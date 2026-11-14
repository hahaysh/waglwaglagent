import asyncio
import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Credential, OAuthAttempt, identifier, session_for, timestamp
from app.security import (
    authenticated_owner,
    decrypt_key,
    decrypt_oauth,
    encrypt_key,
    encrypt_oauth,
    key_fingerprint,
)

router = APIRouter()


class OAuthStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    binding: SecretStr = Field(min_length=32, max_length=128)


class OAuthComplete(OAuthStart):
    state: SecretStr = Field(min_length=32, max_length=128)
    code: SecretStr | None = Field(default=None, min_length=1, max_length=512)
    error: str | None = Field(default=None, max_length=100)


def configured() -> bool:
    settings = get_settings()
    return bool(settings.copilot_client_id and settings.copilot_client_secret)


def usage_state(credential: Credential) -> str:
    if credential.auth_status != "authenticated" or (
        credential.expires_at and credential.expires_at <= timestamp()
    ):
        return "reauth_required"
    if credential.provider == "copilot":
        reason = credential.quota_snapshot.get("reason")
        if reason in {"copilot_plan_not_free", "copilot_overage_enabled"}:
            return "copilot_check_required"
        if reason and reason != "available":
            return reason
    if not credential.approved:
        return "consent_required"
    if credential.provider == "copilot":
        if credential.upstreams != ["github-copilot"]:
            return "copilot_consent_required"
        return credential.quota_snapshot.get("reason", "copilot_check_required")
    if credential.provider in {"openai", "anthropic"}:
        return "paid_calls_disabled"
    if credential.status != "valid" or not credential.model:
        return "free_eligibility_unknown"
    return "available"


@router.get("/connection-options")
async def connection_options(owner: str = Depends(authenticated_owner)):
    return {"copilot_oauth": configured(), "copilot_inference": True, "paid_inference": False}


@router.post("/connections/copilot/start")
async def start(
    body: OAuthStart,
    request: Request,
    owner: str = Depends(authenticated_owner),
    database: Session = Depends(session_for),
):
    if not configured():
        raise HTTPException(503, "copilot_not_configured")
    await request.app.state.limits.rate_limit(owner, "oauth", 10)
    now = datetime.now(UTC)
    database.execute(delete(OAuthAttempt).where(OAuthAttempt.expires_at <= now.isoformat()))
    state, verifier, attempt_id = secrets.token_urlsafe(32), secrets.token_urlsafe(32), identifier()
    callback = get_settings().public_url.rstrip("/") + "/api/connections/copilot/callback"
    database.add(OAuthAttempt(
        id=attempt_id, owner_id=owner, provider="copilot", state_hash=key_fingerprint(state),
        binding_hash=key_fingerprint(body.binding.get_secret_value()),
        encrypted_verifier=encrypt_key(verifier, owner, f"{attempt_id}:pkce"),
        redirect_uri=callback, expires_at=(now + timedelta(minutes=10)).isoformat(),
    ))
    database.commit()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode()
    return {"authorization_url": "https://github.com/login/oauth/authorize?" + urlencode({
        "client_id": get_settings().copilot_client_id, "redirect_uri": callback,
        "scope": "read:user", "state": state,
        "code_challenge": challenge.rstrip("="), "code_challenge_method": "S256",
    })}


