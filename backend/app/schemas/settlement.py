from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class SettlementFilter(BaseModel):
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    product: Optional[str] = None
    currency: Optional[str] = None
    amount: Optional[Decimal] = None
    partner: Optional[str] = None
    order_status: Optional[str] = None
    financial_status: Optional[str] = None
    # Dispatcher ledger filters. When dispatcher_user_id is set the batch
    # settles that person's private ledger and never touches financial_status.
    settlement_type: Optional[str] = None
    dispatcher_user_id: Optional[int] = None


class SettlementPreviewReq(SettlementFilter):
    pass


class PaymentCountRow(BaseModel):
    currency: str
    amount: Optional[Decimal] = None
    quantity: int


class IneligibleOrder(BaseModel):
    order_id: int
    order_number: str
    currency: str
    amount: Optional[Decimal] = None
    order_status: str
    financial_status: str
    reason: str


class SettlementPreview(BaseModel):
    eligible_order_count: int
    payment_counts: List[PaymentCountRow]
    ineligible_orders: List[IneligibleOrder]
    already_settled_count: int
    reserved_count: int
    excluded_count: int


class SettlementCreate(SettlementFilter):
    note: Optional[str] = None


class SettlementOut(BaseModel):
    id: int
    settlement_id: str
    status: str
    settlement_type: str = "group"
    dispatcher_user_id: Optional[int] = None
    order_count: int
    filter_conditions: dict
    created_by_user_id: Optional[int] = None
    confirmed_by_user_id: Optional[int] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    note: Optional[str] = None
    created_at: datetime
    confirmed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
