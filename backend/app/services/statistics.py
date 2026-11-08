from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.constants import (
    CURRENCY_INR,
    CURRENCY_USD,
    FIN_STATUS_EXCLUDED,
    FIN_STATUS_RESERVED,
    FIN_STATUS_SETTLED,
    ORDER_STATUS_COMPLETED,
)
from app.db.models.order import Order
from app.schemas.settlement import (
    IneligibleOrder,
    PaymentCountRow,
    SettlementFilter,
    SettlementPreview,
)


def _apply_filters(query, filters: SettlementFilter):
    if filters.start_date:
        query = query.filter(Order.completed_at >= _dt_start(filters.start_date))
    if filters.end_date:
        query = query.filter(Order.completed_at <= _dt_end(filters.end_date))
    if filters.product:
        query = query.filter(Order.product_name_snapshot == filters.product)
    if filters.currency:
        query = query.filter(Order.currency == filters.currency)
    if filters.amount is not None:
        query = query.filter(Order.amount == filters.amount)
    if filters.partner:
        # partner snapshot is stored on settlement items; for live preview we
        # approximate via accepted_by -> user telegram_username is not a "partner"
        # label. We keep the filter but it only narrows when settlement items exist.
        pass
    if filters.order_status:
        query = query.filter(Order.order_status == filters.order_status)
    if filters.financial_status:
        query = query.filter(Order.financial_status == filters.financial_status)
    return query


def _dt_start(d: date):
    from datetime import datetime, timezone

    return datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=timezone.utc)


def _dt_end(d: date):
    from datetime import datetime, timezone

    return datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=timezone.utc)


def _currency_ok(order: Order) -> bool:
    return order.currency in (CURRENCY_INR, CURRENCY_USD)


def _dispatcher_status(order: Order) -> str:
    return order.dispatcher_settlement_status or "unsettled"


def _build_dispatcher_preview(db: Session, filters: SettlementFilter) -> SettlementPreview:
    """Preview one dispatcher's private ledger.

    Deliberately independent of ``financial_status``: an order that is already
    settled with the group can still be unsettled with its dispatcher (and
    vice versa). This is what makes the two ledgers non-interfering.
    """
    rows = _apply_filters(
        db.query(Order).filter(
            Order.order_status == ORDER_STATUS_COMPLETED,
            Order.order_owner_id == filters.dispatcher_user_id,
        ),
        filters,
    ).all()

    eligible: List[Order] = []
    ineligible: List[IneligibleOrder] = []
    already_settled = reserved = excluded = 0
    for o in rows:
        status = _dispatcher_status(o)
        if status == FIN_STATUS_SETTLED:
            already_settled += 1
            continue
        if status == FIN_STATUS_RESERVED:
            reserved += 1
            continue
        if status == FIN_STATUS_EXCLUDED:
            excluded += 1
            continue
        if o.amount is None:
            ineligible.append(_ineligible(o, "amount is empty/null"))
            continue
        if not _currency_ok(o):
            ineligible.append(_ineligible(o, "unsupported currency"))
            continue
        eligible.append(o)

    groups: dict = {}
    for o in eligible:
        key = (o.currency, o.amount)
        groups[key] = groups.get(key, 0) + 1

    payment_counts = [
        PaymentCountRow(currency=c, amount=a, quantity=q)
        for (c, a), q in sorted(groups.items(), key=lambda kv: (kv[0][0], float(kv[0][1] or 0)))
    ]
    return SettlementPreview(
        eligible_order_count=len(eligible),
        payment_counts=payment_counts,
        ineligible_orders=ineligible,
        already_settled_count=already_settled,
        reserved_count=reserved,
        excluded_count=excluded,
    )


def build_settlement_preview(db: Session, filters: SettlementFilter) -> SettlementPreview:
    """Build settlement preview following the strict counting rules.

    Eligible = completed + amount confirmed + currency INR/USD + amount not null
    + financial_status == unsettled (not reserved/settled/excluded).
    NEVER compute any currency total. Only count successful payment occurrences.
    """
    if filters.dispatcher_user_id:
        return _build_dispatcher_preview(db, filters)

    all_completed = _apply_filters(
        db.query(Order).filter(Order.order_status == ORDER_STATUS_COMPLETED),
        filters,
    ).all()

    eligible: List[Order] = []
    ineligible: List[IneligibleOrder] = []
    already_settled = 0
    reserved = 0
    excluded = 0

    for o in all_completed:
        if o.financial_status == FIN_STATUS_SETTLED:
            already_settled += 1
            continue
        if o.financial_status == FIN_STATUS_RESERVED:
            reserved += 1
            continue
        if o.financial_status == FIN_STATUS_EXCLUDED:
            excluded += 1
            continue
        # financial_status == unsettled here
        if o.amount is None:
            ineligible.append(_ineligible(o, "amount is empty/null"))
            continue
        if not o.amount_confirmed:
            ineligible.append(_ineligible(o, "amount not confirmed"))
            continue
        if not _currency_ok(o):
            ineligible.append(_ineligible(o, "unsupported currency"))
            continue
        eligible.append(o)

    # Group by currency + amount
    groups: dict = {}
    for o in eligible:
        key = (o.currency, o.amount)
        groups[key] = groups.get(key, 0) + 1

    payment_counts = [
        PaymentCountRow(currency=c, amount=a, quantity=q)
        for (c, a), q in sorted(groups.items(), key=lambda kv: (kv[0][0], float(kv[0][1] or 0)))
    ]

    return SettlementPreview(
        eligible_order_count=len(eligible),
        payment_counts=payment_counts,
        ineligible_orders=ineligible,
        already_settled_count=already_settled,
        reserved_count=reserved,
        excluded_count=excluded,
    )


def _ineligible(o: Order, reason: str) -> IneligibleOrder:
    return IneligibleOrder(
        order_id=o.id,
        order_number=o.order_number,
        currency=o.currency,
        amount=o.amount,
        order_status=o.order_status,
        financial_status=o.financial_status,
        reason=reason,
    )


def payment_counts_for_orders(orders: List[Order]) -> List[PaymentCountRow]:
    groups: dict = {}
    for o in orders:
        if o.amount is None or not o.amount_confirmed:
            continue
        if o.currency not in (CURRENCY_INR, CURRENCY_USD):
            continue
        key = (o.currency, o.amount)
        groups[key] = groups.get(key, 0) + 1
    return [
        PaymentCountRow(currency=c, amount=a, quantity=q)
        for (c, a), q in sorted(groups.items())
    ]
