import base64
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.exceptions import InvalidTag
from fastapi import HTTPException
from starlette.requests import Request

from app.config import get_settings
from app.security import authenticated_owner, decrypt_key, encrypt_key


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    monkeypatch.setenv("WAGL_INTERNAL_SECRET", "test-internal-secret-" * 3)
    monkeypatch.setenv("WAGL_ENCRYPTION_KEY", base64.b64encode(bytes(range(32))).decode())
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def token_request(**overrides):
    claims = {
        "sub": "github:1",
        "aud": "wagl-api",
        "iss": "wagl-web",
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(seconds=60),
    } | overrides
    token = jwt.encode(claims, get_settings().internal_secret, algorithm="HS256")
    return Request({"type": "http", "headers": [(b"authorization", f"Bearer {token}".encode())]})


def test_authenticated_identity_is_signed_and_scoped():
    assert authenticated_owner(token_request()) == "github:1"
    for overrides in [{"aud": "other"}, {"iss": "other"}, {"exp": 0}, {"sub": "alice"}]:
        with pytest.raises(HTTPException) as error:
            authenticated_owner(token_request(**overrides))
        assert error.value.status_code == 401


def test_encryption_is_bound_to_user_and_record():
    ciphertext = encrypt_key("my-private-key", "github:1", "key-1")
    assert "my-private-key" not in ciphertext
    assert decrypt_key(ciphertext, "github:1", "key-1") == "my-private-key"
    assert encrypt_key("my-private-key", "github:1", "key-1") != ciphertext
    with pytest.raises(InvalidTag):
        decrypt_key(ciphertext, "github:2", "key-1")
    with pytest.raises(InvalidTag):
        decrypt_key(ciphertext, "github:1", "key-2")


def test_production_requires_shared_infrastructure(monkeypatch):
    monkeypatch.setenv("WAGL_ENVIRONMENT", "production")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="PostgreSQL and Redis"):
        get_settings()
