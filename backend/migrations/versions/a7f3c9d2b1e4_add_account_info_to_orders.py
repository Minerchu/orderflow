"""add account_info to orders

The admin now fills a single multi-line "account info" box. Each line is stored
verbatim and rendered as its own line in the group message, with a one-tap copy
button per line (passwords included -- no hiding). This replaces the old
email/account/password split. Existing orders keep account_info NULL and fall
back to the legacy rendering, so nothing breaks.

Revision ID: a7f3c9d2b1e4
Revises: f2c9e6b48d05
Create Date: 2026-10-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7f3c9d2b1e4"
down_revision: Union[str, None] = "f2c9e6b48d05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    if _has_column("orders", "account_info"):
        return
    op.add_column("orders", sa.Column("account_info", sa.Text(), nullable=True))


def downgrade() -> None:
    if not _has_column("orders", "account_info"):
        return
    op.drop_column("orders", "account_info")