def token_fields(payload: dict) -> dict:
    if (
        not isinstance(payload.get("access_token"), str)
        or not payload["access_token"].startswith("gho_")
        or not isinstance(payload.get("token_type"), str)
        or payload["token_type"].lower() != "bearer"
        or not isinstance(payload.get("scope"), str)
    ):
        raise ValueError("Invalid OAuth response")
    result = {
        "access_token": payload["access_token"], "token_type": "bearer",
        "scopes": payload["scope"].replace(",", " ").split(),
    }
    if "refresh_token" in payload:
        if not isinstance(payload["refresh_token"], str) or not payload["refresh_token"]:
            raise ValueError("Invalid refresh token")
        result["refresh_token"] = payload["refresh_token"]
    for source, target in (
        ("expires_in", "expires_at"), ("refresh_token_expires_in", "refresh_expires_at"),
    ):
        if source in payload:
            seconds = payload[source]
            if type(seconds) is not int or not 0 < seconds <= 31_536_000:
                raise ValueError("Invalid token expiration")
            result[target] = (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()
    return result


async def exchange(client: httpx.AsyncClient, code: str, verifier: str, callback: str) -> dict:
    settings = get_settings()
    try:
        response = await client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": settings.copilot_client_id,
                "client_secret": settings.copilot_client_secret,
                "code": code, "redirect_uri": callback, "code_verifier": verifier,
            },
        )
        response.raise_for_status()
        result = token_fields(response.json())
        user = await client.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {result['access_token']}",
                     "Accept": "application/vnd.github+json"},
        )
        user.raise_for_status()
        identity = user.json()
        if type(identity.get("id")) is not int:
            raise ValueError("Invalid account")
        return result | {"subject": str(identity["id"])}
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        raise HTTPException(502, "oauth_exchange_failed") from None


@router.post("/connections/copilot/complete")
async def complete(
    body: OAuthComplete,
    request: Request,
    owner: str = Depends(authenticated_owner),
    database: Session = Depends(session_for),
):
    async with request.app.state.connection_lock:
        return await complete_connection(body, request, owner, database)


async def complete_connection(
    body: OAuthComplete, request: Request, owner: str, database: Session,
):
    attempt = database.scalar(select(OAuthAttempt).where(
        OAuthAttempt.owner_id == owner, OAuthAttempt.provider == "copilot",
        OAuthAttempt.state_hash == key_fingerprint(body.state.get_secret_value()),
    ))
    if (
        not attempt or attempt.expires_at <= timestamp()
        or not hmac.compare_digest(
            attempt.binding_hash, key_fingerprint(body.binding.get_secret_value())
        )
    ):
        raise HTTPException(400, "oauth_invalid_state")
    if attempt.status == "completed":
        existing = database.get(Credential, attempt.connection_id)
        if existing and existing.owner_id == owner:
            return {"id": existing.id}
        raise HTTPException(400, "oauth_invalid_state")
    claimed = database.execute(update(OAuthAttempt).where(
        OAuthAttempt.id == attempt.id, OAuthAttempt.status == "pending",
    ).values(status="processing"))
    database.commit()
    if claimed.rowcount != 1:
        raise HTTPException(409, "oauth_invalid_state")
    verifier = decrypt_key(attempt.encrypted_verifier, owner, f"{attempt.id}:pkce")
    attempt.encrypted_verifier = None
    database.commit()
    try:
        if body.error or not body.code:
            raise HTTPException(400, "oauth_cancelled")
        if not configured():
            raise HTTPException(503, "copilot_not_configured")
        tokens = await exchange(
            request.app.state.providers.client, body.code.get_secret_value(),
            verifier, attempt.redirect_uri,
        )
        database.refresh(attempt)
        if attempt.status != "processing":
            raise HTTPException(409, "oauth_invalid_state")
        existing = database.scalar(select(Credential).where(
            Credential.owner_id == owner, Credential.provider == "copilot",
            Credential.provider_subject == tokens["subject"],
        ))
        if existing:
            credential = existing
        else:
            count = database.scalar(select(func.count()).select_from(Credential).where(
                Credential.owner_id == owner,
            ))
            if count >= 5:
                raise HTTPException(409, "Credential limit reached")
            credential = Credential(
                id=identifier(), owner_id=owner, provider="copilot",
                label="GitHub Copilot", model=None, provider_subject=tokens["subject"],
                auth_type="oauth", secret_format="oauth_v1",
            )
            database.add(credential)
        credential.encrypted_key = await asyncio.to_thread(
            encrypt_oauth, tokens, owner, credential.id,
        )
        credential.scopes = tokens["scopes"]
        credential.expires_at = tokens.get("expires_at")
        credential.auth_status = "authenticated"
        credential.status = "unverified"
        credential.approved = False
        credential.consent_version = identifier()
        credential.checked_at = timestamp()
        credential.token_version = (credential.token_version or 0) + 1
        credential.quota_snapshot = {"source": "copilot_eligibility_unknown"}
        attempt.status = "completed"
        attempt.connection_id = credential.id
        database.commit()
        return {"id": credential.id}
    except (HTTPException, IntegrityError) as error:
        database.rollback()
        attempt.status = "failed"
        attempt.encrypted_verifier = None
        database.commit()
        if isinstance(error, IntegrityError):
            raise HTTPException(409, "oauth_connection_conflict") from None
        raise


