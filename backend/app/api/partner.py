from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.constants import (
    FIN_STATUS_SETTLED,
    FIN_STATUS_UNSETTLED,
    ORDER_STATUS_COMPLETED,
    ORDER_STATUS_FAILED,
    ORDER_STATUS_PROCESSING,
    ROLE_PARTNER,
    ROLE_WORKER,
    SETTLEMENT_CONFIRMED,
)
from app.core.deps import get_current_user
from app.db.models.order import Order
from app.db.models.user import User
from app.db.models.payment_check import PaymentCountCheck
from app.db.models.audit import AuditLog
from app.db.models.settlement import SettlementBatch, SettlementItem
from app.db.session import get_db
from app.schemas.order import OrderOut
from app.schemas.settlement import PaymentCountRow, SettlementOut
from app.services import orders as order_service
from app.services.statistics import payment_counts_for_orders

router = APIRouter(prefix="/api/partner", tags=["partner"])


def _ensure_partner(user: User) -> User:
    if user.role not in (ROLE_PARTNER, ROLE_WORKER):
        raise HTTPException(status_code=403, detail="partner_only")
    return user


def _my_orders(db: Session, user: User, chat_id: str | None = None,
               order_status: str | None = None, financial_status: str | None = None):
    assigned = [access.chat_id for access in user.chat_accesses]
    if user.role == ROLE_WORKER:
        q = select(Order).where(Order.telegram_chat_id.in_(assigned or ["__none__"]))
    else:
        clauses = [Order.order_owner_id == user.id, Order.accepted_by_user_id == user.id]
        if assigned:
            clauses.append(Order.telegram_chat_id.in_(assigned))
        q = select(Order).where(or_(*clauses))
    if chat_id:
        if chat_id not in assigned and user.role == ROLE_WORKER:
            return []
        q = q.where(Order.telegram_chat_id == chat_id)
    if order_status:
        q = q.where(Order.order_status == order_status)
    if financial_status:
        q = q.where(Order.financial_status == financial_status)
    return db.execute(q.order_by(Order.created_at.desc(), Order.id.desc())).scalars().all()


def _worker_order_out(db: Session, order: Order):
    accepted = db.get(User, order.accepted_by_user_id) if order.accepted_by_user_id else None
    completed = db.get(User, order.completed_by_user_id) if order.completed_by_user_id else None
    return {
        "id": order.id, "order_number": order.order_number,
        "product_name_snapshot": order.product_name_snapshot,
        "amount": order.amount, "currency": order.currency,
        "order_status": order.order_status, "financial_status": order.financial_status,
        "telegram_chat_id": order.telegram_chat_id,
        "created_at": order.created_at, "updated_at": order.updated_at,
        "completed_at": order.completed_at, "amount_confirmed": order.amount_confirmed,
        "accepted_by_username": accepted.username if accepted else None,
        "completed_by_username": completed.username if completed else None,
        "attachments": [],
    }


@router.get("/groups")
def my_groups(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _ensure_partner(user)
    counts: dict[str, int] = {}
    for order in _my_orders(db, user):
        if order.telegram_chat_id:
            counts[order.telegram_chat_id] = counts.get(order.telegram_chat_id, 0) + 1
    chats = {access.chat_id for access in user.chat_accesses} | set(counts)
    return [{"chat_id": chat_id, "order_count": counts.get(chat_id, 0)}
            for chat_id in sorted(chats)]


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), user: User = Depends(get_current_user),
              chat_id: str | None = Query(default=None)):
    _ensure_partner(user)
    orders = _my_orders(db, user, chat_id=chat_id)
    completed = [o for o in orders if o.order_status == ORDER_STATUS_COMPLETED]
    return {
        "completed_orders": len(completed),
        "unsettled": len([o for o in orders if o.financial_status == FIN_STATUS_UNSETTLED]),
        "settled": len([o for o in orders if o.financial_status == FIN_STATUS_SETTLED]),
        "processing": len([o for o in orders if o.order_status == ORDER_STATUS_PROCESSING]),
        "failed": len([o for o in orders if o.order_status == ORDER_STATUS_FAILED]),
        "payment_counts": [
            {"currency": r.currency, "amount": r.amount, "quantity": r.quantity}
            for r in payment_counts_for_orders(completed)
        ],
    }


