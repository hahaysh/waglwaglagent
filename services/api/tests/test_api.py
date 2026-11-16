import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import httpx
import jwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image
from redis.exceptions import RedisError
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy import select
from sqlalchemy.dialects import mssql
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.accounts import ISSUERS
from app.config import get_settings
from app.main import app, cancel, execute_stream
from app.models import (
    Conversation,
    Credential,
    LoginIdentity,
    Message,
    OAuthAttempt,
    Run,
    User,
    WebSession,
)
from app.providers import ProviderError
from app.routing import Candidate, Failure
from app.security import decrypt_oauth
from app.vault import SecretStoreError

OWNER_A = "11111111-1111-4111-8111-111111111111"
OWNER_B = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WAGL_INTERNAL_SECRET", "test-internal-secret-" * 3)
    monkeypatch.setenv("WAGL_ENCRYPTION_KEY", base64.b64encode(bytes(range(32))).decode())
    monkeypatch.setenv("WAGL_DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("WAGL_ENVIRONMENT", "local")
    monkeypatch.setenv("WAGL_REDIS_URL", "")
    get_settings.cache_clear()
    with TestClient(app) as test_client:
        with Session(app.state.engine) as database:
            for identity in (OWNER_A, OWNER_B):
                database.add(User(id=identity))
                database.flush()
                database.add(LoginIdentity(
                    id=identity, user_id=identity, identity_key=identity, provider="github",
                    issuer=ISSUERS["github"], subject=identity, name="Test",
                ))
                database.flush()
                database.add(WebSession(
                    id=identity, user_id=identity, identity_id=identity,
                    expires_at=(datetime.now(UTC) + timedelta(hours=24)).isoformat(),
                ))
            database.commit()
        app.state.providers.endpoints = AsyncMock(
            return_value=[
                {
                    "id": "approved/bf16",
                    "name": "Approved",
                    "context_length": 32000,
                    "max_completion_tokens": 2048,
                }
            ]
        )
        app.state.providers.validate = AsyncMock(
            return_value={"status": "valid", "source": "official"}
        )
        app.state.copilot.verify = AsyncMock(return_value={
            "status": "unverified", "reason": "copilot_overage_in_use",
            "source": "copilot_sdk", "plan": "enterprise",
        })
        yield test_client
    get_settings.cache_clear()


def headers(owner=OWNER_A, sid=None):
    token = jwt.encode(
        {
            "sub": f"user:{owner}",
            "sid": sid or owner,
            "iss": "wagl-web",
            "aud": "wagl-api",
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(minutes=1),
        },
        get_settings().internal_secret,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def login_assertion(login_provider="google", subject="external-account", **overrides):
    claims = {
        "sub": subject, "sid": str(uuid4()), "provider": login_provider,
        "identity_issuer": ISSUERS[login_provider], "name": "Same display name",
        "iss": "wagl-web", "aud": "wagl-login",
        "iat": datetime.now(UTC), "exp": datetime.now(UTC) + timedelta(seconds=60),
    } | overrides
    return {"Authorization": "Bearer " + jwt.encode(
        claims, get_settings().internal_secret, algorithm="HS256",
    )}


def test_login_identity_reuse_concurrency_and_same_email_never_merge(client):
    assertion = login_assertion(email="same@example.invalid")
    first = client.post("/auth/bootstrap", headers=assertion).json()
    with ThreadPoolExecutor(max_workers=3) as executor:
        responses = list(executor.map(lambda _: client.post(
            "/auth/bootstrap", headers=login_assertion(email="same@example.invalid"),
        ), range(3)))
    assert all(response.status_code == 200 for response in responses)
    assert {response.json()["user_id"] for response in responses} == {first["user_id"]}
    other = client.post("/auth/bootstrap", headers=login_assertion(
        "microsoft-entra-id", email="same@example.invalid",
    )).json()
    assert first["user_id"] != other["user_id"]
    assert first["session_id"] != other["session_id"]
    with Session(app.state.engine) as database:
        identity = database.scalar(select(LoginIdentity).where(
            LoginIdentity.user_id == first["user_id"],
        ))
        assert identity.name == "Same display name"
        assert not hasattr(identity, "email")


def test_bootstrap_boundary_issuer_subject_and_normal_tokens_are_not_interchangeable(client):
    assert client.post("/auth/bootstrap", headers=headers()).status_code == 401
    assertion = login_assertion()
    assert client.get("/credentials", headers=assertion).status_code == 401
    for override in (
        {"identity_issuer": "https://accounts.google.com.evil.test"},
        {"provider": ["google"]}, {"sub": ""}, {"sid": "not-a-session"},
    ):
        assert client.post(
            "/auth/bootstrap", headers=login_assertion(**override),
        ).status_code == 401
    for subject in ("external-account", "External-account"):
        response = client.post("/auth/bootstrap", headers=login_assertion(subject=subject))
        assert response.status_code == 200
    with Session(app.state.engine) as database:
        assert len(list(database.scalars(select(LoginIdentity).where(
            LoginIdentity.provider == "google",
        )))) == 2
    legacy = jwt.encode({
        "sub": "github:1", "sid": OWNER_A, "iss": "wagl-web", "aud": "wagl-api",
        "iat": datetime.now(UTC), "exp": datetime.now(UTC) + timedelta(seconds=60),
    }, get_settings().internal_secret, algorithm="HS256")
    assert client.get("/credentials", headers={
        "Authorization": f"Bearer {legacy}",
    }).status_code == 401


def test_session_expiry_revocation_and_wrong_owner_fail_closed(client):
    key = add_key(client)
    other_device = str(uuid4())
    with Session(app.state.engine) as database:
        database.add(WebSession(
            id=other_device, user_id=OWNER_A, identity_id=OWNER_A,
            expires_at=(datetime.now(UTC) + timedelta(hours=24)).isoformat(),
        ))
        database.commit()
    assert client.get("/auth/session", headers=headers()).json()["user_id"] == OWNER_A
    wrong_sid = jwt.encode({
        "sub": f"user:{OWNER_B}", "sid": OWNER_A, "iss": "wagl-web", "aud": "wagl-api",
        "iat": datetime.now(UTC), "exp": datetime.now(UTC) + timedelta(seconds=60),
    }, get_settings().internal_secret, algorithm="HS256")
    assert client.get("/credentials", headers={
        "Authorization": f"Bearer {wrong_sid}",
    }).status_code == 401
    assert client.post("/auth/logout", headers=headers()).status_code == 200
    assert client.get("/credentials", headers=headers()).status_code == 401
    assert client.get("/credentials", headers=headers(OWNER_A, other_device)).status_code == 200
    assert client.get("/credentials", headers=headers(OWNER_B)).status_code == 200
    with Session(app.state.engine) as database:
        assert database.get(Credential, key["id"]) is not None
        session = database.get(WebSession, OWNER_B)
        session.expires_at = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        database.commit()
    assert client.get("/credentials", headers=headers(OWNER_B)).status_code == 401


def test_readiness_checks_database_and_redis(client, monkeypatch):
    redis = SimpleNamespace(ping=AsyncMock(return_value=True), aclose=AsyncMock())
    monkeypatch.setattr(app.state.limits, "redis", redis)
    assert client.get("/ready").status_code == 200
    redis.ping.assert_awaited_once()
    redis.ping.side_effect = RedisError("unavailable")
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert client.get("/health").status_code == 200


def test_readiness_blocks_database_outage(client, monkeypatch):
    monkeypatch.setattr(app.state.engine, "connect", Mock(
        side_effect=OperationalError("SELECT 1", {}, RuntimeError("unavailable")),
    ))
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


def add_key(client, **overrides):
    payload = {
        "provider": "openrouter",
        "label": "Personal key",
        "api_key": "private-test-key",
        "model": "vendor/model:free",
        "upstreams": ["approved/bf16"],
        "approved": True,
    } | overrides
    payload["api_key"] = (
        "private-test-key-" + str(payload.get("priority", 0))
    )
    response = client.post("/credentials", json=payload, headers=headers())
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["approved"] is payload["approved"]
    return result


def test_connection_creation_stores_explicit_consent_but_defaults_to_inactive(client):
    saved = add_key(client)
    assert saved["usage_state"] == "available"
    assert client.get("/credentials", headers=headers()).json()[0]["approved"] is True
    inactive = client.post("/credentials", headers=headers(), json={
        "provider": "openrouter", "label": "No consent", "api_key": "another-private-key",
        "model": "vendor/model:free", "upstreams": ["approved/bf16"],
    })
    assert inactive.status_code == 201
    assert inactive.json()["approved"] is False
    assert inactive.json()["usage_state"] == "consent_required"
    rejected = client.post("/credentials", headers=headers(), json={
        "provider": "openrouter", "label": "Wrong upstream", "api_key": "third-private-key",
        "model": "vendor/model:free", "upstreams": ["unknown-provider"], "approved": True,
    })
    assert rejected.status_code == 422


def test_vault_connection_lifecycle_and_fail_closed_writes(client, monkeypatch):
    settings = get_settings()
    settings.key_vault_url = "https://test.vault.azure.net/"
    vault, secrets = Mock(), {}

    def store(name, value, **_):
        secrets[name] = value
        return SimpleNamespace(properties=SimpleNamespace(version="a" * 32))

    def remove(name):
        secrets.pop(name)
        return Mock()

    vault.set_secret.side_effect = store
    vault.get_secret.side_effect = lambda name, **_: SimpleNamespace(value=secrets[name])
    vault.begin_delete_secret.side_effect = remove
    monkeypatch.setattr("app.security.secret_client", lambda: vault)
    key = add_key(client)
    with Session(app.state.engine) as database:
        assert database.get(Credential, key["id"]).encrypted_key.startswith("kv://")
    assert client.post(f"/credentials/{key['id']}/verify", headers=headers()).status_code == 200
    assert client.delete(f"/credentials/{key['id']}", headers=headers()).status_code == 204
    assert not secrets
    vault.set_secret.side_effect = SecretStoreError("test vault unavailable")
    response = client.post("/credentials", headers=headers(), json={
        "provider": "openai", "label": "Vault failure", "api_key": "private-vault-test-key",
    })
    assert response.status_code == 503
    assert response.json() == {"detail": "secret_store_unavailable"}
    assert client.get("/credentials", headers=headers()).json() == []


def test_authentication_and_key_isolation(client):
    assert client.get("/credentials").status_code == 401
    key = add_key(client)
    assert "private-test-key" not in str(key)
    assert "encrypted_key" not in key
    assert client.get("/credentials", headers=headers(OWNER_B)).json() == []
    for method in ("delete", "patch"):
        response = client.request(
            method,
            f"/credentials/{key['id']}",
            headers=headers(OWNER_B),
            json={"approved": False} if method == "patch" else None,
        )
        assert response.status_code == 404
    with Session(app.state.engine) as database:
        record = database.scalar(select(Credential))
        assert "private-test-key" not in record.encrypted_key


def test_invalid_input_never_echoes_secret(client):
    response = client.post(
        "/credentials",
        headers=headers(),
        json={
            "provider": "unknown",
            "api_key": "my-super-secret-key",
        },
    )
    assert response.status_code == 422
    assert "my-super-secret-key" not in response.text


def oauth_setup(monkeypatch, *, revoke_status=204):
    monkeypatch.setenv("WAGL_COPILOT_CLIENT_ID", "test-oauth-client")
    monkeypatch.setenv("WAGL_COPILOT_CLIENT_SECRET", "test-oauth-secret")
    get_settings.cache_clear()
    calls = []

    async def send(_client, request, **_kwargs):
        calls.append(request)
        if request.url.path == "/login/oauth/access_token":
            form = parse_qs(request.content.decode())
            if form.get("grant_type") == ["refresh_token"]:
                return httpx.Response(200, request=request, json={
                    "access_token": "gho_refreshed-test", "refresh_token": "refresh-rotated",
                    "expires_in": 28800, "scope": "read:user", "token_type": "bearer",
                })
            assert form.get("code_verifier")
            return httpx.Response(200, request=request, json={
                "access_token": "gho_private-test-token", "token_type": "bearer",
                "scope": "read:user", "refresh_token": "refresh-test", "expires_in": 28800,
            })
        if request.url.path == "/user":
            return httpx.Response(200, request=request, json={"id": 123})
        if request.method == "DELETE":
            return httpx.Response(revoke_status, request=request)
        raise AssertionError(f"Unexpected provider request: {request.url.path}")

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    return calls


def oauth_attempt(client, approved=False):
    response = client.post("/connections/copilot/start", headers=headers(),
                           json={"binding": "browser-binding-test-" * 3, "approved": approved})
    assert response.status_code == 200
    url = urlparse(response.json()["authorization_url"])
    query = parse_qs(url.query)
    assert query["code_challenge_method"] == ["S256"]
    return {"state": query["state"][0], "binding": "browser-binding-test-" * 3,
            "code": "test-auth-code"}


def test_oauth_owner_browser_binding_replay_and_inactive_storage(client, monkeypatch):
    calls = oauth_setup(monkeypatch)
    body = oauth_attempt(client)
    path = "/connections/copilot/complete"
    assert client.post(path, headers=headers(OWNER_B), json=body).status_code == 400
    wrong_binding = client.post(
        path, headers=headers(), json=body | {"binding": "wrong-binding-" * 4},
    )
    assert wrong_binding.status_code == 400
    assert calls == []
    completed = client.post(path, headers=headers(), json=body)
    assert completed.status_code == 200, completed.text
    assert client.post(path, headers=headers(), json=body).json() == completed.json()
    assert len(calls) == 2
    listed = client.get("/credentials", headers=headers()).json()
    assert len(listed) == 1
    assert listed[0]["approved"] is False
    assert listed[0]["usage_state"] == "consent_required"
    assert "gho_" not in str(listed) and "refresh-test" not in str(listed)
    with Session(app.state.engine) as database:
        credential = database.get(Credential, listed[0]["id"])
        assert "gho_" not in credential.encrypted_key
        tokens = decrypt_oauth(credential.encrypted_key, credential.owner_id, credential.id)
        assert tokens["access_token"].startswith("gho_")
        assert database.scalar(select(OAuthAttempt)).encrypted_verifier is None
    reauth = oauth_attempt(client)
    assert client.post(path, headers=headers(), json=reauth).json() == completed.json()
    assert len(client.get("/credentials", headers=headers()).json()) == 1


def test_oauth_consent_is_bound_to_start_and_persists_on_same_account_reauth(client, monkeypatch):
    oauth_setup(monkeypatch)
    path = "/connections/copilot/complete"
    body = oauth_attempt(client, approved=True)
    assert client.post(path, headers=headers(OWNER_B), json=body).status_code == 400
    completed = client.post(path, headers=headers(), json=body)
    assert completed.status_code == 200
    saved = client.get("/credentials", headers=headers()).json()[0]
    assert saved["approved"] is True
    assert saved["upstreams"] == ["github-copilot"]
    assert saved["usage_state"] != "available"
    reauth = oauth_attempt(client)
    assert client.post(path, headers=headers(), json=reauth).json() == completed.json()
    assert client.get("/credentials", headers=headers()).json()[0]["approved"] is True
    client.patch(f"/credentials/{saved['id']}", headers=headers(), json={"approved": False})
    pending = oauth_attempt(client)
    tampered = client.post(path, headers=headers(), json=pending | {"approved": True})
    assert tampered.status_code == 422
    assert client.post(path, headers=headers(), json=pending).status_code == 200
    assert client.get("/credentials", headers=headers()).json()[0]["approved"] is False


def test_cancelled_oauth_does_not_save_connection_or_consent(client, monkeypatch):
    calls = oauth_setup(monkeypatch)
    body = oauth_attempt(client, approved=True)
    response = client.post("/connections/copilot/complete", headers=headers(),
                           json=body | {"code": None, "error": "access_denied"})
    assert response.json()["detail"] == "oauth_cancelled"
    assert calls == []
    assert client.get("/credentials", headers=headers()).json() == []


def test_copilot_lookup_failure_invalidates_cached_conditions_not_consent(client, monkeypatch):
    oauth_setup(monkeypatch)
    app.state.copilot.verify = AsyncMock(return_value={
        "status": "valid", "reason": "available", "source": "copilot_sdk",
    })
    key = client.post("/connections/copilot/complete", headers=headers(),
                      json=oauth_attempt(client, approved=True)).json()["id"]
    assert client.post(f"/credentials/{key}/verify", headers=headers()).json()[
        "usage_state"
    ] == "available"
    monkeypatch.setattr("app.main.verify_copilot", AsyncMock(
        side_effect=HTTPException(503, "verification_unavailable"),
    ))
    assert client.post(f"/credentials/{key}/verify", headers=headers()).status_code == 503
    saved = client.get("/credentials", headers=headers()).json()[0]
    assert saved["approved"] is True
    assert saved["status"] == "unverified"
    assert saved["usage_state"] == "verification_unavailable"


def test_oauth_cancel_expiry_and_delete_never_recreate_connection(client, monkeypatch):
    oauth_setup(monkeypatch, revoke_status=500)
    body = oauth_attempt(client)
    path = "/connections/copilot/complete"
    cancelled = client.post(
        path, headers=headers(), json=body | {"code": None, "error": "access_denied"},
    )
    assert cancelled.json()["detail"] == "oauth_cancelled"
    assert client.post(path, headers=headers(), json=body).status_code == 409
    with Session(app.state.engine) as database:
        assert database.scalar(select(OAuthAttempt)).encrypted_verifier is None
    expired = oauth_attempt(client)
    with Session(app.state.engine) as database:
        attempt = database.scalar(select(OAuthAttempt).where(OAuthAttempt.status == "pending"))
        attempt.expires_at = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
        database.commit()
    assert client.post(path, headers=headers(), json=expired).status_code == 400
    body = oauth_attempt(client)
    completed = client.post(path, headers=headers(), json=body).json()
    pending = oauth_attempt(client)
    removed = client.delete(f"/credentials/{completed['id']}", headers=headers())
    assert removed.json()["detail"] == "local_disconnect_only"
    assert client.get("/credentials", headers=headers()).json() == []
    assert client.post(path, headers=headers(), json=body).status_code == 409
    assert client.post(path, headers=headers(), json=pending).status_code == 409


def test_oauth_expired_token_refresh_updates_encrypted_bundle_and_version(client, monkeypatch):
    calls = oauth_setup(monkeypatch)
    body = oauth_attempt(client)
    key_id = client.post("/connections/copilot/complete", headers=headers(), json=body).json()["id"]
    with Session(app.state.engine) as database:
        credential = database.get(Credential, key_id)
        previous_version = credential.token_version
        credential.expires_at = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        database.commit()
    response = client.post(f"/credentials/{key_id}/verify", json={}, headers=headers())
    assert response.status_code == 200
    assert response.json()["status"] == "unverified"
    with Session(app.state.engine) as database:
        credential = database.get(Credential, key_id)
        tokens = decrypt_oauth(credential.encrypted_key, credential.owner_id, credential.id)
        assert tokens["refresh_token"] == "refresh-rotated"
        assert credential.token_version == previous_version + 1
    assert len(calls) == 4


@pytest.mark.parametrize("reply,expected", [
    ({"error": "bad_refresh_token"}, 200),
    ({"unexpected": "response"}, 503),
    ([], 503),
])
def test_oauth_refresh_failures_preserve_secret_and_require_reauth_when_revoked(
    client, monkeypatch, reply, expected,
):
    oauth_setup(monkeypatch)
    key_id = client.post("/connections/copilot/complete", headers=headers(),
                         json=oauth_attempt(client)).json()["id"]
    with Session(app.state.engine) as database:
        credential = database.get(Credential, key_id)
        original = credential.encrypted_key
        credential.expires_at = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        database.commit()

    async def send(_client, request, **_kwargs):
        return httpx.Response(200, request=request, json=reply)

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    response = client.post(f"/credentials/{key_id}/verify", json={}, headers=headers())
    assert response.status_code == expected
    with Session(app.state.engine) as database:
        credential = database.get(Credential, key_id)
        assert credential.encrypted_key == original
        if expected == 200:
            assert credential.auth_status == "reauth_required"


def test_oauth_concurrent_verification_rotates_refresh_token_only_once(client, monkeypatch):
    calls = oauth_setup(monkeypatch)
    key_id = client.post("/connections/copilot/complete", headers=headers(),
                         json=oauth_attempt(client)).json()["id"]
    with Session(app.state.engine) as database:
        credential = database.get(Credential, key_id)
        credential.expires_at = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        database.commit()
    send = httpx.AsyncClient.send

    async def delayed(*args, **kwargs):
        await asyncio.sleep(0.02)
        return await send(*args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "send", delayed)
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: client.post(
            f"/credentials/{key_id}/verify", json={}, headers=headers(),
        ).status_code, range(2)))
    assert results == [200, 200]
    refreshes = [request for request in calls if
                 b"grant_type=refresh_token" in request.content]
    assert len(refreshes) == 1


