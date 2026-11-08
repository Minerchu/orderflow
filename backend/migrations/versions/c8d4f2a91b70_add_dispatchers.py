"""Add dispatchers: product whitelist, default chat, Telegram binding, dual settlement."""

from alembic import op
import sqlalchemy as sa

revision = "c8d4f2a91b70"
down_revision = "d1a7c4e92f60"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Dispatcher configuration -------------------------------------------
    op.add_column("users", sa.Column("default_chat_id", sa.String(length=64), nullable=True))
    op.create_table(
        "dispatcher_product_access",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("user_id", "product_id", name="uq_dispatcher_product_access"),
    )
    op.create_index("ix_dispatcher_product_access_user_id", "dispatcher_product_access", ["user_id"])
    op.create_index("ix_dispatcher_product_access_product_id", "dispatcher_product_access", ["product_id"])

    op.create_table(
        "telegram_bind_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("token_hash", name="uq_telegram_bind_token_hash"),
    )
    op.create_index("ix_telegram_bind_tokens_user_id", "telegram_bind_tokens", ["user_id"])
    op.create_index("ix_telegram_bind_tokens_token_hash", "telegram_bind_tokens", ["token_hash"])

    # --- Dual settlement ----------------------------------------------------
    # Existing rows are group-ledger rows and are still unsettled for their
    # dispatcher (there are no dispatcher orders yet) -> safe defaults.
    op.add_column(
        "orders",
        sa.Column("dispatcher_settlement_status", sa.String(length=20),
                  nullable=False, server_default="unsettled"),
    )
    op.create_index("ix_orders_dispatcher_settlement_status", "orders",
                    ["dispatcher_settlement_status"])

    op.add_column(
        "settlement_batches",
        sa.Column("settlement_type", sa.String(length=20),
                  nullable=False, server_default="group"),
    )
    # SQLite cannot ALTER-add a column that carries a constraint. Add the
    # plain column everywhere and create the FK only where the dialect supports
    # it (PostgreSQL in production; tests run on SQLite).
    op.add_column(
        "settlement_batches",
        sa.Column("dispatcher_user_id", sa.Integer(), nullable=True),
    )
    if op.get_bind().dialect.name != "sqlite":
        op.create_foreign_key(
            "fk_settlement_batches_dispatcher_user_id",
            "settlement_batches", "users",
            ["dispatcher_user_id"], ["id"],
        )
    op.create_index("ix_settlement_batches_settlement_type", "settlement_batches",
                    ["settlement_type"])
    op.create_index("ix_settlement_batches_dispatcher_user_id", "settlement_batches",
                    ["dispatcher_user_id"])


def downgrade() -> None:
    op.drop_index("ix_settlement_batches_dispatcher_user_id", table_name="settlement_batches")
    op.drop_index("ix_settlement_batches_settlement_type", table_name="settlement_batches")
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint("fk_settlement_batches_dispatcher_user_id",
                           "settlement_batches", type_="foreignkey")
    op.drop_column("settlement_batches", "dispatcher_user_id")
    op.drop_column("settlement_batches", "settlement_type")

    op.drop_index("ix_orders_dispatcher_settlement_status", table_name="orders")
    op.drop_column("orders", "dispatcher_settlement_status")

    op.drop_index("ix_telegram_bind_tokens_token_hash", table_name="telegram_bind_tokens")
    op.drop_index("ix_telegram_bind_tokens_user_id", table_name="telegram_bind_tokens")
    op.drop_table("telegram_bind_tokens")

    op.drop_index("ix_dispatcher_product_access_product_id", table_name="dispatcher_product_access")
    op.drop_index("ix_dispatcher_product_access_user_id", table_name="dispatcher_product_access")
    op.drop_table("dispatcher_product_access")

    op.drop_column("users", "default_chat_id")
