import base64
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from azure.core.exceptions import ResourceNotFoundError, ServiceRequestError
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import Base, Conversation, Message
from app.security import decrypt_key, encrypt_key
from app.vault import SecretStoreError, connection_secret_name, delete_reference, read_reference


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    monkeypatch.setenv("WAGL_INTERNAL_SECRET", "test-internal-secret-" * 3)
    monkeypatch.setenv("WAGL_ENCRYPTION_KEY", base64.b64encode(bytes(range(32))).decode())
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_vault_credentials_are_version_pinned_and_owner_bound(monkeypatch):
    client = Mock()
    client.set_secret.return_value = SimpleNamespace(
        properties=SimpleNamespace(version="a" * 32),
    )
    client.get_secret.return_value = SimpleNamespace(value="private-connection-token")
    monkeypatch.setattr("app.security.secret_client", lambda: client)
    monkeypatch.setattr("app.security.get_settings", lambda: SimpleNamespace(
        key_vault_url="https://test.vault.azure.net/",
    ))
    reference = encrypt_key("private-connection-token", "github:1", "record")
    assert reference == f"kv://{connection_secret_name('github:1', 'record')}/{'a' * 32}"
    assert decrypt_key(reference, "github:1", "record") == "private-connection-token"
    calls = client.get_secret.call_count
    with pytest.raises(SecretStoreError, match="mismatched"):
        decrypt_key(reference, "github:2", "record")
    assert client.get_secret.call_count == calls


def test_vault_failure_does_not_fall_back_or_expose_upstream_values():
    client = Mock()
    client.get_secret.side_effect = ServiceRequestError("sensitive-upstream-detail")
    with pytest.raises(SecretStoreError) as error:
        read_reference(client, "kv://example")
    assert "sensitive-upstream-detail" not in str(error.value)


def test_secret_deletion_can_be_retried_after_a_database_commit_failure():
    client = Mock()
    client.begin_delete_secret.side_effect = ResourceNotFoundError("already deleted")
    name = connection_secret_name("github:1", "record")
    delete_reference(client, f"kv://{name}/{'a' * 32}", "github:1", "record")
    with pytest.raises(SecretStoreError, match="mismatched"):
        delete_reference(client, f"kv://{name}/{'a' * 32}", "github:2", "record")
    assert client.begin_delete_secret.call_count == 1


def test_settings_resolve_vault_references_and_reject_plaintext(monkeypatch):
    client = Mock()
    values = {"internal": "s" * 48, "encryption": base64.b64encode(bytes(range(32))).decode()}
    client.get_secret.side_effect = lambda name, **_: SimpleNamespace(value=values[name])
    monkeypatch.setattr("app.vault.vault_client", lambda *args: client)
    settings = Settings(
        _env_file=None, key_vault_url="https://test.vault.azure.net/",
        internal_secret="kv://internal", encryption_key="kv://encryption",
    )
    assert settings.internal_secret == values["internal"]
    assert values["internal"] not in repr(settings)
    with pytest.raises(ValueError, match="must use Key Vault"):
        Settings(
            _env_file=None, key_vault_url="https://test.vault.azure.net/",
            internal_secret="s" * 48, encryption_key="kv://encryption",
        )


def test_customer_content_is_encrypted_in_database_and_round_trips():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    attachment = {"name": "private.txt", "mime_type": "text/plain", "data": "cHJpdmF0ZQ=="}
    with Session(engine) as database:
        database.add(Conversation(id="chat", owner_id="github:1", title="Private title"))
        database.add(Message(
            id="message", conversation_id="chat", role="user", content="Private prompt",
            attachments=[attachment],
        ))
        database.commit()
        raw = database.execute(text(
            "SELECT content,attachments FROM messages WHERE id='message'"
        )).one()
        assert "Private prompt" not in raw.content
        assert "private.txt" not in raw.attachments
        assert raw.content.startswith("enc:v1:")
        assert database.get(Message, "message").attachments == [attachment]
        assert database.get(Conversation, "chat").title == "Private title"
    engine.dispose()