def free_copilot(client, monkeypatch, plan="free"):
    oauth_setup(monkeypatch)
    key_id = client.post("/connections/copilot/complete", headers=headers(),
                         json=oauth_attempt(client)).json()["id"]
    response = client.patch(f"/credentials/{key_id}", headers=headers(), json={
        "approved": True, "upstreams": ["github-copilot"],
    })
    assert response.status_code == 200
    snapshot = {
        "status": "valid", "source": "copilot_sdk", "plan": plan, "reason": "available",
        "valid_until": (datetime.now(UTC) + timedelta(seconds=60)).isoformat(),
    }
    app.state.copilot.verify = AsyncMock(return_value=snapshot)
    return key_id, snapshot


@pytest.mark.parametrize("plan", ["free", "enterprise"])
def test_copilot_included_chat_uses_owner_oauth_and_persists_provenance(client, monkeypatch, plan):
    key_id, snapshot = free_copilot(client, monkeypatch, plan)
    checked = client.post(f"/credentials/{key_id}/verify", json={}, headers=headers())
    assert checked.json()["usage_state"] == "available"
    calls = []

    async def stream(token, messages):
        calls.append((token, messages))
        yield {"type": "eligibility", "snapshot": snapshot}
        yield {"type": "delta", "text": "무료 Copilot 응답"}
        yield {"type": "usage", "usage": {"total_tokens": 9}, "model": "free-auto-model"}

    app.state.copilot.stream = stream
    response = client.post("/chat", headers=headers(), json={
        "prompt": "안녕", "request_id": "copilot-free-test", "credential_id": key_id,
    })
    assert response.status_code == 200
    assert "무료 Copilot 응답" in response.text and "event: done" in response.text
    assert "gho_" not in response.text
    assert len(calls) == 1 and calls[0][0].startswith("gho_")
    assert calls[0][1] == [{"role": "user", "content": "안녕"}]
    with Session(app.state.engine) as database:
        message = database.scalar(select(Message).where(Message.role == "assistant"))
        assert message.provider == "copilot" and message.model == "free-auto-model"
        assert message.status == "complete"
    denied = client.post("/chat", headers=headers(OWNER_B), json={
        "prompt": "Hi", "request_id": "copilot-other-owner", "credential_id": key_id,
    })
    assert denied.status_code == 404