@router.get("/orders")
def my_orders(db: Session = Depends(get_db), user: User = Depends(get_current_user),
              chat_id: str | None = Query(default=None),
              order_status: str | None = Query(default=None),
              financial_status: str | None = Query(default=None)):
    _ensure_partner(user)
    orders = _my_orders(db, user, chat_id, order_status, financial_status)
    if user.role == ROLE_WORKER:
        return [_worker_order_out(db, order) for order in orders]
    return [OrderOut.model_validate(order) for order in orders]


@router.get("/settlement-history")
def settlement_history(db: Session = Depends(get_db), user: User = Depends(get_current_user),
                       chat_id: str | None = Query(default=None)):
    _ensure_partner(user)
    authorized_ids = [order.id for order in _my_orders(db, user, chat_id=chat_id)]
    if not authorized_ids:
        return []
    rows = db.execute(
        select(SettlementBatch, SettlementItem, Order)
        .join(SettlementItem, SettlementItem.settlement_batch_id == SettlementBatch.id)
        .join(Order, Order.id == SettlementItem.order_id)
        .where(SettlementBatch.status == SETTLEMENT_CONFIRMED, Order.id.in_(authorized_ids))
        .order_by(SettlementBatch.confirmed_at.desc(), SettlementBatch.id.desc(), Order.id.desc())
    ).all()
    batches: dict[int, dict] = {}
    for batch, item, order in rows:
        row = batches.setdefault(batch.id, {
            "id": batch.id,
            "settlement_id": batch.settlement_id,
            "settled_at": batch.confirmed_at or batch.created_at,
            "order_count": 0,
        })
        row["order_count"] += 1
    return list(batches.values())


@router.get("/settlement-history/{batch_id}")
def settlement_history_detail(batch_id: int, db: Session = Depends(get_db),
                              user: User = Depends(get_current_user),
                              chat_id: str | None = Query(default=None)):
    _ensure_partner(user)
    batch = db.get(SettlementBatch, batch_id)
    if batch is None or batch.status != SETTLEMENT_CONFIRMED:
        raise HTTPException(status_code=404, detail="settlement_not_found")
    authorized_ids = [order.id for order in _my_orders(db, user, chat_id=chat_id)]
    rows = db.execute(
        select(SettlementItem, Order)
        .join(Order, Order.id == SettlementItem.order_id)
        .where(SettlementItem.settlement_batch_id == batch_id, Order.id.in_(authorized_ids or [0]))
        .order_by(Order.created_at.desc(), Order.id.desc())
    ).all()
    if not rows:
        raise HTTPException(status_code=404, detail="settlement_not_found")
    orders = []
    for item, order in rows:
        row = _worker_order_out(db, order) if user.role == ROLE_WORKER else OrderOut.model_validate(order).model_dump()
        row.update({
            "amount": item.amount_snapshot,
            "currency": item.currency_snapshot,
            "product_name_snapshot": item.product_snapshot or order.product_name_snapshot,
            "completed_at": item.completed_at_snapshot or order.completed_at,
        })
        orders.append(row)
    return {
        "settlement_id": batch.settlement_id,
        "settled_at": batch.confirmed_at or batch.created_at,
        "order_count": len(orders),
        "orders": orders,
    }


