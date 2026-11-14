"""Encrypt persisted customer content without moving documents into Key Vault."""

import json

import sqlalchemy as sa
from alembic import op

from app.encryption import seal, unseal

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def transform(encrypt: bool):
    bind = op.get_bind()
    for table_name, column_name in (
        ("credentials", "label"), ("conversations", "title"), ("messages", "content"),
        ("messages", "attachments"),
    ):
        is_json = column_name == "attachments"
        table = sa.table(
            table_name, sa.column("id", sa.String()),
            sa.column(column_name, sa.JSON() if is_json else sa.Text()),
        )
        for row in bind.execute(sa.select(table)).mappings().yield_per(20):
            value = row[column_name]
            context = f"{table_name}.{column_name}"
            if encrypt:
                value = (
                    {"encrypted": seal(json.dumps(value), context)}
                    if is_json else seal(value, context)
                )
            else:
                value = (
                    json.loads(unseal(value["encrypted"], context))
                    if is_json else unseal(value, context)
                )
            bind.execute(
                table.update().where(table.c.id == row["id"]).values({column_name: value})
            )


def upgrade():
    with op.batch_alter_table("credentials") as batch:
        batch.alter_column("label", existing_type=sa.String(80), type_=sa.Text())
    with op.batch_alter_table("conversations") as batch:
        batch.alter_column("title", existing_type=sa.String(120), type_=sa.Text())
    transform(True)


def downgrade():
    raise RuntimeError(
        "Encrypted customer data cannot be downgraded automatically; restore an encrypted backup"
    )
