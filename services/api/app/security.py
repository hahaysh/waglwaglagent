import base64
import hashlib
import os

import jwt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import HTTPException, Request

from app.config import get_settings


def authenticated_owner(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Authentication required")
    try:
        claims = jwt.decode(
            authorization[7:],
            get_settings().internal_secret,
            algorithms=["HS256"],
            audience="wagl-api",
            issuer="wagl-web",
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
        )
        owner = claims["sub"]
        if not isinstance(owner, str) or not owner.startswith("github:") or len(owner) > 100:
            raise ValueError("Invalid subject")
        return owner
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(401, "Invalid authentication") from None


def encrypt_key(raw_key: str, owner: str, credential_id: str) -> str:
    nonce = os.urandom(12)
    cipher = AESGCM(base64.b64decode(get_settings().encryption_key))
    ciphertext = cipher.encrypt(nonce, raw_key.encode(), f"{owner}:{credential_id}".encode())
    return base64.b64encode(nonce + ciphertext).decode()


def decrypt_key(ciphertext: str, owner: str, credential_id: str) -> str:
    payload = base64.b64decode(ciphertext)
    cipher = AESGCM(base64.b64decode(get_settings().encryption_key))
    return cipher.decrypt(payload[:12], payload[12:], f"{owner}:{credential_id}".encode()).decode()


def key_fingerprint(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()