def image_attachment():
    image = BytesIO()
    Image.new("RGB", (16, 16), "red").save(image, format="PNG")
    return {
        "name": "screenshot.png", "mime_type": "image/png",
        "data": base64.b64encode(image.getvalue()).decode(),
    }


def test_attachments_reach_model_persist_with_owner_and_return_in_followup(client, monkeypatch):
    key_id, snapshot = free_copilot(client, monkeypatch)
    image = image_attachment()
    document = {
        "name": "notes.txt", "mime_type": "text/plain",
        "data": base64.b64encode("파일 속 테스트 단어: 와글".encode()).decode(),
    }
    calls = []

    async def stream(_token, messages):
        calls.append(messages)
        yield {"type": "eligibility", "snapshot": snapshot}
        yield {"type": "delta", "text": "이미지와 문서를 확인했어요"}

    app.state.copilot.stream = stream
    response = client.post("/chat", headers=headers(), json={
        "request_id": "with-attachments", "attachments": [image, document],
        "credential_id": key_id,
    })
    assert response.status_code == 200 and "event: done" in response.text
    content = calls[0][0]["content"]
    assert "파일 속 테스트 단어: 와글" in content[0]["text"]
    assert content[-1]["image_url"]["url"] == f"data:image/png;base64,{image['data']}"
    chat_id = client.get("/conversations", headers=headers()).json()[0]["id"]
    saved = client.get(f"/conversations/{chat_id}", headers=headers()).json()["messages"]
    assert saved[0]["attachments"] == [image, document]
    assert client.get(f"/conversations/{chat_id}", headers=headers(OWNER_B)).status_code == 404
    followup = client.post("/chat", headers=headers(), json={
        "prompt": "첨부를 다시 설명해줘", "request_id": "attachments-followup",
        "credential_id": key_id, "conversation_id": chat_id,
    })
    assert followup.status_code == 200 and "event: done" in followup.text
    assert calls[1][0] == calls[0][0]
    assert calls[1][-1]["content"] == "첨부를 다시 설명해줘"
    client.delete(f"/conversations/{chat_id}", headers=headers())
    with Session(app.state.engine) as database:
        assert database.scalar(select(Message)) is None


