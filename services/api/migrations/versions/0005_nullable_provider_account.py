"""Preserve multiple API keys without a provider subject on SQL Server."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("credentials") as batch:
        batch.drop_constraint("uq_provider_account", type_="unique")
        batch.create_index(
            "uq_provider_account", ["owner_id", "provider", "provider_subject"],
            unique=True, mssql_where=sa.text("provider_subject IS NOT NULL"),
        )


def downgrade():
    raise RuntimeError(
        "Nullable provider accounts cannot be downgraded to SQL Server NULL uniqueness"
    )