async def verify_copilot(
    client: httpx.AsyncClient, credential: Credential, database: Session,
) -> dict:
    token = await asyncio.to_thread(
        decrypt_oauth, credential.encrypted_key, credential.owner_id, credential.id,
    )
    if credential.expires_at and credential.expires_at <= (
        datetime.now(UTC) + timedelta(seconds=60)
    ).isoformat():
        if not token.get("refresh_token") or (
            token.get("refresh_expires_at") and token["refresh_expires_at"] <= timestamp()
        ):
            credential.auth_status = "reauth_required"
            return {"status": "invalid", "source": "reauth_required"}
        settings = get_settings()
        version = credential.token_version
        try:
            response = await client.post(
                "https://github.com/login/oauth/access_token",
                headers={"Accept": "application/json"},
                data={"client_id": settings.copilot_client_id,
                      "client_secret": settings.copilot_client_secret,
                      "grant_type": "refresh_token", "refresh_token": token["refresh_token"]},
            )
            response.raise_for_status()
            refreshed = response.json()
            if refreshed.get("error"):
                if refreshed["error"] in {"bad_refresh_token", "invalid_grant", "expired_token"}:
                    credential.auth_status = "reauth_required"
                    return {"status": "invalid", "source": "reauth_required"}
                raise HTTPException(503, "verification_unavailable")
            fields = token_fields(refreshed)
            if "refresh_token" not in fields or "expires_at" not in fields:
                raise HTTPException(503, "verification_unavailable")
            token = token | fields
            changed = database.execute(update(Credential).where(
                Credential.id == credential.id, Credential.owner_id == credential.owner_id,
                Credential.token_version == version,
            ).values(
                encrypted_key=await asyncio.to_thread(
                    encrypt_oauth, token, credential.owner_id, credential.id,
                ),
                expires_at=token["expires_at"], scopes=token["scopes"], token_version=version + 1,
            ))
            if changed.rowcount != 1:
                database.rollback()
                raise HTTPException(409, "oauth_connection_conflict")
            database.commit()
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            raise HTTPException(503, "verification_unavailable") from None
    try:
        response = await client.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {token['access_token']}"},
        )
        if response.status_code == 401:
            credential.auth_status = "reauth_required"
            return {"status": "invalid", "source": "reauth_required"}
        response.raise_for_status()
        if str(response.json().get("id")) != credential.provider_subject:
            credential.auth_status = "reauth_required"
            credential.status = "invalid"
            database.commit()
            raise HTTPException(409, "oauth_account_mismatch")
        credential.auth_status = "authenticated"
        return {"status": "unverified", "source": "copilot_eligibility_unknown"}
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        raise HTTPException(503, "verification_unavailable") from None


async def revoke_copilot(client: httpx.AsyncClient, tokens: dict) -> bool:
    settings = get_settings()
    try:
        response = await client.request(
            "DELETE",
            f"https://api.github.com/applications/{settings.copilot_client_id}/token",
            auth=httpx.BasicAuth(settings.copilot_client_id, settings.copilot_client_secret),
            json={"access_token": tokens["access_token"]},
        )
        return response.status_code in {204, 404}
    except httpx.HTTPError:
        return False