@pytest.mark.parametrize("changes", [
    {"name": "../screenshot.png"},
    {"data": "not-base64"},
    {"data": base64.b64encode(b"not an image").decode()},
    {"mime_type": "image/svg+xml"},
    {"name": "secret.exe", "mime_type": "text/plain"},
])
def test_invalid_attachments_are_rejected_without_echoing_content_or_creating_history(
    client, changes,
):
    response = client.post("/chat", headers=headers(), json={
        "prompt": "test", "request_id": "invalid-attachment",
        "attachments": [image_attachment() | changes],
    })
    assert response.status_code == 422
    assert "not-base64" not in response.text
    assert client.get("/conversations", headers=headers()).json() == []


def test_image_context_never_routes_to_text_only_provider(client):
    add_key(client)
    app.state.providers.stream = AsyncMock()
    response = client.post("/chat", headers=headers(), json={
        "prompt": "이미지 분석", "request_id": "text-only-provider",
        "attachments": [image_attachment()],
    })
    assert response.status_code == 422
    assert response.json()["detail"] == "attachment_provider_unsupported"
    app.state.providers.stream.assert_not_called()


def test_attachment_byte_count_text_encoding_and_file_count_are_bounded():
    from pydantic import ValidationError

    from app.schemas import ChatInput

    image = image_attachment()
    original = base64.b64decode(image["data"])
    padded = image | {"data": base64.b64encode(original.ljust(2 * 1024 * 1024, b"\0")).decode()}
    payload = {"request_id": "size-boundary", "attachments": [padded, padded]}
    assert len(ChatInput.model_validate(payload).attachments) == 2
    with pytest.raises(ValidationError):
        ChatInput.model_validate(payload | {"attachments": [padded, padded, image]})
    for raw, name in [(b"a" * 32769, "large.txt"), (b"\xff\xfe", "bad.txt"),
                      (b"binary\x00text", "binary.txt")]:
        with pytest.raises(ValidationError):
            ChatInput.model_validate(payload | {"attachments": [{
                "name": name, "mime_type": "text/plain", "data": base64.b64encode(raw).decode(),
            }]})
    with pytest.raises(ValidationError):
        ChatInput.model_validate(payload | {"attachments": [image] * 4})


