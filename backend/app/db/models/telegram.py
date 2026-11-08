from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TelegramUpdate(Base):
    """Webhook-level idempotency table for inbound updates / callback queries."""

    __tablename__ = "telegram_updates"
    __table_args__ = (
        UniqueConstraint("update_key", name="uq_telegram_update_key"),
        Index("ix_tg_updates_processed", "processed"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    update_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    processed: Mapped[bool] = mapped_column(Boolean, default=False)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TelegramOutbox(Base):
    """Transactional outbox for reliable Telegram message delivery & retries."""

    __tablename__ = "telegram_outbox"
    __table_args__ = (Index("ix_outbox_status", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("orders.id"), nullable=True, index=True
    )
    chat_id: Mapped[str] = mapped_column(String(64), index=True)
    message_type: Mapped[str] = mapped_column(String(30), default="order")
    payload: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    telegram_message_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
