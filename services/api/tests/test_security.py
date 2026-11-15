import base64
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.exceptions import InvalidTag
from fastapi import HTTPException
from starlette.requests import Request

from app.accounts import decode_assertion
from app.config import Settings, get_settings
from app.security import decrypt_key, encrypt_key


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
        "sid": "11111111-1111-4111-8111-111111111111",
        "aud": "wagl-api",
        "iss": "wagl-web",
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(seconds=60),
    } | overrides
    token = jwt.encode(claims, get_settings().internal_secret, algorithm="HS256")
    return Request({"type": "http", "headers": [(b"authorization", f"Bearer {token}".encode())]})


def test_authenticated_identity_is_signed_and_scoped():
    assert decode_assertion(token_request(), "wagl-api")["sub"] == "github:1"
    for overrides in [{"aud": "other"}, {"iss": "other"}, {"exp": 0}, {"sid": "alice"}]:
        with pytest.raises(HTTPException) as error:
            decode_assertion(token_request(**overrides), "wagl-api")
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
    with pytest.raises(ValueError, match="Production requires Azure Key Vault"):
        get_settings()


def test_azure_sql_requires_managed_identity_and_verified_tls():
    url = (
        "mssql+mssqlpython://@example.database.windows.net:1433/db?"
        "authentication=ActiveDirectoryMSI&encrypt=yes&trustservercertificate=no"
    )
    settings = Settings.model_construct(
        environment="production", database_url=url, redis_url="rediss://example",
        internal_secret="s" * 48, encryption_key=base64.b64encode(bytes(range(32))).decode(),
        public_url="https://example.test",
    )
    assert settings.validate_security() is settings
    for invalid in (
        url.replace("ActiveDirectoryMSI", "ActiveDirectoryPassword"),
        url.replace("encrypt=yes", "encrypt=no"),
        url.replace("trustservercertificate=no", "trustservercertificate=yes"),
        url.replace("example.database.windows.net", "untrusted.example"),
        url.replace("://@", "://user:password@"),
    ):
        settings.database_url = invalid
        with pytest.raises(ValueError, match="certificate-verified"):
            settings.validate_security()