@pytest.mark.parametrize("reason", [
    "copilot_overage_in_use", "copilot_free_eligibility_unknown",
])
def test_copilot_free_gate_returns_real_reason_without_sending_or_saving_prompt(
    client, monkeypatch, reason,
):
    key_id, _snapshot = free_copilot(client, monkeypatch)
    app.state.copilot.verify = AsyncMock(return_value={
        "status": "unverified", "reason": reason, "source": "copilot_sdk",
    })
    app.state.copilot.stream = AsyncMock()
    response = client.post("/chat", headers=headers(), json={
        "prompt": "must-not-send", "request_id": "blocked-copilot", "credential_id": key_id,
    })
    assert response.status_code == 422 and response.json()["detail"] == reason
    app.state.copilot.stream.assert_not_called()
    assert client.get("/conversations", headers=headers()).json() == []
    saved = client.get("/credentials", headers=headers()).json()[0]
    assert saved["usage_state"] == reason


@pytest.mark.parametrize("reason", ["copilot_plan_not_free", "copilot_overage_enabled"])
def test_legacy_block_rechecked_on_chat_without_changing_token_or_consent(
    client, monkeypatch, reason,
):
    key_id, _snapshot = free_copilot(client, monkeypatch, "enterprise")
    with Session(app.state.engine) as database:
        record = database.get(Credential, key_id)
        original_secret = record.encrypted_key
        record.status = "unverified"
        record.quota_snapshot = {
            "status": "unverified", "reason": reason, "plan": "enterprise",
        }
        database.commit()
    saved = client.get("/credentials", headers=headers()).json()[0]
    assert saved["usage_state"] == "copilot_check_required"
    async def stream(_token, _messages):
        yield {"type": "delta", "text": "기존 연결로 응답"}

    app.state.copilot.stream = stream
    response = client.post("/chat", json={
        "prompt": "Hi", "request_id": "recheck-legacy", "credential_id": key_id,
    }, headers=headers())
    assert response.status_code == 200 and "기존 연결로 응답" in response.text
    checked = client.get("/credentials", headers=headers()).json()[0]
    assert checked["usage_state"] == "available"
    assert checked["quota_snapshot"]["plan"] == "enterprise"
    with Session(app.state.engine) as database:
        record = database.get(Credential, key_id)
        assert record.encrypted_key == original_secret
        assert record.approved is True


