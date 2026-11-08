from __future__ import annotations

import io
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import (
    ACTOR_ADMIN,
    CURRENCY_INR,
    CURRENCY_USD,
    FIN_STATUS_RESERVED,
    FIN_STATUS_SETTLED,
    FIN_STATUS_UNSETTLED,
    ORDER_STATUS_COMPLETED,
    SETTLEMENT_CANCELLED,
    SETTLEMENT_CONFIRMED,
    SETTLEMENT_DRAFT,
    SETTLEMENT_TYPE_DISPATCHER,
    SETTLEMENT_TYPE_GROUP,
    ROLE_DISPATCHER,
)
from app.db.models.audit import AuditLog
from app.db.models.order import Order
from app.db.models.settlement import SettlementBatch, SettlementItem
from app.db.models.user import User
from app.schemas.settlement import SettlementFilter


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _select_eligible(db: Session, filters: SettlementFilter, for_update: bool = False):
    # A completed order counts on its own: completing it in the group is the
    # confirmation. `amount_confirmed` stays in the schema for audit/history,
    # but it is no longer a second manual gate the admin must clear per order.
    #
    # Two independent ledgers:
    #   group      -> financial_status
    #   dispatcher -> dispatcher_settlement_status, scoped to one owner
    # Settling one must never reserve/close the other.
    q = db.query(Order).filter(
        Order.order_status == ORDER_STATUS_COMPLETED,
        Order.amount.isnot(None),
        Order.currency.in_([CURRENCY_INR, CURRENCY_USD]),
    )
    if filters.dispatcher_user_id:
        q = q.filter(
            Order.order_owner_id == filters.dispatcher_user_id,
            Order.dispatcher_settlement_status == FIN_STATUS_UNSETTLED,
        )
    else:
        q = q.filter(Order.financial_status == FIN_STATUS_UNSETTLED)
    if filters.start_date:
        q = q.filter(Order.completed_at >= _dt_start(filters.start_date))
    if filters.end_date:
        q = q.filter(Order.completed_at <= _dt_end(filters.end_date))
    if filters.product:
        q = q.filter(Order.product_name_snapshot == filters.product)
    if filters.currency:
        q = q.filter(Order.currency == filters.currency)
    if filters.amount is not None:
        q = q.filter(Order.amount == filters.amount)
    if filters.order_status:
        q = q.filter(Order.order_status == filters.order_status)
    if for_update:
        q = q.with_for_update()
    return q


def _dt_start(d):
    return datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=timezone.utc)


def _dt_end(d):
    return datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=timezone.utc)


def create_settlement_batch(db: Session, filters: SettlementFilter,
                            admin: User) -> SettlementBatch:
    """Create a DRAFT settlement batch. Atomically reserve eligible orders."""
    is_dispatcher = (
        filters.settlement_type == SETTLEMENT_TYPE_DISPATCHER
        or filters.dispatcher_user_id is not None
    )
    if is_dispatcher:
        if filters.dispatcher_user_id is None:
            raise ValueError("dispatcher_required")
        dispatcher = db.get(User, filters.dispatcher_user_id)
        if dispatcher is None or dispatcher.role != ROLE_DISPATCHER:
            raise ValueError("dispatcher_not_found")
    eligible = _select_eligible(db, filters, for_update=True).all()

    batch = SettlementBatch(
        settlement_id=f"SET-{uuid.uuid4().hex[:8].upper()}",
        status=SETTLEMENT_DRAFT,
        settlement_type=SETTLEMENT_TYPE_DISPATCHER if is_dispatcher else SETTLEMENT_TYPE_GROUP,
        dispatcher_user_id=filters.dispatcher_user_id if is_dispatcher else None,
        filter_conditions=filters.model_dump(exclude_none=True),
        order_count=len(eligible),
        created_by_user_id=admin.id,
        start_date=filters.start_date,
        end_date=filters.end_date,
    )
    db.add(batch)
    db.flush()

    for o in eligible:
        if is_dispatcher:
            o.dispatcher_settlement_status = FIN_STATUS_RESERVED
        else:
            o.financial_status = FIN_STATUS_RESERVED
        item = SettlementItem(
            settlement_batch_id=batch.id,
            order_id=o.id,
            amount_snapshot=o.amount,
            currency_snapshot=o.currency,
            product_snapshot=o.product_name_snapshot,
            partner_snapshot=None,
            completed_at_snapshot=o.completed_at,
        )
        db.add(item)
        db.add(AuditLog(actor_type=ACTOR_ADMIN, actor_user_id=admin.id,
                        action="settlement_reserve", entity_type="order",
                        entity_id=str(o.id),
                        detail=f"batch={batch.settlement_id},"
                               f"ledger={batch.settlement_type}"))

    db.commit()
    db.refresh(batch)
    return batch


