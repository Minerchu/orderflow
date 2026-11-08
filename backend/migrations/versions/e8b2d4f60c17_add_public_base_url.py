"""allow the Telegram webhook URL to be set from the admin UI

Adds ``system_configs.public_base_url``. Previously the callback URL came only
from the ``APP_BASE_URL`` environment variable, so a deployment whose env was
left at ``http://localhost`` could not fix it without editing .env and
restarting the stack -- and the symptom (group buttons silently doing nothing)
was very hard to diagnose.

The column defaults to '' so the env value keeps working as the fallback.

Revision ID: e8b2d4f60c17
Revises: d5a7c3e91b44
Create Date: 2026-10-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e8b2d4f60c17"
down_revision: Union[str, None] = "d5a7c3e91b44"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    # Idempotent: never fail if this has already been applied.
    if not _has_column("system_configs", "public_base_url"):
        op.add_column(
            "system_configs",
            sa.Column(
                "public_base_url",
                sa.String(length=256),
                nullable=False,
                server_default="",
            ),
        )


def downgrade() -> None:
    if _has_column("system_configs", "public_base_url"):
        op.drop_column("system_configs", "public_base_url")