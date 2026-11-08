from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SystemConfig(Base):
    __tablename__ = "system_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_bot_token_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    telegram_default_chat_id: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    telegram_allowed_chat_ids: Mapped[str] = mapped_column(Text, default="", nullable=False)
    admin_telegram_user_ids: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # Public base URL used to register the Telegram callback webhook. Settable
    # from the settings UI so admins never have to edit .env and restart.
    public_base_url: Mapped[str] = mapped_column(String(256), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
