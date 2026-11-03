import asyncio
import base64
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.main import app, cancel, execute_stream
from app.models import Conversation, Credential, Message, Run
from app.providers import ProviderError
from app.routing import Candidate, Failure


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WAGL_INTERNAL_SECRET", "test-internal-secret-" * 3)
    monkeypatch.setenv("WAGL_ENCRYPTION_KEY", base64.b64encode(bytes(range(32))).decode())
    monkeypatch.setenv("WAGL_DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("WAGL_ENVIRONMENT", "local")
    monkeypatch.setenv("WAGL_REDIS_URL", "")
    get_settings.cache_clear()
    with TestClient(app) as test_client:
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
        yield test_client
    get_settings.cache_clear()


def headers(owner="github:1"):
    token = jwt.encode(
        {
            "sub": owner,
            "iss": "wagl-web",
            "aud": "wagl-api",
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(minutes=1),
        },
        get_settings().internal_secret,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def add_key(client, **overrides):
    payload = {
        "provider": "openrouter",
        "label": "Personal key",
        "api_key": "private-test-key",
        "model": "vendor/model:free",
        "upstreams": ["approved/bf16"],
        "approved": True,
    } | overrides
    response = client.post("/credentials", json=payload, headers=headers())
    assert response.status_code == 201, response.text
    return response.json()


def test_authentication_and_key_isolation(client):
    assert client.get("/credentials").status_code == 401
    key = add_key(client)
    assert "private-test-key" not in str(key)
    assert "encrypted_key" not in key
    assert client.get("/credentials", headers=headers("github:2")).json() == []
    for method in ("delete", "patch"):
        response = client.request(
            method,
            f"/credentials/{key['id']}",
            headers=headers("github:2"),
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


def test_unapproved_key_cannot_create_chat(client):
    add_key(client, approved=False)
    response = client.post(
        "/chat", headers=headers(), json={"prompt": "Hello", "request_id": "request-0001"}
    )
    assert response.status_code == 409
    assert client.get("/conversations", headers=headers()).json() == []


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
        client.get(f"/conversations/{conversation_id}", headers=headers("github:2")).status_code
        == 404
    )
    assert (
        client.delete(f"/conversations/{conversation_id}", headers=headers("github:2")).status_code
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
    owner = "github:1"
    conversation_id = "cancel-conversation"
    run_id = "github:1:cancel-request"
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
