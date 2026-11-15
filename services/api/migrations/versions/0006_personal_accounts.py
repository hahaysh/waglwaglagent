"""Introduce independent accounts only after explicitly approved legacy cleanup."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

OWNER_TABLES = ("credentials", "oauth_attempts", "conversations", "runs")


def upgrade():
    connection = op.get_bind()
    for table in OWNER_TABLES:
        if connection.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one():
            raise RuntimeError(
                "Personal accounts require explicitly approved legacy user-data cleanup; "
                "this migration never deletes or transfers user data"
            )
    op.create_table(
        "users", sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
    )
    op.create_table(
        "login_identities", sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("identity_key", sa.String(64), nullable=False, unique=True),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("issuer", sa.String(256), nullable=False),
        sa.Column("subject", sa.String(256), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
    )
    op.create_index("ix_login_identities_user_id", "login_identities", ["user_id"])
    op.create_table(
        "web_sessions", sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "identity_id", sa.String(36), sa.ForeignKey("login_identities.id"), nullable=False,
        ),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("expires_at", sa.String(40), nullable=False),
        sa.Column("revoked_at", sa.String(40), nullable=True),
    )
    op.create_index("ix_web_sessions_user_id", "web_sessions", ["user_id"])
    op.create_index("ix_web_sessions_identity_id", "web_sessions", ["identity_id"])
    for table in OWNER_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.drop_index(f"ix_{table}_owner_id")
            if table == "credentials":
                batch.drop_index("uq_provider_account")
            batch.alter_column(
                "owner_id", existing_type=sa.String(100), type_=sa.String(36),
                existing_nullable=False,
            )
            batch.create_foreign_key(f"fk_{table}_owner_id_users", "users", ["owner_id"], ["id"])
            batch.create_index(f"ix_{table}_owner_id", ["owner_id"])
            if table == "credentials":
                batch.create_index(
                    "uq_provider_account", ["owner_id", "provider", "provider_subject"],
                    unique=True, mssql_where=sa.text("provider_subject IS NOT NULL"),
                )


def downgrade():
    raise RuntimeError("Personal account data cannot be downgraded to GitHub-only ownership")
