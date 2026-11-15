"""Grant the App Service identity SQL access using the tenant's Entra administrator."""

import argparse
import uuid

import mssql_python
from azure.identity import AzureCliCredential
from configure_backend import sql_database_url


def configure(args):
    sql_database_url(args.host, args.database)
    # TYPE=E uses the application/client ID for service principals, not their object ID.
    principal = uuid.UUID(args.client_id)
    sid = principal.bytes_le.hex()
    credential = AzureCliCredential(tenant_id=args.tenant)
    connection = mssql_python.connect(
        f"Server={args.host};Database={args.database};Encrypt=yes;TrustServerCertificate=no",
        token_provider=credential, autocommit=True,
    )
    try:
        cursor = connection.cursor()
        cursor.execute(
            "IF NOT EXISTS (SELECT 1 FROM sys.database_principals "
            "WHERE name = 'waglwaglagent-api') "
            f"CREATE USER [waglwaglagent-api] WITH SID=0x{sid}, TYPE=E"
        )
        cursor.execute(
            "SELECT sid FROM sys.database_principals WHERE name = 'waglwaglagent-api'"
        )
        if bytes(cursor.fetchone()[0]) != principal.bytes_le:
            raise RuntimeError("Existing SQL identity does not match the actual App Service")
        for role in ("db_datareader", "db_datawriter", "db_ddladmin"):
            cursor.execute(f"ALTER ROLE [{role}] ADD MEMBER [waglwaglagent-api]")
        cursor.execute(
            "SELECT r.name FROM sys.database_role_members AS m "
            "JOIN sys.database_principals AS r ON r.principal_id=m.role_principal_id "
            "JOIN sys.database_principals AS u ON u.principal_id=m.member_principal_id "
            "WHERE u.name='waglwaglagent-api'"
        )
        roles = {row[0] for row in cursor.fetchall()}
        if roles != {"db_datareader", "db_datawriter", "db_ddladmin"}:
            raise RuntimeError("Unexpected SQL database roles")
        print("Verified API Entra SID and SQL read/write/startup-migration roles.")
    finally:
        connection.close()
        credential.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--database", default="waglwaglagent-db")
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--client-id", required=True)
    try:
        configure(parser.parse_args())
    except (mssql_python.Error, RuntimeError, ValueError) as error:
        raise SystemExit(
            f"SQL configuration failed ({type(error).__name__}); no credentials logged."
        ) from None
