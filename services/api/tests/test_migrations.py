import base64
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from app.config import get_settings
from app.models import Base


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
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
        command.downgrade(config, "base")
        assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    finally:
        engine.dispose()
        get_settings.cache_clear()
