"""Move existing local configuration to Azure without printing secret values."""

import argparse
import hmac
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit

from alembic import command
from alembic.config import Config
from azure.appconfiguration import AzureAppConfigurationClient, ConfigurationSetting
from azure.core.exceptions import AzureError, ResourceNotFoundError
from azure.identity import AzureCliCredential
from dotenv import dotenv_values
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.encryption import seal, unseal
from app.models import Credential, make_engine
from app.security import decrypt_key
from app.vault import (
    SecretStoreError,
    connection_secret_name,
    read_reference,
    read_secret,
    vault_client,
    write_secret,
)

SECRET_NAMES = {
    "WAGL_INTERNAL_SECRET": "waglwaglagent-internal-secret",
    "WAGL_ENCRYPTION_KEY": "waglwaglagent-encryption-key",
    "WAGL_POSTGRES_PASSWORD": "waglwaglagent-postgres-password",
    "WAGL_COPILOT_CLIENT_ID": "waglwaglagent-copilot-id",
    "WAGL_COPILOT_CLIENT_SECRET": "waglwaglagent-copilot-secret",
    "AUTH_SECRET": "waglwaglagent-auth-secret",
    "AUTH_GITHUB_ID": "waglwaglagent-github-id",
    "AUTH_GITHUB_SECRET": "waglwaglagent-github-secret",
}
ORDINARY_KEYS = {
    "WAGL_ENVIRONMENT", "WAGL_DATABASE_URL", "WAGL_REDIS_URL", "WAGL_WEB_PORT",
    "WAGL_PUBLIC_URL", "LITELLM_TELEMETRY", "AUTH_TRUST_HOST", "AUTH_URL", "WAGL_API_URL",
    "NEXT_TELEMETRY_DISABLED", "WAGL_GEMINI_REVIEWS",
}


def verified_secret(client, name: str, value: str) -> str:
    try:
        existing = client.get_secret(name)
    except ResourceNotFoundError:
        reference = write_secret(client, name, value)
    else:
        if not hmac.compare_digest(existing.value or "", value):
            raise SecretStoreError(
                f"Existing vault secret differs: {name}; refusing to replace it"
            )
        reference = f"kv://{name}/{existing.properties.version}"
    if not hmac.compare_digest(read_reference(client, reference), value):
        raise SecretStoreError("Key Vault read-back verification failed")
    return reference


def publish_settings(configuration, vault, values: dict, label: str, vault_url: str):
    for key, value in values.items():
        if value is None:
            value = ""
        content_type = None
        if value and (key in SECRET_NAMES or (
            key in {"WAGL_DATABASE_URL", "WAGL_REDIS_URL"} and urlsplit(value).password
        )):
            name = SECRET_NAMES.get(
                key, "waglwaglagent-" + key.removeprefix("WAGL_").lower().replace("_", "-"),
            )
            reference = verified_secret(vault, name, value)
            uri = vault_url.rstrip("/") + "/secrets/" + reference.removeprefix("kv://")
            value = json.dumps({"uri": uri})
            content_type = "application/vnd.microsoft.appconfig.keyvaultref+json;charset=utf-8"
        elif key not in ORDINARY_KEYS and key not in SECRET_NAMES and key != "WAGL_KEY_VAULT_URL":
            raise SecretStoreError(f"Unclassified environment setting: {key}")
        setting = ConfigurationSetting(
            key=key, label=label, value=value, content_type=content_type,
        )
        configuration.set_configuration_setting(setting)
        actual = configuration.get_configuration_setting(key, label=label)
        if actual.value != value or actual.content_type != content_type:
            raise SecretStoreError("App Configuration read-back verification failed")


def atomic_write(path: Path, text: str):
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False,
    ) as stream:
        temporary = Path(stream.name)
        stream.write(text)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def protect_backup(path: Path):
    target = path.with_suffix(path.suffix + ".aesgcm")
    import base64

    original = path.read_bytes()
    if target.exists():
        restored = base64.b64decode(unseal(target.read_text(), f"backup:{path.name}"))
        if restored != original:
            raise SecretStoreError("Encrypted backup already exists with different contents")
    else:
        encoded = base64.b64encode(original).decode()
        encrypted = seal(encoded, f"backup:{path.name}")
        atomic_write(target, encrypted)
        if base64.b64decode(unseal(target.read_text(), f"backup:{path.name}")) != original:
            raise SecretStoreError("Encrypted backup verification failed")
    path.unlink()


