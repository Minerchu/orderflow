"""ensure products is name-only (idempotent reconciliation)

Why this revision exists
------------------------
An earlier revision (``c3e8f1a94b21``) was shipped and then edited in place to
drop three more columns. Alembic keys off the revision *id*, so anyone who
already ran it before the edit is stamped ``c3e8f1a94b21`` and will never
re-run it -- leaving the database in a half-migrated state with
``code`` / ``default_currency`` / ``default_login_method`` still present while
the code expects them gone.

This revision is deliberately idempotent: it inspects the live schema and only
drops what is actually there. That makes it safe for

* fresh installs      -> nothing left to do
* half-migrated DBs    -> removes the leftovers
* fully-migrated DBs   -> no-op

Revision ID: d5a7c3e91b44
Revises: c3e8f1a94b21
Create Date: 2026-10-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d5a7c3e91b44"
down_revision: Union[str, None] = "c3e8f1a94b21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Anything not part of the final name-only shape.
_LEFTOVER_COLUMNS = (
    "require_amount",
    "require_email",
    "require_password",
    "allow_screenshot",
    "code",
    "default_currency",
    "default_login_method",
)

_EXPECTED = {"id", "name", "is_active", "created_at", "updated_at"}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "products" not in inspector.get_table_names():
        return

    existing = {c["name"] for c in inspector.get_columns("products")}
    leftover = [c for c in _LEFTOVER_COLUMNS if c in existing]

    # Fast path: already correct.
    if not leftover:
        return

    # Drop indexes that reference the doomed columns first. SQLite refuses
    # DROP COLUMN while an index still covers it ("error in index ... after
    # drop column"). PostgreSQL would survive, but do it for both.
    live_indexes = {ix["name"]: ix for ix in inspector.get_indexes("products")}
    for index_name, index in live_indexes.items():
        columns = set(index.get("column_names") or [])
        if columns & set(leftover):
            op.drop_index(index_name, table_name="products")

    # Relax NOT NULL so the table stays valid mid-migration.
    inspector = sa.inspect(bind)
    for column in leftover:
        column_info = next(
            (c for c in inspector.get_columns("products") if c["name"] == column), None
        )
        if column_info and not column_info.get("nullable", True):
            with op.batch_alter_table("products") as batch:
                batch.alter_column(
                    column,
                    existing_type=column_info["type"],
                    nullable=True,
                )

    for column in leftover:
        op.drop_column("products", column)

    # Re-create the unique index on `name` only when the rebuild dropped it.
    live_indexes = {ix["name"] for ix in sa.inspect(bind).get_indexes("products")}
    if "ix_products_name" not in live_indexes:
        op.create_index("ix_products_name", "products", ["name"], unique=True)


def downgrade() -> None:
    """Re-add the removed columns as nullable so older code can still read it."""
    op.add_column("products", sa.Column("code", sa.String(length=64), nullable=True))
    op.add_column(
        "products",
        sa.Column("default_currency", sa.String(length=8), nullable=True, server_default="INR"),
    )
    op.add_column(
        "products", sa.Column("default_login_method", sa.String(length=20), nullable=True)
    )
    for column in ("require_amount", "require_email", "require_password", "allow_screenshot"):
        op.add_column(
            "products",
            sa.Column(column, sa.Boolean(), nullable=True, server_default=sa.false()),
        )