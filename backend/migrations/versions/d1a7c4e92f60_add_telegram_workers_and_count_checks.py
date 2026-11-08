"""Add Telegram workers, group permissions, and count confirmations."""

from alembic import op
import sqlalchemy as sa

revision = "d1a7c4e92f60"
down_revision = "b6d1f7a30e58"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("display_name", sa.String(length=128), nullable=True))
    op.create_table(
        "partner_chat_access",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chat_id", sa.String(length=64), nullable=False),
        sa.UniqueConstraint("user_id", "chat_id", name="uq_partner_chat_access"),
    )
    op.create_index("ix_partner_chat_access_user_id", "partner_chat_access", ["user_id"])
    op.create_index("ix_partner_chat_access_chat_id", "partner_chat_access", ["chat_id"])
    op.create_table(
        "payment_count_checks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chat_id", sa.String(length=64), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("order_signature", sa.String(length=64), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "chat_id", "currency", "amount", name="uq_payment_count_check"),
    )
    op.create_index("ix_payment_count_checks_user_id", "payment_count_checks", ["user_id"])
    op.create_index("ix_payment_count_checks_chat_id", "payment_count_checks", ["chat_id"])


def downgrade() -> None:
    op.drop_index("ix_payment_count_checks_chat_id", table_name="payment_count_checks")
    op.drop_index("ix_payment_count_checks_user_id", table_name="payment_count_checks")
    op.drop_table("payment_count_checks")
    op.drop_index("ix_partner_chat_access_chat_id", table_name="partner_chat_access")
    op.drop_index("ix_partner_chat_access_user_id", table_name="partner_chat_access")
    op.drop_table("partner_chat_access")
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "display_name")
