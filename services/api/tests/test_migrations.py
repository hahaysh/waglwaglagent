import base64
import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Base, Conversation, Credential, Message
from app.security import decrypt_key, encrypt_key


def test_initial_migration_matches_models_and_rolls_back(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setenv("WAGL_DATABASE_URL", url)
    monkeypatch.setenv("WAGL_ENVIRONMENT", "local")
    monkeypatch.setenv("WAGL_INTERNAL_SECRET", "migration-test-secret-" * 3)
    monkeypatch.setenv("WAGL_ENCRYPTION_KEY", base64.b64encode(bytes(range(32))).decode())
    get_settings.cache_clear()
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    engine = create_engine(url)
    try:
        command.upgrade(config, "0001")
        cipher = encrypt_key("legacy-private-api-key", "github:legacy", "legacy-key")
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO credentials (id,owner_id,provider,label,encrypted_key,fingerprint,"
                "status,model,upstreams,approved,priority,consent_version,quota_group,"
                "quota_snapshot,created_at) VALUES "
                "('legacy-key','github:legacy','openrouter','Legacy',:cipher,'fingerprint',"
                "'valid','vendor/model:free','[]',0,0,'consent','account','{}','2026-01-01')"
            ), {"cipher": cipher})
            connection.execute(text(
                "INSERT INTO conversations (id,owner_id,title,created_at) VALUES "
                "('old-chat','github:legacy','Old chat','2026-01-01')"
            ))
            connection.execute(text(
                "INSERT INTO messages (id,conversation_id,role,content,status,created_at) VALUES "
                "('old-message','old-chat','user','Keep my message','complete','2026-01-01')"
            ))
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
        with Session(engine) as database:
            record = database.get(Credential, "legacy-key")
            assert record.encrypted_key == cipher
            original = decrypt_key(record.encrypted_key, record.owner_id, record.id)
            assert original == "legacy-private-api-key"
            assert record.auth_type == "api_key"
            message = database.get(Message, "old-message")
            assert message.attachments == []
            assert message.content == "Keep my message"
        with pytest.raises(RuntimeError, match="cannot be downgraded"):
            command.downgrade(config, "base")
        assert "messages" in inspect(engine).get_table_names()
    finally:
        engine.dispose()
        get_settings.cache_clear()


@pytest.mark.skipif(
    not os.getenv("WAGL_SQL_TEST_HOST"), reason="Requires the approved Azure SQL DB"
)
def test_live_sql_migrations_encryption_nullable_accounts_and_cascade(monkeypatch):
    from azure.identity import AzureCliCredential

    credential = AzureCliCredential(tenant_id=os.environ["WAGL_SQL_TEST_TENANT"])
    url = (
        f"mssql+mssqlpython://@{os.environ['WAGL_SQL_TEST_HOST']}/waglwaglagent-db?"
        "encrypt=yes&trustservercertificate=no"
    )
    monkeypatch.setenv("WAGL_DATABASE_URL", url)
    monkeypatch.setenv("WAGL_ENVIRONMENT", "local")
    monkeypatch.setenv("WAGL_INTERNAL_SECRET", "migration-test-secret-" * 3)
    monkeypatch.setenv("WAGL_ENCRYPTION_KEY", base64.b64encode(bytes(range(32))).decode())
    get_settings.cache_clear()
    engine = create_engine(
        url, connect_args={"token_provider": credential}, deprecate_large_types=True,
    )
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        with engine.connect() as connection:
            with Session(connection) as database:
                owner = "github:sql-migration-test"
                for identity in ("sql-key-one", "sql-key-two"):
                    database.add(Credential(
                        id=identity, owner_id=owner, provider="openrouter", label="SQL test",
                        encrypted_key="kv://test", auth_type="api_key", provider_subject=None,
                    ))
                database.add(Conversation(id="sql-chat", owner_id=owner, title="SQL test"))
                database.flush()
                database.add(Message(
                    id="sql-message", conversation_id="sql-chat", role="user",
                    content="SQL encrypted " + "x" * 12000,
                    attachments=[{"name": "sql.txt", "content": "x" * 12000}],
                ))
                database.flush()
                database.expire_all()
                message = database.get(Message, "sql-message")
                assert message.content == "SQL encrypted " + "x" * 12000
                assert message.attachments[0]["name"] == "sql.txt"
                stored = connection.execute(text(
                    "SELECT content,attachments FROM messages WHERE id='sql-message'"
                )).one()
                assert "SQL encrypted" not in stored.content
                assert "sql.txt" not in stored.attachments
                for identity in ("sql-oauth-one", "sql-oauth-two"):
                    database.add(Credential(
                        id=identity, owner_id=owner, provider="copilot", label="SQL test",
                        encrypted_key="kv://test", provider_subject="same-provider-account",
                    ))
                with pytest.raises(IntegrityError):
                    database.flush()
            with connection.begin() as transaction:
                connection.execute(Conversation.__table__.insert().values(
                    id="sql-cascade-chat", owner_id="github:sql-test", title="SQL cascade"
                ))
                connection.execute(Message.__table__.insert().values(
                    id="sql-cascade-message", conversation_id="sql-cascade-chat",
                    role="user", content="cascade", attachments=[],
                ))
                connection.execute(text("DELETE FROM conversations WHERE id='sql-cascade-chat'"))
                assert connection.execute(text(
                    "SELECT COUNT(*) FROM messages WHERE id='sql-cascade-message'"
                )).scalar_one() == 0
                transaction.rollback()
        saved_id = uuid.uuid4().hex
        with Session(engine) as database:
            database.add(Conversation(
                id=saved_id, owner_id="github:sql-migration-test", title="Durable SQL test"
            ))
            database.commit()
        engine.dispose()
        try:
            with Session(engine) as database:
                saved = database.get(Conversation, saved_id)
                assert saved.title == "Durable SQL test"
        finally:
            with Session(engine) as database:
                saved = database.get(Conversation, saved_id)
                if saved is not None:
                    assert saved.owner_id == "github:sql-migration-test"
                    database.delete(saved)
                    database.commit()
    finally:
        engine.dispose()
        credential.close()
        get_settings.cache_clear()
