from __future__ import annotations

from datetime import datetime, date, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Date,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.constants import SETTLEMENT_STATUSES, SETTLEMENT_DRAFT


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SettlementBatch(Base):
    __tablename__ = "settlement_batches"
    __table_args__ = (
        CheckConstraint(
            "status IN (%s)" % ",".join("'%s'" % s for s in SETTLEMENT_STATUSES),
            name="ck_settlement_status",
        ),
        Index("ix_settlement_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    settlement_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default=SETTLEMENT_DRAFT)
    # "group" settles the chat ledger; "dispatcher" settles one dispatcher's
    # private ledger. Kept explicit so history stays readable and exports and
    # confirm/cancel logic can branch on it.
    settlement_type: Mapped[str] = mapped_column(String(20), default="group", index=True)
    dispatcher_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )

    filter_conditions: Mapped[dict] = mapped_column(JSON, default=dict)
    order_count: Mapped[int] = mapped_column(Integer, default=0)

    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    confirmed_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class SettlementItem(Base):
    __tablename__ = "settlement_items"
    __table_args__ = (
        # An order may only belong to ONE valid (non-cancelled) batch.
        UniqueConstraint("order_id", "settlement_batch_id", name="uq_settlement_item"),
        Index("ix_settlement_items_batch", "settlement_batch_id"),
        Index("ix_settlement_items_order", "order_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    settlement_batch_id: Mapped[int] = mapped_column(
        ForeignKey("settlement_batches.id", ondelete="CASCADE"), index=True
    )
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id"), index=True
    )
    amount_snapshot: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency_snapshot: Mapped[str] = mapped_column(String(8))
    product_snapshot: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    partner_snapshot: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    completed_at_snapshot: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