def confirm_settlement(db: Session, settlement_id: str, admin: User) -> SettlementBatch:
    batch = db.execute(
        select(SettlementBatch).where(SettlementBatch.settlement_id == settlement_id)
    ).scalar_one_or_none()
    if batch is None:
        raise ValueError("settlement_not_found")
    if batch.status != SETTLEMENT_DRAFT:
        raise ValueError("settlement_not_draft")

    items = db.execute(
        select(SettlementItem).where(SettlementItem.settlement_batch_id == batch.id)
    ).scalars().all()

    # Re-verify every order under lock. Reject if any became invalid.
    order_ids = [i.order_id for i in items]
    orders = db.execute(
        select(Order).where(Order.id.in_(order_ids)).with_for_update()
    ).scalars().all()
    by_id = {o.id: o for o in orders}

    for item in items:
        o = by_id.get(item.order_id)
        if o is None:
            raise ValueError(f"order_missing:{item.order_id}")
        if o.order_status != ORDER_STATUS_COMPLETED:
            raise ValueError(f"order_not_completed:{item.order_id}")
        if o.amount is None:
            raise ValueError(f"amount_invalid:{item.order_id}")
        if o.currency not in (CURRENCY_INR, CURRENCY_USD):
            raise ValueError(f"currency_invalid:{item.order_id}")
        if batch.settlement_type == SETTLEMENT_TYPE_DISPATCHER:
            if o.dispatcher_settlement_status != FIN_STATUS_RESERVED:
                raise ValueError(f"order_not_reserved:{item.order_id}")
        elif o.financial_status != FIN_STATUS_RESERVED:
            raise ValueError(f"order_not_reserved:{item.order_id}")

    for item in items:
        o = by_id[item.order_id]
        if batch.settlement_type == SETTLEMENT_TYPE_DISPATCHER:
            # Only the private ledger moves. `financial_status` and `cycle_id`
            # stay untouched so the group settlement still sees this order and
            # the group's numbering does not restart.
            o.dispatcher_settlement_status = FIN_STATUS_SETTLED
        else:
            o.financial_status = FIN_STATUS_SETTLED
            # Stamp the cycle so the next batch's "No.1 / No.2 ..." restarts.
            o.cycle_id = batch.id

    batch.status = SETTLEMENT_CONFIRMED
    batch.confirmed_by_user_id = admin.id
    batch.confirmed_at = _now()
    db.add(AuditLog(actor_type=ACTOR_ADMIN, actor_user_id=admin.id,
                    action="settlement_confirm", entity_type="settlement",
                    entity_id=batch.settlement_id,
                    detail=f"orders={len(items)}"))
    db.commit()
    db.refresh(batch)
    return batch


