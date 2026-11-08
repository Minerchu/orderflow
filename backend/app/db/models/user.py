from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("telegram_user_id", name="uq_users_telegram_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="partner", index=True)
    telegram_user_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    telegram_username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    preferred_language: Mapped[str] = mapped_column(String(10), default="en")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Dispatcher-only: the group their orders are pushed to. The dispatcher
    # never chooses a group; the admin sets it here.
    default_chat_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    chat_accesses: Mapped[list["PartnerChatAccess"]] = relationship(
        "PartnerChatAccess", cascade="all, delete-orphan", lazy="select"
    )
    product_accesses: Mapped[list["DispatcherProductAccess"]] = relationship(
        "DispatcherProductAccess", cascade="all, delete-orphan", lazy="select"
    )


class PartnerChatAccess(Base):
    __tablename__ = "partner_chat_access"
    __table_args__ = (UniqueConstraint("user_id", "chat_id", name="uq_partner_chat_access"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    chat_id: Mapped[str] = mapped_column(String(64), index=True)


class DispatcherProductAccess(Base):
    """Product whitelist for a dispatcher.

    Absence of a row means "cannot send this product"; the check is enforced
    server-side, the UI only hides what is not allowed.
    """

    __tablename__ = "dispatcher_product_access"
    __table_args__ = (
        UniqueConstraint("user_id", "product_id", name="uq_dispatcher_product_access"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )


class TelegramBindToken(Base):
    """One-time token that lets a logged-in dispatcher bind a Telegram account.

    The raw token only travels inside the t.me deep link; the database stores a
    SHA-256 digest, so a leaked dump cannot be replayed into someone's account.
    """

    __tablename__ = "telegram_bind_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_telegram_bind_token_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