def migrate(args):
    root = Path.cwd()
    api_path, web_path = root / ".env", root / "apps" / "web" / ".env.local"
    api_values, web_values = dict(dotenv_values(api_path)), dict(dotenv_values(web_path))
    if api_values.get("WAGL_APP_CONFIG_ENDPOINT") or web_values.get("WAGL_APP_CONFIG_ENDPOINT"):
        raise SecretStoreError("Configuration is already migrated; use normal runtime validation")
    if not hmac.compare_digest(
        api_values.get("WAGL_INTERNAL_SECRET") or "",
        web_values.get("WAGL_INTERNAL_SECRET") or "",
    ):
        raise SecretStoreError("API and web internal secrets differ")
    settings = get_settings()
    if not settings.database_url.startswith("sqlite:///"):
        raise SecretStoreError("This offline migration tool requires the local SQLite database")
    database_path = Path(settings.database_url.removeprefix("sqlite:///")).resolve()
    if not database_path.is_file():
        raise SecretStoreError("Existing local database not found")
    vault = vault_client(args.vault_url, "local", args.tenant_id)
    credential = AzureCliCredential(tenant_id=args.tenant_id)
    with AzureAppConfigurationClient(
        args.configuration_endpoint, credential, logging_enable=False,
    ) as configuration:
        for values, label in ((api_values, "local-api"), (web_values, "local-web")):
            publish_settings(
                configuration, vault, values | {"WAGL_KEY_VAULT_URL": args.vault_url},
                label, args.vault_url,
            )
    # Keep recoverable backups encrypted under the original key before rewriting data.
    backup = root / ".local" / "wagl-before-keyvault.db"
    if not backup.exists() and not backup.with_suffix(".db.aesgcm").exists():
        with closing(sqlite3.connect(database_path)) as source:
            with closing(sqlite3.connect(backup)) as destination:
                source.backup(destination)
    if backup.exists():
        protect_backup(backup)
    for old_backup in sorted((root / ".local").glob("wagl-before-*.db")):
        protect_backup(old_backup)
    environment_backup = root / ".local" / "environment-before-keyvault.aesgcm"
    if not environment_backup.exists():
        source_text = json.dumps({"api": api_values, "web": web_values})
        encrypted = seal(source_text, "backup:environment")
        atomic_write(environment_backup, encrypted)
        if unseal(environment_backup.read_text(), "backup:environment") != source_text:
            raise SecretStoreError("Encrypted environment backup verification failed")
    command.upgrade(Config(str(root / "services" / "api" / "alembic.ini")), "head")
    engine = make_engine(settings.database_url)
    migrated = 0
    try:
        with Session(engine) as database:
            for record in database.scalars(select(Credential)):
                suffix = f"{record.id}:oauth_v1" if record.auth_type == "oauth" else record.id
                name = connection_secret_name(record.owner_id, suffix)
                if record.encrypted_key.startswith("kv://"):
                    read_reference(vault, record.encrypted_key, name)
                    continue
                raw = decrypt_key(record.encrypted_key, record.owner_id, suffix)
                record.encrypted_key = verified_secret(vault, name, raw)
                migrated += 1
            database.commit()
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA secure_delete=ON")
            connection.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.commit()
            connection.exec_driver_sql("VACUUM")
    finally:
        engine.dispose()
    for path, label in ((api_path, "local-api"), (web_path, "local-web")):
        atomic_write(path, "\n".join((
            "WAGL_ENVIRONMENT=local",
            f"WAGL_APP_CONFIG_ENDPOINT={args.configuration_endpoint}",
            f"WAGL_APP_CONFIG_LABEL={label}",
            f"WAGL_AZURE_TENANT_ID={args.tenant_id}",
            "",
        )))
    get_settings.cache_clear()
    resolved = get_settings()
    if not hmac.compare_digest(resolved.encryption_key, settings.encryption_key):
        raise SecretStoreError("Encryption key changed during migration")
    if not hmac.compare_digest(
        read_secret(vault, SECRET_NAMES["AUTH_SECRET"]), web_values["AUTH_SECRET"],
    ):
        raise SecretStoreError("Web authentication secret changed during migration")
    print(f"Migration verified: {migrated} connection(s); no secret values were printed.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault-url", required=True)
    parser.add_argument("--configuration-endpoint", required=True)
    parser.add_argument("--tenant-id", required=True)
    args = parser.parse_args()
    try:
        migrate(args)
    except SecretStoreError as error:
        raise SystemExit(f"Migration stopped: {error}") from None
    except (AzureError, ValueError, OSError) as error:
        raise SystemExit(f"Migration stopped ({type(error).__name__}); no values logged.") from None


if __name__ == "__main__":
    main()
