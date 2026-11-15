"""Dry-run legacy user cleanup. Execution requires an exact approved digest and maintenance."""

import argparse
import hashlib
import json
import re
from pathlib import Path

from redis import Redis
from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.engine import make_url

from app.config import get_settings
from app.models import make_engine
from app.security import delete_key
from app.vault import connection_secret_name

TABLES = ("attempts", "messages", "runs", "conversations", "oauth_attempts", "credentials")


def inventory(engine, database_url: str) -> dict:
    url = make_url(database_url)
    target = (
        str(Path(url.database).resolve()) if url.drivername.startswith("sqlite")
        else f"{url.host}/{url.database}"
    )
    with engine.connect() as connection:
        schema_version = connection.execute(
            text("SELECT version_num FROM alembic_version"),
        ).scalar_one()
        if schema_version not in {"0004", "0005"}:
            raise ValueError("Legacy cleanup requires schema 0004/0005 before personal accounts")
        rows = {
            table: [row[0] for row in connection.execute(
                text(f"SELECT id FROM {table} ORDER BY id"),
            )] for table in TABLES
        }
        credentials = connection.execute(text(
            "SELECT id,owner_id,secret_format,encrypted_secret,provider,provider_subject,"
            "quota_group,upstreams FROM credentials ORDER BY id"
        )).mappings().all()
        owners = set()
        for table in ("credentials", "oauth_attempts", "conversations", "runs"):
            owners.update(connection.execute(
                text(f"SELECT DISTINCT owner_id FROM {table}"),
            ).scalars())
        if any(not owner.startswith("github:") for owner in owners):
            raise ValueError("Non-legacy owner found; stop and review the cleanup scope")
        references, redis_keys, fingerprints = [], set(), []
        for owner in owners:
            for scope in ("active", "rate:chat", "rate:credential", "rate:catalog", "rate:oauth"):
                redis_keys.add("wagl:" + hashlib.sha256(f"{owner}:{scope}".encode()).hexdigest())
        for row in credentials:
            if row["secret_format"] not in {"api_key_v1", "oauth_v1"}:
                raise ValueError("Unknown credential secret format; stop before cleanup")
            record = row["id"] + (":oauth_v1" if row["secret_format"] == "oauth_v1" else "")
            reference = row["encrypted_secret"]
            fingerprints.append(hashlib.sha256(reference.encode()).hexdigest())
            if reference.startswith("kv://"):
                expected = connection_secret_name(row["owner_id"], record)
                name, separator, version = reference.removeprefix("kv://").partition("/")
                if (
                    name != expected or not separator
                    or not re.fullmatch(r"[a-fA-F0-9]{32}", version)
                ):
                    raise ValueError("Unverified Key Vault reference; no cleanup performed")
                references.append({
                    "owner": row["owner_id"], "record": record, "reference": reference,
                })
            scope = (
                f"copilot:{row['provider_subject']}" if row["provider"] == "copilot"
                else f"{row['provider']}:{row['quota_group']}"
            )
            upstreams = json.loads(row["upstreams"]) if isinstance(
                row["upstreams"], str,
            ) else row["upstreams"]
            scopes = ["rate:" + scope, "cooldown:" + scope]
            for upstream in upstreams or []:
                scopes.append(f"cooldown:endpoint:{row['id']}:{(upstream,)}")
            for entry in scopes:
                redis_keys.add("wagl:" + hashlib.sha256(
                    f"{row['owner_id']}:{entry}".encode(),
                ).hexdigest())
    result = {
        "target": target, "schema": schema_version, "rows": rows, "owners": sorted(owners),
        "key_vault_references": references, "secret_fingerprints": fingerprints,
        "redis_keys": sorted(redis_keys),
        "protected": "Azure resources, operational secrets/keys, migration history and backups",
    }
    result["approval_digest"] = hashlib.sha256(
        json.dumps(result, sort_keys=True, separators=(",", ":")).encode(),
    ).hexdigest()
    return result


def execute(engine, expected: dict, approved_digest: str, drained: bool):
    settings = get_settings()
    if not settings.maintenance_enabled or not drained:
        raise ValueError("Execution requires approved maintenance and verified request drain")
    current = inventory(engine, settings.database_url)
    if approved_digest != expected["approval_digest"] or current != expected:
        raise ValueError("Cleanup inventory changed; obtain new explicit approval")
    for reference in current["key_vault_references"]:
        delete_key(reference["reference"], reference["owner"], reference["record"])
    if settings.redis_url and current["redis_keys"]:
        with Redis.from_url(settings.redis_url) as redis:
            redis.delete(*current["redis_keys"])
    with engine.begin() as connection:
        for table in TABLES:
            ids = current["rows"][table]
            for offset in range(0, len(ids), 500):
                connection.execute(
                    text(f"DELETE FROM {table} WHERE id IN :ids").bindparams(
                        bindparam("ids", expanding=True),
                    ), {"ids": ids[offset:offset + 500]},
                )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--approved-inventory", type=Path)
    parser.add_argument("--approved-digest")
    parser.add_argument("--drained", action="store_true")
    parser.add_argument("--sql-cli", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    credential = None
    if args.sql_cli:
        from azure.identity import AzureCliCredential

        url = make_url(settings.database_url)
        if url.drivername != "mssql+mssqlpython":
            raise ValueError("--sql-cli requires the selected Azure SQL database")
        credential = AzureCliCredential(tenant_id=settings.azure_tenant_id or None)
        url = url.set(query={
            key: value for key, value in url.query.items() if key != "authentication"
        })
        engine = create_engine(
            url, connect_args={"token_provider": credential}, deprecate_large_types=True,
        )
    else:
        engine = make_engine(settings.database_url)
    try:
        if args.approved_inventory:
            if not args.approved_digest:
                raise ValueError("Explicit approval digest is required")
            expected = json.loads(args.approved_inventory.read_text(encoding="utf-8"))
            execute(engine, expected, args.approved_digest, args.drained)
            print("Only explicitly approved legacy rows/references were removed.")
        else:
            if args.approved_digest or args.drained:
                raise ValueError("Execution flags require an approved inventory file")
            result = inventory(engine, settings.database_url)
            rendered = json.dumps(result, ensure_ascii=True, indent=2)
            if args.output:
                args.output.write_text(rendered, encoding="utf-8")
            print(rendered)
    finally:
        engine.dispose()
        if credential:
            credential.close()


if __name__ == "__main__":
    main()
