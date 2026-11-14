"""Persist validated chat attachments with their owning message."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("messages") as batch:
        batch.add_column(sa.Column("attachments", sa.JSON(), nullable=False, server_default="[]"))
    with op.batch_alter_table("messages") as batch:
        batch.alter_column("attachments", server_default=None)


def downgrade():
    messages = sa.table("messages", sa.column("attachments", sa.JSON()))
    if any(op.get_bind().execute(sa.select(messages.c.attachments)).scalars()):
        raise RuntimeError("Delete conversations containing attachments before downgrading")
    with op.batch_alter_table("messages") as batch:
        batch.drop_column("attachments")
