from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.constants import (
    CURRENCY_INR,
    FIN_STATUSES,
    FIN_STATUS_UNSETTLED,
    LOGIN_METHODS,
    ORDER_STATUSES,
    ORDER_STATUS_DRAFT,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint(
            "currency IN ('INR','USD')", name="ck_orders_currency"
        ),
        CheckConstraint(
            "order_status IN (%s)" % ",".join("'%s'" % s for s in ORDER_STATUSES),
            name="ck_orders_status",
        ),
        CheckConstraint(
            "financial_status IN (%s)" % ",".join("'%s'" % s for s in FIN_STATUSES),
            name="ck_orders_fin_status",
        ),
        Index("ix_orders_currency_amount", "currency", "amount"),
        Index("ix_orders_status_fin", "order_status", "financial_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_number: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    product_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("products.id"), nullable=True, index=True
    )
    product_name_snapshot: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default=CURRENCY_INR)

    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    password_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    login_method: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    account: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Raw, verbatim account block typed by the admin. One input line -> one
    # displayed line in the group message, each with its own copy button.
    account_info: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    order_status: Mapped[str] = mapped_column(
        String(20), default=ORDER_STATUS_DRAFT
    )
    # Independent of financial_status: this tracks the *dispatcher* ledger.
    # Settling with a dispatcher must never remove the order from the group
    # ledger, so the two columns are advanced by separate batches.
    dispatcher_settlement_status: Mapped[str] = mapped_column(
        String(20), default="unsettled", index=True
    )
    financial_status: Mapped[str] = mapped_column(
        String(20), default=FIN_STATUS_UNSETTLED
    )

    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    order_owner_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    accepted_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    completed_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    failed_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    closed_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    telegram_chat_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    telegram_message_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # True when telegram_message_id points at a *photo* message. Telegram only
    # accepts editMessageCaption on those -- editMessageText is rejected with
    # "there is no text in the message to edit", which used to silently break
    # every status update for image orders.
    telegram_message_is_media: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    telegram_send_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    telegram_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    accepted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    failure_reason: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    failure_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    amount_confirmed: Mapped[bool] = mapped_column(
    Boolean, default=False, index=True
    )

    # Settlement cycle this order belongs to. Sequence numbers restart at 1 for
    # each cycle, so "No.1 of this batch" stays meaningful after settlement.
    cycle_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, index=True
    )

    # Relationships (no schema impact; enable order.attachments / order.events)
    attachments: Mapped[list["OrderAttachment"]] = relationship(
        "OrderAttachment", lazy="select", order_by="OrderAttachment.id"
    )
    events: Mapped[list["OrderEvent"]] = relationship(
        "OrderEvent", lazy="select", order_by="OrderEvent.id"
    )
    amount_confirmed_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    amount_confirmed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class OrderAttachment(Base):
    __tablename__ = "order_attachments"
    __table_args__ = (Index("ix_attachments_order", "order_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE")
    )
    storage_key: Mapped[str] = mapped_column(String(512))
    original_filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    mime_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    telegram_file_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    uploaded_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OrderEvent(Base):
    __tablename__ = "order_events"
    __table_args__ = (Index("ix_order_events_order", "order_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE")
    )
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    from_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    to_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    actor_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    telegram_user_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    telegram_username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
