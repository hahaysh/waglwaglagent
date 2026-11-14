import base64
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.central_config import REFERENCE_TYPE, load_configuration
from app.config import get_settings
from app.encryption import unseal
from app.migrate_secrets import protect_backup, publish_settings, verified_secret
from app.vault import SecretStoreError


def setting(key, value, content_type=None):
    return SimpleNamespace(key=key, value=value, content_type=content_type)


def test_native_references_resolve_only_with_matching_vault(monkeypatch):
    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    items = [
        setting("WAGL_KEY_VAULT_URL", "https://expected.vault.azure.net/"),
        setting("WAGL_INTERNAL_SECRET", json.dumps({
            "uri": "https://expected.vault.azure.net/secrets/internal",
        }), REFERENCE_TYPE + ";charset=utf-8"),
    ]
    client.list_configuration_settings.return_value = items
    monkeypatch.setattr("app.central_config.AzureAppConfigurationClient", lambda *a, **k: client)
    result = load_configuration("https://example.azconfig.io", "local-api", "local")
    assert result["WAGL_INTERNAL_SECRET"] == "kv://internal"
    items[1].value = json.dumps({"uri": "https://other.vault.azure.net/secrets/internal"})
    with pytest.raises(SecretStoreError, match="unexpected Key Vault"):
        load_configuration("https://example.azconfig.io", "local-api", "local")


def test_migration_writes_native_references_not_secret_values():
    configuration, vault = Mock(), Mock()
    vault.get_secret.return_value = SimpleNamespace(
        value="private-token", properties=SimpleNamespace(version="a" * 32),
    )
    saved = {}
    configuration.set_configuration_setting.side_effect = lambda value: saved.update(
        {value.key: value},
    )
    configuration.get_configuration_setting.side_effect = lambda key, **_: saved[key]
    publish_settings(configuration, vault, {
        "AUTH_SECRET": "private-token", "AUTH_URL": "http://localhost:3000",
    }, "local-web", "https://expected.vault.azure.net/")
    assert "private-token" not in saved["AUTH_SECRET"].value
    assert json.loads(saved["AUTH_SECRET"].value)["uri"].endswith(
        "/secrets/waglwaglagent-auth-secret/" + "a" * 32,
    )
    assert saved["AUTH_URL"].value == "http://localhost:3000"


def test_migration_refuses_to_replace_a_different_existing_master_key():
    vault = Mock()
    vault.get_secret.return_value = SimpleNamespace(value="existing-key")
    with pytest.raises(SecretStoreError, match="refusing to replace"):
        verified_secret(vault, "waglwaglagent-encryption-key", "replacement-key")
    vault.set_secret.assert_not_called()


def test_old_backup_is_removed_only_after_encrypted_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("WAGL_INTERNAL_SECRET", "test-internal-secret-" * 3)
    monkeypatch.setenv("WAGL_ENCRYPTION_KEY", base64.b64encode(bytes(range(32))).decode())
    get_settings.cache_clear()
    backup = tmp_path / "legacy.db"
    original = b"private-oauth-token-and-prompt"
    backup.write_bytes(original)
    try:
        protect_backup(backup)
        assert not backup.exists()
        encrypted = (tmp_path / "legacy.db.aesgcm").read_text()
        assert "private-oauth" not in encrypted
        assert base64.b64decode(unseal(encrypted, "backup:legacy.db")) == original
    finally:
        get_settings.cache_clear()
