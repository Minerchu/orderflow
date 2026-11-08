"""add settlement cycle to orders

Sequence numbers ("No.1 / No.2 / No.3...") are scoped to a cycle so that, once
a settlement batch is confirmed, the next batch starts counting from 1 again.

Existing orders get cycle_id = NULL, which behaves as "the original cycle" and
keeps their numbering exactly as it was.

Revision ID: f2c9e6b48d05
Revises: e8b2d4f60c17
Create Date: 2026-10-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f2c9e6b48d05"
down_revision: Union[str, None] = "e8b2d4f60c17"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    if _has_column("orders", "cycle_id"):
        return
    op.add_column("orders", sa.Column("cycle_id", sa.Integer(), nullable=True))
    # Existing rows keep cycle_id NULL (= original cycle), so numbering is
    # unchanged for everything that already exists.
    try:
        op.create_index("ix_orders_cycle_id", "orders", ["cycle_id"], unique=False)
    except Exception:
        # A pre-existing index with the same name would only be a warning.
        pass


def downgrade() -> None:
    if not _has_column("orders", "cycle_id"):
        return
    try:
        op.drop_index("ix_orders_cycle_id", table_name="orders")
    except Exception:
        pass
    op.drop_column("orders", "cycle_id")