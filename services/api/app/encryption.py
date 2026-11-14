import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings

PREFIX = "enc:v1:"


def seal(value: str, context: str) -> str:
    nonce = os.urandom(12)
    cipher = AESGCM(base64.b64decode(get_settings().encryption_key, validate=True))
    payload = cipher.encrypt(nonce, value.encode(), context.encode())
    return PREFIX + base64.b64encode(nonce + payload).decode()


def unseal(value: str, context: str) -> str:
    if not value.startswith(PREFIX):
        raise ValueError("Unencrypted database content; run database migrations before starting")
    payload = base64.b64decode(value[len(PREFIX):], validate=True)
    cipher = AESGCM(base64.b64decode(get_settings().encryption_key, validate=True))
    return cipher.decrypt(payload[:12], payload[12:], context.encode()).decode()
