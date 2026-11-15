import base64
import hashlib
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import HTTPException, Request

from app.config import get_settings
from app.vault import (
    SecretStoreError,
    connection_secret_name,
    delete_reference,
    read_reference,
    vault_client,
    write_secret,
)


def secret_client():
    settings = get_settings()
    if not settings.key_vault_url:
        raise SecretStoreError("Azure Key Vault is not configured")
    return vault_client(
        settings.key_vault_url, settings.environment, settings.azure_tenant_id,
        settings.managed_identity_client_id,
    )


def authenticated_owner(request: Request) -> str:
    from sqlalchemy.orm import Session

    from app.accounts import canonical_uuid, decode_assertion, valid_session

    if get_settings().maintenance_enabled:
        raise HTTPException(503, "maintenance")
    claims = decode_assertion(request, "wagl-api")
    try:
        subject = claims["sub"]
        if not isinstance(subject, str) or not subject.startswith("user:"):
            raise ValueError("Invalid subject")
        owner = canonical_uuid(subject[5:])
    except ValueError:
        raise HTTPException(401, "Invalid authentication") from None
    with Session(request.app.state.engine) as database:
        valid_session(database, owner, claims["sid"])
    request.state.session_id = claims["sid"]
    return owner


def encrypt_key(raw_key: str, owner: str, credential_id: str) -> str:
    if get_settings().key_vault_url:
        # PKCE is short-lived and stays encrypted in the database, not in vault history.
        if not credential_id.endswith(":pkce"):
            return write_secret(
                secret_client(), connection_secret_name(owner, credential_id), raw_key,
            )
    nonce = os.urandom(12)
    cipher = AESGCM(base64.b64decode(get_settings().encryption_key))
    ciphertext = cipher.encrypt(nonce, raw_key.encode(), f"{owner}:{credential_id}".encode())
    return base64.b64encode(nonce + ciphertext).decode()


def decrypt_key(ciphertext: str, owner: str, credential_id: str) -> str:
    if ciphertext.startswith("kv://"):
        return read_reference(
            secret_client(), ciphertext, connection_secret_name(owner, credential_id),
        )
    payload = base64.b64decode(ciphertext)
    cipher = AESGCM(base64.b64decode(get_settings().encryption_key))
    return cipher.decrypt(payload[:12], payload[12:], f"{owner}:{credential_id}".encode()).decode()


def delete_key(reference: str, owner: str, credential_id: str):
    if reference.startswith("kv://"):
        delete_reference(secret_client(), reference, owner, credential_id)


def key_fingerprint(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def encrypt_oauth(tokens: dict, owner: str, credential_id: str) -> str:
    return encrypt_key(json.dumps(tokens), owner, f"{credential_id}:oauth_v1")


def decrypt_oauth(ciphertext: str, owner: str, credential_id: str) -> dict:
    return json.loads(decrypt_key(ciphertext, owner, f"{credential_id}:oauth_v1"))
