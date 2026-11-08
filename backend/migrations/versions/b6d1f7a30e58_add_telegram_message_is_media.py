"""add telegram_message_is_media to orders

Image orders post their card as a Telegram *photo* message, and Telegram only
accepts ``editMessageCaption`` on media -- ``editMessageText`` is rejected with
"there is no text in the message to edit". Without remembering which kind of
message anchors an order, every status update for an image order silently
failed and the group card went stale ("订单点了没反应").

This column records that fact so the refresh path can pick the right API call.
Existing rows default to false (text messages), which is correct for every
order created before image orders could carry buttons.

Revision ID: b6d1f7a30e58
Revises: a7f3c9d2b1e4
Create Date: 2026-10-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b6d1f7a30e58"
down_revision: Union[str, None] = "a7f3c9d2b1e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    if _has_column("orders", "telegram_message_is_media"):
        return
    op.add_column(
        "orders",
        sa.Column(
            "telegram_message_is_media",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    if not _has_column("orders", "telegram_message_is_media"):
        return
    op.drop_column("orders", "telegram_message_is_media")
