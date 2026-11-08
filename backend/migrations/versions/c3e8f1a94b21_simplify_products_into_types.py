"""simplify products into plain types

Drops the four rule-engine flags (require_amount / require_email /
require_password / allow_screenshot). None of them were ever read by any
code path, so they only added noise in the UI.

NOTE: this revision was later found to be insufficient (it left ``code``,
``default_currency`` and ``default_login_method`` behind for databases that had
already run it). Do not add further steps here -- a revision that has shipped is
never re-run. Reconciliation lives in ``d5a7c3e91b44``.

Revision ID: c3e8f1a94b21
Revises: 9f4d1b8a2c77
Create Date: 2026-10-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3e8f1a94b21"
down_revision: Union[str, None] = "9f4d1b8a2c77"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LEGACY_FLAGS = (
    "require_amount",
    "require_email",
    "require_password",
    "allow_screenshot",
)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "products" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("products")}

    for column in _LEGACY_FLAGS:
        if column in existing:
            op.drop_column("products", column)

    # `code` stays, but becomes optional.
    if "code" in existing:
        with op.batch_alter_table("products") as batch:
            batch.alter_column(
                "code",
                existing_type=sa.String(length=64),
                nullable=True,
            )


def downgrade() -> None:
    with op.batch_alter_table("products") as batch:
        batch.alter_column(
            "code",
            existing_type=sa.String(length=64),
            nullable=False,
        )

    for column in reversed(_LEGACY_FLAGS):
        op.add_column(
            "products",
            sa.Column(column, sa.Boolean(), nullable=True, server_default=sa.false()),
        )