def test_old_copilot_consent_does_not_authorize_new_model_transmission(client, monkeypatch):
    key_id, _snapshot = free_copilot(client, monkeypatch)
    with Session(app.state.engine) as database:
        record = database.get(Credential, key_id)
        record.upstreams = []
        database.commit()
    response = client.post("/chat", headers=headers(), json={
        "prompt": "Hi", "request_id": "old-consent-copilot", "credential_id": key_id,
    })
    assert response.status_code == 409
    app.state.copilot.verify.assert_not_called()
    response = client.patch(f"/credentials/{key_id}", headers=headers(), json={
        "approved": True, "upstreams": ["unapproved-provider"],
    })
    assert response.status_code == 422


@pytest.mark.parametrize("manual,partial", [(False, False), (True, False), (False, True)])
def test_copilot_quota_fallback_only_for_automatic_routing_before_output(
    client, monkeypatch, manual, partial,
):
    key_id, snapshot = free_copilot(client, monkeypatch)
    add_key(client, label="OpenRouter fallback", priority=2)
    calls = []

    async def copilot_stream(_token, _messages):
        yield {"type": "eligibility", "snapshot": snapshot}
        if partial:
            yield {"type": "delta", "text": "Partial"}
        raise ProviderError(Failure.EXHAUSTED, "copilot_quota_exhausted")

    async def openrouter_stream(*_args):
        calls.append("openrouter")
        yield {"type": "delta", "text": "Fallback"}

    app.state.copilot.stream = copilot_stream
    app.state.providers.stream = openrouter_stream
    response = client.post("/chat", headers=headers(), json={
        "prompt": "Hi", "request_id": "fallback-copilot",
        "credential_id": key_id if manual else None,
    })
    if manual or partial:
        assert calls == [] and "event: done" not in response.text
    else:
        assert calls == ["openrouter"] and "event: fallback" in response.text
        assert "event: done" in response.text


