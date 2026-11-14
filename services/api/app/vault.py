import hashlib
import re
from functools import lru_cache
from urllib.parse import urlsplit

from azure.core.exceptions import AzureError, ResourceNotFoundError
from azure.identity import AzureCliCredential, ManagedIdentityCredential
from azure.keyvault.secrets import SecretClient


class SecretStoreError(RuntimeError):
    pass


class SecretMissingError(SecretStoreError):
    pass


def validate_vault_url(url: str) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not re.fullmatch(r"[a-zA-Z0-9-]+\.vault\.azure\.net", parsed.netloc)
        or parsed.path not in {"", "/"}
        or parsed.query or parsed.fragment
    ):
        raise ValueError("Invalid Azure Key Vault URL")
    return url.rstrip("/")


@lru_cache(maxsize=8)
def vault_client(url: str, environment: str, tenant_id: str = "", client_id: str = ""):
    credential = (
        ManagedIdentityCredential(client_id=client_id or None)
        if environment == "production"
        else AzureCliCredential(tenant_id=tenant_id or None)
    )
    return SecretClient(
        validate_vault_url(url), credential,
        logging_enable=False, connection_timeout=10, read_timeout=15, retry_total=2,
    )


def read_secret(client: SecretClient, name: str, version: str | None = None) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9-]{1,127}", name):
        raise SecretStoreError("Invalid Key Vault reference")
    try:
        value = client.get_secret(name, version=version).value
    except ResourceNotFoundError:
        raise SecretMissingError("Key Vault secret is missing") from None
    except AzureError:
        raise SecretStoreError(
            "Key Vault secret read failed; check access and availability"
        ) from None
    if not value:
        raise SecretStoreError("Required Key Vault secret is empty")
    return value


def connection_secret_name(owner: str, record: str) -> str:
    digest = hashlib.sha256(f"{owner}:{record}".encode()).hexdigest()
    return f"wagl-connection-{digest}"


def write_secret(client: SecretClient, name: str, value: str) -> str:
    try:
        secret = client.set_secret(name, value, logging_enable=False)
    except AzureError:
        raise SecretStoreError("Key Vault secret write failed; connection was not saved") from None
    if not secret.properties.version:
        raise SecretStoreError("Key Vault did not return a secret version")
    return f"kv://{name}/{secret.properties.version}"


def read_reference(client: SecretClient, reference: str, expected_name: str | None = None) -> str:
    match = re.fullmatch(r"kv://([a-zA-Z0-9-]{1,127})(?:/([a-fA-F0-9]{32}))?", reference)
    if not match or (expected_name and (match[1] != expected_name or not match[2])):
        raise SecretStoreError("Invalid or mismatched Key Vault reference")
    return read_secret(client, match[1], match[2])


def delete_reference(client: SecretClient, reference: str, owner: str, record: str):
    name = connection_secret_name(owner, record)
    if not re.fullmatch(rf"kv://{name}/[a-fA-F0-9]{{32}}", reference):
        raise SecretStoreError("Invalid or mismatched Key Vault reference")
    try:
        client.begin_delete_secret(name).result()
    except ResourceNotFoundError:
        return
    except AzureError:
        raise SecretStoreError(
            "Key Vault secret deletion failed; retry connection removal"
        ) from None