def cancel_settlement(db: Session, settlement_id: str, admin: User) -> SettlementBatch:
    batch = db.execute(
        select(SettlementBatch).where(SettlementBatch.settlement_id == settlement_id)
    ).scalar_one_or_none()
    if batch is None:
        raise ValueError("settlement_not_found")
    if batch.status != SETTLEMENT_DRAFT:
        raise ValueError("only_draft_can_be_cancelled")

    items = db.execute(
        select(SettlementItem).where(SettlementItem.settlement_batch_id == batch.id)
    ).scalars().all()
    order_ids = [i.order_id for i in items]
    if order_ids:
        orders = db.execute(
            select(Order).where(Order.id.in_(order_ids)).with_for_update()
        ).scalars().all()
        for o in orders:
            if batch.settlement_type == SETTLEMENT_TYPE_DISPATCHER:
                if o.dispatcher_settlement_status == FIN_STATUS_RESERVED:
                    o.dispatcher_settlement_status = FIN_STATUS_UNSETTLED
            elif o.financial_status == FIN_STATUS_RESERVED:
                o.financial_status = FIN_STATUS_UNSETTLED
    # Release reserved; remove items.
    for item in items:
        db.delete(item)
    batch.status = SETTLEMENT_CANCELLED
    db.add(AuditLog(actor_type=ACTOR_ADMIN, actor_user_id=admin.id,
                    action="settlement_cancel", entity_type="settlement",
                    entity_id=batch.settlement_id, detail="released reserved"))
    db.commit()
    db.refresh(batch)
    return batch


def get_settlement_export_rows(batch: SettlementBatch, db: Session):
    """Return payment-count summary + order details + metadata for Excel."""
    items = db.execute(
        select(SettlementItem).where(SettlementItem.settlement_batch_id == batch.id)
    ).scalars().all()

    # Summary grouped by currency + amount (snapshot values)
    groups: dict = {}
    for it in items:
        key = (it.currency_snapshot, it.amount_snapshot)
        groups[key] = groups.get(key, 0) + 1
    summary = [
        {"Currency": c, "Amount": (a if a is not None else ""), "Quantity": q}
        for (c, a), q in sorted(groups.items())
    ]

    # Order details
    order_ids = [i.order_id for i in items]
    orders = db.execute(
        select(Order).where(Order.id.in_(order_ids))
    ).scalars().all() if order_ids else []
    by_id = {o.id: o for o in orders}
    details = []
    for it in items:
        o = by_id.get(it.order_id)
        details.append({
            "Order ID": o.order_number if o else "",
            "Product": it.product_snapshot or "",
            "Amount": it.amount_snapshot if it.amount_snapshot is not None else "",
            "Currency": it.currency_snapshot,
            "Order Status": o.order_status if o else "",
            "Settlement Status": (
                o.dispatcher_settlement_status
                if (o and batch.settlement_type == SETTLEMENT_TYPE_DISPATCHER)
                else (o.financial_status if o else "")
            ),
            "Ledger": batch.settlement_type,
            "Dispatcher ID": batch.dispatcher_user_id or "",
            "Created At": o.created_at.isoformat() if o and o.created_at else "",
            "Completed At": o.completed_at.isoformat() if o and o.completed_at else "",
            "Accepted By": o.accepted_by_user_id if o else "",
            "Completed By": o.completed_by_user_id if o else "",
            "Settlement ID": batch.settlement_id,
        })

    metadata = [{
        "Settlement ID": batch.settlement_id,
        "Created By": batch.created_by_user_id,
        "Created At": batch.created_at.isoformat() if batch.created_at else "",
        "Confirmed By": batch.confirmed_by_user_id,
        "Confirmed At": batch.confirmed_at.isoformat() if batch.confirmed_at else "",
        "Start Date": batch.start_date.isoformat() if batch.start_date else "",
        "End Date": batch.end_date.isoformat() if batch.end_date else "",
        "Number of Orders": batch.order_count,
        "Batch Status": batch.status,
        "Settlement Type": batch.settlement_type,
        "Dispatcher ID": batch.dispatcher_user_id or "",
    }]
    return summary, details, metadata
