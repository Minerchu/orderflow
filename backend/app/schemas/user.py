from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    telegram_user_id: Optional[str] = None
    telegram_username: Optional[str] = None
    display_name: Optional[str] = None
    preferred_language: str
    is_active: bool
    created_at: datetime
    last_login_at: Optional[datetime] = None
    assigned_chat_ids: list[str] = []
    default_chat_id: Optional[str] = None
    allowed_product_ids: list[int] = []
    telegram_bound: bool = False

    model_config = ConfigDict(from_attributes=True)


class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "partner"
    telegram_user_id: Optional[str] = None
    telegram_username: Optional[str] = None
    preferred_language: str = "en"


class PartnerCreate(BaseModel):
    """Partner created by admin. They can log in and view their own orders."""

    username: str
    password: str
    telegram_user_id: Optional[str] = None
    telegram_username: Optional[str] = None
    preferred_language: str = "en"
