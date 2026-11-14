"""Store OAuth connections separately from inference consent."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("credentials") as batch:
        batch.alter_column("encrypted_key", new_column_name="encrypted_secret",
                           existing_type=sa.Text(), existing_nullable=False)
        batch.alter_column("fingerprint", nullable=True, existing_type=sa.String(64))
        batch.alter_column("model", nullable=True, existing_type=sa.String(200))
        for name, kind, default in [
            ("secret_format", sa.String(30), "api_key_v1"),
            ("encryption_key_version", sa.Integer(), "1"),
            ("auth_type", sa.String(20), "api_key"),
            ("auth_status", sa.String(30), "authenticated"),
            ("scopes", sa.JSON(), "[]"),
            ("token_version", sa.Integer(), "1"),
            ("usage_policy", sa.String(30), "free_only"),
        ]:
            batch.add_column(sa.Column(name, kind, nullable=False, server_default=default))
        batch.add_column(sa.Column("provider_subject", sa.String(100), nullable=True))
        batch.add_column(sa.Column("expires_at", sa.String(40), nullable=True))
        batch.create_unique_constraint(
            "uq_provider_account", ["owner_id", "provider", "provider_subject"]
        )
    with op.batch_alter_table("credentials") as batch:
        for name in [
            "secret_format", "encryption_key_version", "auth_type", "auth_status",
            "scopes", "token_version", "usage_policy",
        ]:
            batch.alter_column(name, server_default=None)
    op.execute(
        sa.text("UPDATE credentials SET auth_status = 'reauth_required' WHERE status = 'invalid'")
    )
    op.create_table(
        "oauth_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(100), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("state_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("binding_hash", sa.String(64), nullable=False),
        sa.Column("encrypted_verifier", sa.Text(), nullable=True),
        sa.Column("redirect_uri", sa.String(500), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("expires_at", sa.String(40), nullable=False),
        sa.Column("connection_id", sa.String(36), nullable=True),
    )
    op.create_index("ix_oauth_attempts_owner_id", "oauth_attempts", ["owner_id"])


def downgrade():
    connection = op.get_bind()
    if connection.scalar(sa.text(
        "SELECT count(*) FROM credentials "
        "WHERE auth_type != 'api_key' OR model IS NULL OR fingerprint IS NULL"
    )):
        raise RuntimeError("Disconnect new connections without legacy fields before downgrading")
    op.drop_index("ix_oauth_attempts_owner_id", table_name="oauth_attempts")
    op.drop_table("oauth_attempts")
    with op.batch_alter_table("credentials") as batch:
        batch.drop_constraint("uq_provider_account", type_="unique")
        for name in [
            "secret_format", "encryption_key_version", "auth_type", "auth_status",
            "provider_subject", "scopes", "expires_at", "token_version", "usage_policy",
        ]:
            batch.drop_column(name)
        batch.alter_column("encrypted_secret", new_column_name="encrypted_key",
                           existing_type=sa.Text(), existing_nullable=False)
        batch.alter_column("fingerprint", nullable=False, existing_type=sa.String(64))
        batch.alter_column("model", nullable=False, existing_type=sa.String(200))
