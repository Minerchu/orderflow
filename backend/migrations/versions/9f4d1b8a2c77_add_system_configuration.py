"""add system configuration

Revision ID: 9f4d1b8a2c77
Revises: 7333717e53eb
Create Date: 2026-10-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9f4d1b8a2c77"
down_revision: Union[str, None] = "7333717e53eb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "system_configs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("telegram_bot_token_encrypted", sa.Text(), nullable=True),
        sa.Column(
            "telegram_default_chat_id",
            sa.String(length=128),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "telegram_allowed_chat_ids",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "admin_telegram_user_ids",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("system_configs")