@pytest.mark.parametrize("provider", ["openai", "anthropic", "copilot"])
def test_new_connections_cannot_bypass_free_only_policy(client, monkeypatch, provider):
    if provider == "copilot":
        oauth_setup(monkeypatch)
        result = client.post("/connections/copilot/complete", headers=headers(),
                             json=oauth_attempt(client)).json()
    else:
        response = client.post("/credentials", headers=headers(), json={
            "provider": provider, "label": "New provider", "api_key": "test-private-api-key",
            "approved": True,
        })
        assert response.status_code == 201
        result = response.json()
        assert result["approved"] is True
        assert client.post("/credentials", headers=headers(), json={
            "provider": provider, "label": "Duplicate", "api_key": "test-private-api-key",
        }).status_code == 409
    client.patch(f"/credentials/{result['id']}", headers=headers(), json={"approved": True})
    app.state.providers.endpoints.reset_mock()
    response = client.post("/chat", headers=headers(), json={
        "prompt": "Must not reach inference", "request_id": "new-provider-blocked",
    })
    assert response.status_code == 409
    app.state.providers.endpoints.assert_not_called()
    assert client.get("/conversations", headers=headers()).json() == []


def test_unapproved_key_cannot_create_chat(client):
    add_key(client, approved=False)
    response = client.post(
        "/chat", headers=headers(), json={"prompt": "Hello", "request_id": "request-0001"}
    )
    assert response.status_code == 409
    assert client.get("/conversations", headers=headers()).json() == []


def test_chat_approved_filter_compiles_for_sql_server(client):
    add_key(client, approved=False)
    queries = []

    def capture_query(state):
        if state.is_select and state.bind_arguments.get("mapper") is not None:
            if state.bind_arguments["mapper"].class_ is Credential:
                queries.append(str(state.statement.compile(
                    dialect=mssql.dialect(), compile_kwargs={"literal_binds": True},
                )))

    sqlalchemy_event.listen(Session, "do_orm_execute", capture_query)
    try:
        response = client.post(
            "/chat", headers=headers(), json={"prompt": "Hello", "request_id": "sql-filter-test"},
        )
    finally:
        sqlalchemy_event.remove(Session, "do_orm_execute", capture_query)
    assert response.status_code == 409
    assert any("credentials.approved = 1" in query for query in queries)


def test_stream_persists_provenance_and_rejects_duplicate_request(client):
    add_key(client)

    async def stream(*_args):
        yield {"type": "delta", "text": "Actual test output"}
        yield {"type": "usage", "usage": {"total_tokens": 8}}

    app.state.providers.stream = stream
    payload = {"prompt": "Hello", "request_id": "request-0002"}
    response = client.post("/chat", headers=headers(), json=payload)
    assert response.status_code == 200
    assert "event: done" in response.text
    conversation_id = client.get("/conversations", headers=headers()).json()[0]["id"]
    detail = client.get(f"/conversations/{conversation_id}", headers=headers()).json()
    assert detail["messages"][-1]["provider"] == "openrouter"
    assert detail["messages"][-1]["content"] == "Actual test output"
    assert (
        client.get(f"/conversations/{conversation_id}", headers=headers(OWNER_B)).status_code
        == 404
    )
    assert (
        client.delete(f"/conversations/{conversation_id}", headers=headers(OWNER_B)).status_code
        == 404
    )
    assert client.post("/chat", headers=headers(), json=payload).status_code == 409
    activity = client.get("/activity", headers=headers()).json()
    assert activity[0]["upstreams"] == ["approved/bf16"]
    assert activity[0]["usage"]["total_tokens"] == 8
    assert client.delete(f"/conversations/{conversation_id}", headers=headers()).status_code == 204
    assert client.get("/activity", headers=headers()).json() == []