@router.get("/orders/{order_id}")
def my_order_detail(order_id: int, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    _ensure_partner(user)
    order = db.get(Order, order_id)
    if order is None or not order_service.partner_can_access(order, user):
        raise HTTPException(status_code=404, detail="order_not_found")
    if user.role == ROLE_WORKER:
        return _worker_order_out(db, order)
    return OrderOut.model_validate(order)


@router.get("/payment-counts")
def payment_counts(db: Session = Depends(get_db), user: User = Depends(get_current_user),
                   chat_id: str | None = Query(default=None)):
    _ensure_partner(user)
    orders = _my_orders(db, user, chat_id=chat_id)
    completed = [o for o in orders if o.order_status == ORDER_STATUS_COMPLETED]
    result = []
    for row in payment_counts_for_orders(completed):
        check = None
        if chat_id and row.amount is not None:
            check = db.execute(select(PaymentCountCheck).where(
                PaymentCountCheck.user_id == user.id,
                PaymentCountCheck.chat_id == chat_id,
                PaymentCountCheck.currency == row.currency,
                PaymentCountCheck.amount == row.amount,
            )).scalar_one_or_none()
        matching = [o for o in completed if o.currency == row.currency and o.amount == row.amount
                    and (not chat_id or o.telegram_chat_id == chat_id)]
        signature = hashlib.sha256(",".join(str(o.id) for o in sorted(matching, key=lambda x: x.id)).encode()).hexdigest()
        result.append({
            "currency": row.currency, "amount": row.amount, "quantity": row.quantity,
            "checked": bool(check and check.order_signature == signature),
            "checked_at": check.checked_at if check and check.order_signature == signature else None,
        })
    return result


class PaymentCountCheckReq(BaseModel):
    chat_id: str
    currency: str
    amount: Decimal


@router.post("/payment-counts/check")
def confirm_payment_count(payload: PaymentCountCheckReq, db: Session = Depends(get_db),
                          user: User = Depends(get_current_user)):
    _ensure_partner(user)
    if payload.currency not in ("INR", "USD") or payload.chat_id not in {
        access.chat_id for access in user.chat_accesses
    }:
        raise HTTPException(status_code=403, detail="forbidden")
    orders = db.execute(select(Order).where(
        Order.telegram_chat_id == payload.chat_id,
        Order.order_status == ORDER_STATUS_COMPLETED,
        Order.currency == payload.currency,
        Order.amount == payload.amount,
    ).order_by(Order.id)).scalars().all()
    if not orders:
        raise HTTPException(status_code=404, detail="payment_count_not_found")
    signature = hashlib.sha256(",".join(str(o.id) for o in orders).encode()).hexdigest()
    check = db.execute(select(PaymentCountCheck).where(
        PaymentCountCheck.user_id == user.id,
        PaymentCountCheck.chat_id == payload.chat_id,
        PaymentCountCheck.currency == payload.currency,
        PaymentCountCheck.amount == payload.amount,
    )).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if check is None:
        check = PaymentCountCheck(user_id=user.id, chat_id=payload.chat_id,
                                  currency=payload.currency, amount=payload.amount,
                                  order_signature=signature, checked_at=now)
        db.add(check)
    else:
        check.order_signature = signature
        check.checked_at = now
    db.add(AuditLog(actor_type="partner", actor_user_id=user.id,
                    action="payment_count_check", entity_type="telegram_group",
                    entity_id=payload.chat_id,
                    detail=f"{payload.currency} {payload.amount} x {len(orders)}"))
    db.commit()
    return {"checked": True, "checked_at": now, "quantity": len(orders)}


@router.get("/settlements")
def my_settlements(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _ensure_partner(user)
    if user.role == ROLE_WORKER:
        return []
    # Partner sees settlement batches that include their orders.
    from app.db.models.settlement import SettlementBatch, SettlementItem

    items = db.execute(
        select(SettlementItem).where(
            SettlementItem.order_id.in_([o.id for o in _my_orders(db, user)] or [0])
        )
    ).scalars().all()
    batch_ids = {i.settlement_batch_id for i in items}
    batches = db.execute(
        select(SettlementBatch).where(SettlementBatch.id.in_(batch_ids or [0]))
    ).scalars().all()
    return [SettlementOut.model_validate(b) for b in batches]
