from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict


class OrderCreate(BaseModel):
    product_id: Optional[int] = None
    order_owner_id: Optional[int] = None
    product_name: Optional[str] = None
    amount: Optional[Decimal] = None
    currency: str = "INR"
    email: Optional[str] = None
    password: Optional[str] = None
    login_method: Optional[str] = None
    account: Optional[str] = None
    account_info: Optional[str] = None
    note: Optional[str] = None


class OrderUpdate(BaseModel):
    product_id: Optional[int] = None
    product_name: Optional[str] = None
    amount: Optional[Decimal] = None
    currency: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    login_method: Optional[str] = None
    account: Optional[str] = None
    account_info: Optional[str] = None
    note: Optional[str] = None
    # admin-only workflow controls
    order_status: Optional[str] = None
    failure_reason: Optional[str] = None
    # admin-only financial controls
    amount_confirmed: Optional[bool] = None
    exclude_from_settlement: Optional[bool] = None
    financial_status: Optional[str] = None


class AttachmentOut(BaseModel):
    id: int
    order_id: int
    original_filename: Optional[str] = None
    mime_type: Optional[str] = None
    file_size: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OrderEventOut(BaseModel):
    id: int
    order_id: int
    event_type: str
    from_status: Optional[str] = None
    to_status: Optional[str] = None
    actor_user_id: Optional[int] = None
    telegram_user_id: Optional[str] = None
    telegram_username: Optional[str] = None
    note: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OrderOut(BaseModel):
    id: int
    order_number: str
    product_id: Optional[int] = None
    product_name_snapshot: Optional[str] = None
    amount: Optional[Decimal] = None
    currency: str
    email: Optional[str] = None
    login_method: Optional[str] = None
    account: Optional[str] = None
    account_info: Optional[str] = None
    note: Optional[str] = None
    order_status: str
    financial_status: str
    dispatcher_settlement_status: str = "unsettled"
    created_by_user_id: Optional[int] = None
    order_owner_id: Optional[int] = None
    accepted_by_user_id: Optional[int] = None
    completed_by_user_id: Optional[int] = None
    failed_by_user_id: Optional[int] = None
    closed_by_user_id: Optional[int] = None
    telegram_chat_id: Optional[str] = None
    telegram_message_id: Optional[str] = None
    telegram_message_is_media: bool = False
    telegram_send_status: Optional[str] = None
    telegram_sent_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    accepted_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    failure_reason: Optional[str] = None
    failure_note: Optional[str] = None
    amount_confirmed: bool
    amount_confirmed_by: Optional[int] = None
    amount_confirmed_at: Optional[datetime] = None
    attachments: list[AttachmentOut] = []
    accepted_by_username: Optional[str] = None
    completed_by_username: Optional[str] = None
    created_by_username: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
