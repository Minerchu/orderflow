from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Product(Base):
    """A product *type*: nothing but a name, plus an on/off switch.

    Deliberately minimal. Earlier versions carried ``code``,
    ``default_currency``, ``default_login_method`` and four rule flags
    (require_amount / require_email / require_password / allow_screenshot).
    None of those were ever enforced, and the admin only ever wanted a list of
    names to pick from when creating an order, so they are gone.
    """

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )