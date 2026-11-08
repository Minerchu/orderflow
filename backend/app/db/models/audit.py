from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_action", "action"), Index("ix_audit_created", "created_at"))

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    actor_type: Mapped[str] = mapped_column(String(20), default="system", index=True)
    action: Mapped[str] = mapped_column(String(60))
    entity_type: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    entity_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    __table_args__ = (Index("ix_login_attempts_username", "username", "attempt_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64))
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
