import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import LoginIdentity, User, WebSession, identifier, timestamp

router = APIRouter(prefix="/auth")
MICROSOFT_ISSUER = (
    "https://login.microsoftonline.com/9188040d-6c67-4c5b-b112-36a304b66dad/v2.0"
)
ISSUERS = {
    "github": "https://github.com",
    "google": "https://accounts.google.com",
    "microsoft-entra-id": MICROSOFT_ISSUER,
}


def canonical_uuid(value) -> str:
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("Invalid identifier")
    return value


def decode_assertion(request: Request, audience: str) -> dict:
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Authentication required")
    try:
        claims = jwt.decode(
            authorization[7:], get_settings().internal_secret, algorithms=["HS256"],
            audience=audience, issuer="wagl-web",
            options={"require": ["exp", "iat", "sub", "aud", "iss", "sid"]},
        )
        if claims["exp"] - claims["iat"] > 60:
            raise ValueError("Assertion lifetime exceeded")
        canonical_uuid(claims["sid"])
        return claims
    except (jwt.PyJWTError, ValueError, TypeError):
        raise HTTPException(401, "Invalid authentication") from None


def valid_session(database: Session, owner: str, sid: str) -> WebSession:
    session = database.get(WebSession, sid)
    user = database.get(User, owner)
    if (
        session is None or user is None or user.status != "active"
        or session.user_id != owner or session.revoked_at is not None
        or datetime.fromisoformat(session.expires_at) <= datetime.now(UTC)
    ):
        raise HTTPException(401, "Session expired")
    return session


@router.post("/bootstrap")
def bootstrap(request: Request):
    if get_settings().maintenance_enabled:
        raise HTTPException(503, "maintenance")
    claims = decode_assertion(request, "wagl-login")
    provider, issuer, subject = claims.get("provider"), claims.get("identity_issuer"), claims["sub"]
    name = claims.get("name")
    if (
        not isinstance(provider, str) or provider not in ISSUERS or ISSUERS[provider] != issuer
        or not isinstance(subject, str) or not 1 <= len(subject) <= 256
        or (provider == "github" and not subject.isdecimal())
        or not isinstance(name, str) or not 1 <= len(name) <= 200
    ):
        raise HTTPException(401, "Invalid login identity")
    key = hashlib.sha256(json.dumps(
        [provider, issuer, subject], ensure_ascii=True, separators=(",", ":"),
    ).encode()).hexdigest()
    with Session(request.app.state.engine) as database:
        for retry in range(2):
            try:
                identity = database.scalar(select(LoginIdentity).where(
                    LoginIdentity.identity_key == key,
                ))
                if identity is None:
                    user = User(id=identifier())
                    database.add(user)
                    database.flush()
                    identity = LoginIdentity(
                        id=identifier(), user_id=user.id, identity_key=key, provider=provider,
                        issuer=issuer, subject=subject, name=name,
                    )
                    database.add(identity)
                    database.flush()
                elif (identity.provider, identity.issuer, identity.subject) != (
                    provider, issuer, subject,
                ):
                    raise HTTPException(401, "Invalid login identity")
                user = database.get(User, identity.user_id)
                if user is None or user.status != "active":
                    raise HTTPException(401, "Account unavailable")
                session = database.get(WebSession, claims["sid"])
                if session is None:
                    session = WebSession(
                        id=claims["sid"], user_id=user.id, identity_id=identity.id,
                        expires_at=(datetime.now(UTC) + timedelta(hours=24)).isoformat(),
                    )
                    database.add(session)
                elif session.identity_id != identity.id:
                    raise HTTPException(401, "Invalid login session")
                identity.name = name
                database.commit()
                valid_session(database, user.id, session.id)
                return {
                    "user_id": user.id, "session_id": session.id, "provider": provider,
                    "name": identity.name, "expires_at": session.expires_at,
                }
            except IntegrityError:
                database.rollback()
                if retry:
                    raise HTTPException(409, "Login conflict; please retry") from None


@router.get("/session")
def session_info(request: Request):
    from app.security import authenticated_owner

    owner = authenticated_owner(request)
    with Session(request.app.state.engine) as database:
        session = valid_session(database, owner, request.state.session_id)
        identity = database.get(LoginIdentity, session.identity_id)
        if identity is None or identity.user_id != owner:
            raise HTTPException(401, "Session expired")
        return {
            "user_id": owner, "session_id": session.id, "provider": identity.provider,
            "name": identity.name, "expires_at": session.expires_at,
        }


@router.post("/logout")
async def logout(request: Request):
    from app.security import authenticated_owner

    owner = authenticated_owner(request)
    sid = request.state.session_id
    with Session(request.app.state.engine) as database:
        session = valid_session(database, owner, sid)
        session.revoked_at = timestamp()
        database.commit()
    if request.app.state.active_sessions.get(owner) == sid:
        task = request.app.state.active.get(owner)
        if task:
            task.cancel()
    return {"status": "signed_out"}


def session_is_active(engine, owner: str, sid: str) -> bool:
    try:
        with Session(engine) as database:
            valid_session(database, owner, sid)
    except HTTPException:
        return False
    return True
