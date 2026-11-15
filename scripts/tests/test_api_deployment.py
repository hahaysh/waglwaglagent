import importlib.util
import json
import sys
import uuid
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from check_api_deployment import validate_api_configuration
from configure_backend import database_url, redis_url
from configure_sql_database import configure as configure_sql_database
from package_api import package_api


@pytest.mark.parametrize("matching_sid", [True, False])
def test_sql_user_uses_managed_identity_client_id_and_rejects_another_sid(monkeypatch, matching_sid):
    client_id = "11112222-3333-4444-5555-666677778888"
    sid = uuid.UUID(client_id).bytes_le
    cursor = Mock()
    cursor.fetchone.return_value = (sid if matching_sid else bytes(16),)
    cursor.fetchall.return_value = [(role,) for role in (
        "db_datareader", "db_datawriter", "db_ddladmin",
    )]
    connection = Mock()
    connection.cursor.return_value = cursor
    credential = Mock()
    monkeypatch.setattr("configure_sql_database.AzureCliCredential", lambda **_: credential)
    monkeypatch.setattr("configure_sql_database.mssql_python.connect", lambda *_, **__: connection)
    args = SimpleNamespace(
        client_id=client_id, tenant="test-tenant",
        host="test.database.windows.net", database="test-db",
    )
    if matching_sid:
        configure_sql_database(args)
    else:
        with pytest.raises(RuntimeError, match="does not match"):
            configure_sql_database(args)
        assert not any("ALTER ROLE" in call.args[0] for call in cursor.execute.call_args_list)
    assert f"SID=0x{sid.hex()}" in cursor.execute.call_args_list[0].args[0]
    connection.close.assert_called_once()
    credential.close.assert_called_once()


def test_api_archive_contains_runtime_dependencies_and_migrations_not_tests(tmp_path):
    source, dependencies, runtime = (tmp_path / name for name in ("api", "packages", "runtime"))
    for relative in ("app/main.py", "migrations/env.py", "alembic.ini", "start_api.py"):
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("source")
    (source / "tests").mkdir()
    (source / "tests" / "private_test.py").write_text("not for production")
    path = dependencies / "uvicorn" / "__init__.py"
    path.parent.mkdir(parents=True)
    path.write_text("dependency")
    for name in ("copilot", "copilot-runtime", "runtime.node", ".hostless-runtime-assets-v2"):
        path = runtime / "prebuilds" / "linux-x64" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"binary")
    output = tmp_path / "api.zip"
    package_api(source, dependencies, runtime, output)
    with zipfile.ZipFile(output) as archive:
        assert archive.read("app/main.py") == b"source"
        assert archive.read(".python_packages/lib/site-packages/uvicorn/__init__.py") == b"dependency"
        assert archive.read("copilot-runtime/prebuilds/linux-x64/copilot") == b"binary"
        assert "tests/private_test.py" not in archive.namelist()
    marker = runtime / "prebuilds" / "linux-x64" / ".hostless-runtime-assets-v2"
    marker.write_bytes(b"")
    with pytest.raises(ValueError, match="Missing API release file"):
        package_api(source, dependencies, runtime, tmp_path / "incomplete.zip")
    marker.write_bytes(b"binary")
    (runtime / ".env").write_text("private")
    with pytest.raises(ValueError, match="private configuration"):
        package_api(source, dependencies, runtime, tmp_path / "unsafe.zip")


def settings():
    values = {
        "WAGL_PUBLIC_URL": "https://web.azurewebsites.net",
        "WAGL_KEY_VAULT_URL": "https://test.vault.azure.net/",
        "WAGL_COPILOT_CALLBACK_CONFIRMED": "true",
    }
    result = [{"key": key, "value": value} for key, value in values.items()]
    for key in (
        "WAGL_INTERNAL_SECRET", "WAGL_ENCRYPTION_KEY", "WAGL_DATABASE_URL", "WAGL_REDIS_URL",
        "WAGL_COPILOT_CLIENT_ID", "WAGL_COPILOT_CLIENT_SECRET",
    ):
        result.append({
            "key": key, "value": json.dumps({"uri": "https://test.vault.azure.net/secrets/test"}),
            "contentType": "application/vnd.microsoft.appconfig.keyvaultref+json;charset=utf-8",
        })
    return result


def test_api_configuration_requires_real_copilot_setup_and_native_secret_references():
    values = settings()
    validate_api_configuration(values, "https://web.azurewebsites.net")
    next(setting for setting in values if setting["key"] == "WAGL_COPILOT_CALLBACK_CONFIRMED")[
        "value"
    ] = "false"
    with pytest.raises(ValueError, match="callback"):
        validate_api_configuration(values, "https://web.azurewebsites.net")
    values = settings()
    next(setting for setting in values if setting["key"] == "WAGL_DATABASE_URL")[
        "contentType"
    ] = "text/plain"
    with pytest.raises(ValueError, match="native Key Vault"):
        validate_api_configuration(values, "https://web.azurewebsites.net")
    with pytest.raises(ValueError, match="WAGL_DATABASE_URL"):
        validate_api_configuration(
            [item for item in settings() if item["key"] != "WAGL_DATABASE_URL"],
            "https://web.azurewebsites.net",
        )


def test_startup_migration_failure_does_not_start_server(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "start_api", Path(__file__).parents[2] / "services" / "api" / "start_api.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = tmp_path / "api"
    packages = root / ".python_packages" / "lib" / "site-packages"
    packages.mkdir(parents=True)
    binary = root / "copilot-runtime" / "copilot"
    binary.parent.mkdir()
    binary.write_text("binary")
    binary.with_name("copilot-runtime").write_text("binary")
    monkeypatch.setattr(module, "__file__", str(root / "start_api.py"))
    monkeypatch.setattr(module.site, "addsitedir", lambda *_: None)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COPILOT_CLI_EXTRACT_DIR", "")
    monkeypatch.setenv("COPILOT_SKIP_CLI_DOWNLOAD", "")
    monkeypatch.setenv("PYTHONPATH", "")
    monkeypatch.setattr("copilot._cli_download.get_cached_cli_path", lambda: str(binary))

    def fail_migration(command, *, check):
        assert command[-2:] == ["upgrade", "head"] and check
        raise RuntimeError("migration failed")

    monkeypatch.setattr(module.subprocess, "run", fail_migration)
    monkeypatch.setattr(module.os, "execv", lambda *_: pytest.fail("Server must not start"))
    with pytest.raises(RuntimeError, match="migration failed"):
        module.main()


def test_backend_connection_urls_escape_secrets_and_require_verified_tls():
    from urllib.parse import parse_qs, unquote, urlsplit

    password = "a:b/@?+%#"
    database = urlsplit(database_url(
        "example.postgres.database.azure.com", "wagladmin", password, "waglwaglagent-db"
    ))
    assert unquote(database.password) == password
    assert parse_qs(database.query)["sslmode"] == ["verify-full"]
    cache = urlsplit(redis_url("example.koreacentral.redis.azure.net", password))
    assert unquote(cache.password) == password
    assert cache.scheme == "rediss" and cache.port == 10000
    assert parse_qs(cache.query)["ssl_cert_reqs"] == ["required"]
    for host in ("invalid.test", "a.redis.azure.net@evil.test"):
        with pytest.raises(ValueError, match="hostname"):
            redis_url(host, password)
    with pytest.raises(ValueError, match="hostname"):
        database_url("a@b.postgres.database.azure.com", "user", password, "db")
