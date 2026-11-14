import base64
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Base, Credential, Message
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