def test_no_provider_splice_after_partial_stream(client):
    add_key(client)
    add_key(client, label="Fallback", priority=2)
    calls = []

    async def stream(*args):
        calls.append(args)
        yield {"type": "delta", "text": "Partial output"}
        raise ProviderError(Failure.TRANSIENT, "provider_unavailable")

    app.state.providers.stream = stream
    response = client.post(
        "/chat", headers=headers(), json={"prompt": "Hello", "request_id": "request-0003"}
    )
    assert "event: error" in response.text
    assert "event: fallback" not in response.text
    assert len(calls) == 1


def test_fallback_before_output_only_to_approved_provider(client):
    add_key(client)
    add_key(client, label="Fallback", priority=2)
    calls = []

    async def stream(*args):
        calls.append(args)
        if len(calls) == 1:
            raise ProviderError(Failure.TRANSIENT, "provider_unavailable")
        yield {"type": "delta", "text": "Recovered"}

    app.state.providers.stream = stream
    response = client.post(
        "/chat", headers=headers(), json={"prompt": "Hello", "request_id": "request-0004"}
    )
    assert "event: fallback" in response.text
    assert "event: done" in response.text
    assert len(calls) == 2


def test_quota_exhaustion_does_not_rotate_keys_in_same_account(client):
    add_key(client)
    add_key(client, label="Same account", priority=2)
    calls = []

    async def stream(*args):
        calls.append(args)
        raise ProviderError(Failure.EXHAUSTED, "rate_limited", 60)
        yield

    app.state.providers.stream = stream
    response = client.post(
        "/chat",
        headers=headers(),
        json={
            "prompt": "Hello",
            "request_id": "request-quota",
        },
    )
    assert "event: done" not in response.text
    assert "event: error" in response.text
    assert len(calls) == 1
    assert (
        client.post(
            "/chat",
            headers=headers(),
            json={
                "prompt": "Again",
                "request_id": "request-quota-2",
            },
        ).status_code
        == 409
    )


def test_consent_revocation_does_not_depend_on_provider_catalog(client):
    key = add_key(client)
    app.state.providers.endpoints = AsyncMock(
        side_effect=ProviderError(
            Failure.TRANSIENT,
            "endpoints_unavailable",
        )
    )
    response = client.patch(
        f"/credentials/{key['id']}",
        headers=headers(),
        json={
            "approved": False,
            "priority": 0,
            "upstreams": key["upstreams"],
        },
    )
    assert response.status_code == 200
    assert response.json()["approved"] is False


@pytest.mark.parametrize(
    "failure,code",
    [
        (Failure.REFUSAL, "policy_refusal"),
        (Failure.AUTH, "invalid_key"),
    ],
)
def test_refusal_and_auth_errors_never_fallback(client, failure, code):
    add_key(client)
    add_key(client, label="Fallback", priority=2)
    calls = []

    async def stream(*args):
        calls.append(args)
        raise ProviderError(failure, code)
        yield

    app.state.providers.stream = stream
    response = client.post(
        "/chat",
        headers=headers(),
        json={
            "prompt": "Hello",
            "request_id": "request-no-fallback",
        },
    )
    assert "event: fallback" not in response.text
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_cancel_persists_partial_closes_stream_and_releases_lease(client):
    key = add_key(client)
    owner = OWNER_A
    conversation_id = "cancel-conversation"
    run_id = f"{owner}:cancel-request"
    with Session(app.state.engine) as database:
        database.add(Conversation(id=conversation_id, owner_id=owner, title="Cancel test"))
        database.flush()
        database.add(Run(id=run_id, owner_id=owner, conversation_id=conversation_id))
        database.commit()
    started, closed = asyncio.Event(), asyncio.Event()

    async def stream(*_args):
        try:
            yield {"type": "delta", "text": "Partial"}
            await asyncio.Event().wait()
        finally:
            closed.set()

    app.state.providers.stream = stream
    lease = await app.state.limits.acquire(owner)
    request = SimpleNamespace(app=app, is_disconnected=AsyncMock(return_value=False))
    candidate = Candidate(
        key["id"],
        owner,
        "openrouter",
        "vendor/model:free",
        True,
        datetime.now(UTC) + timedelta(seconds=60),
        ("approved/bf16",),
    )

    async def consume():
        async for event in execute_stream(
            request,
            owner,
            run_id,
            conversation_id,
            [{"role": "user", "content": "Hello"}],
            [candidate],
            lease,
            session_id=owner,
        ):
            if "event: delta" in event:
                started.set()

    task = asyncio.create_task(consume())
    await asyncio.wait_for(started.wait(), 2)
    await cancel(request, owner)
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()
    assert owner not in app.state.active
    with Session(app.state.engine) as database:
        assert database.get(Run, run_id).status == "cancelled"
        message = database.scalar(select(Message))
        assert message.content == "Partial"
        assert message.status == "cancelled"
    next_lease = await app.state.limits.acquire(owner)
    await app.state.limits.release(owner, next_lease)
