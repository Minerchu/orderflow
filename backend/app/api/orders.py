from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_admin
from app.db.models.order import Order, OrderEvent
from app.db.models.user import User
from app.constants import ROLE_ADMIN, ROLE_DISPATCHER, ROLE_WORKER
from app.db.session import get_db
from app.schemas.order import (
    OrderCreate,
    OrderEventOut,
    OrderOut,
    OrderUpdate,
)
from app.services import orders as order_service
from app.services.telegram_bot import (
    TelegramNotConfigured,
    get_default_chat_id,
    get_telegram_client,
)

router = APIRouter(prefix="/api/orders", tags=["orders"])


# ---------------------------------------------------------------------------
# Why a Telegram failure is reported as 4xx instead of 5xx
# ---------------------------------------------------------------------------
# Cloudflare REPLACES the body of any 5xx response with its own generic error
# page ("error code: 502"), so the admin only ever sees "failed" and never
# learns why. 4xx bodies pass through untouched, which lets the UI explain
# the actual reason. The failures listed here are content/config problems --
# a wrong chat id, a bot that lost admin rights, a rejected button payload --
# and the admin can act on them. Genuine infrastructure hiccups (network,
# timeout) keep the 5xx status.
_TG_CONTENT_ERRORS = frozenset({
    "telegram_bad_request",
    "telegram_copy_text_too_long",
    "telegram_message_too_long",
    "telegram_invalid_payload",
    "telegram_chat_not_found",
    "telegram_bot_not_admin",
    "telegram_bot_blocked",
    "telegram_send_forbidden",
    "telegram_rate_limited",
    "telegram_credentials_unavailable",
    "empty_order",
    "no_chat_id",
})


def _tg_http_status(error_code: str) -> int:
    """4xx for actionable Telegram problems, 5xx for infrastructure ones."""
    return 400 if error_code in _TG_CONTENT_ERRORS else 502


def _client(db: Session):
    """Build the Telegram client, turning the not-configured case into a 400."""
    try:
        return get_telegram_client(db)
    except TelegramNotConfigured as e:
        raise HTTPException(status_code=400, detail="telegram_not_configured") from e


def _serialize(db, order: Order) -> OrderOut:
    out = OrderOut.model_validate(order)
    # attach display names
    if order.created_by_user_id:
        u = db.get(User, order.created_by_user_id)
        out.created_by_username = u.username if u else None
    if order.accepted_by_user_id:
        u = db.get(User, order.accepted_by_user_id)
        out.accepted_by_username = u.username if u else None
    if order.completed_by_user_id:
        u = db.get(User, order.completed_by_user_id)
        out.completed_by_username = u.username if u else None
    return out


@router.get("", response_model=list[OrderOut])
def list_orders(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    order_status: Optional[str] = Query(default=None),
    currency: Optional[str] = Query(default=None),
    owner_id: Optional[int] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    if current_user.role == ROLE_WORKER:
        raise HTTPException(status_code=403, detail="worker_use_group_orders")
    q = select(Order)
    if current_user.role == ROLE_DISPATCHER:
        # Dispatchers see exactly their own orders.
        q = q.where(Order.order_owner_id == current_user.id)
    elif current_user.role != ROLE_ADMIN:
        q = q.where(
            (Order.order_owner_id == current_user.id)
            | (Order.accepted_by_user_id == current_user.id)
        )
    if owner_id is not None and current_user.role == ROLE_ADMIN:
        q = q.where(Order.order_owner_id == owner_id)
    if order_status:
        q = q.where(Order.order_status == order_status)
    if currency:
        q = q.where(Order.currency == currency)
    q = q.order_by(Order.created_at.desc())
    rows = db.execute(q.limit(page_size).offset((page - 1) * page_size)).scalars().all()
    return [_serialize(db, o) for o in rows]


@router.post("", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
def create_order(
    payload: OrderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Admins send any order; dispatchers send within their granted scope.

    Partners/workers are refused: they handle orders in the group, they do not
    create them.
    """
    if current_user.role not in (ROLE_ADMIN, ROLE_DISPATCHER):
        raise HTTPException(status_code=403, detail="not_allowed_to_create_orders")
    try:
        order = order_service.create_order(db, payload, current_user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _serialize(db, order)


@router.get("/{order_id}")
def get_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="order_not_found")
    if not order_service.partner_can_access(order, current_user):
        raise HTTPException(status_code=403, detail="forbidden")
    if current_user.role == ROLE_WORKER:
        from app.api.partner import _worker_order_out
        return _worker_order_out(db, order)
    return _serialize(db, order)


@router.patch("/{order_id}", response_model=OrderOut)
def update_order(
    order_id: int,
    payload: OrderUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="order_not_found")
    try:
        order = order_service.update_order(db, order, payload, current_user)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _serialize(db, order)


@router.post("/{order_id}/send", response_model=OrderOut)
def send_order(
    order_id: int,
    chat_id: Optional[str] = Query(default=None),
    force_new: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """推送订单到群组。

    默认行为是**原地同步**：把订单的当前状态重写到群里那条已有消息上，
    不产生新消息（群里不刷屏）。这正是后台"同步到群"按钮要的效果。

    ``force_new=true`` 时退化为"重新发一条新消息"，等价于 retry-send，
    用于原消息被删除、或确实需要重新推送一份的情形。
    """
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="order_not_found")

    if current_user.role == ROLE_DISPATCHER:
        if order.order_owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="forbidden")
        # The dispatcher never chooses a group: the admin configured it.
        chat_id = order_service.dispatcher_default_chat(db, current_user)
        if not chat_id:
            raise HTTPException(status_code=400, detail="dispatcher_no_chat")
    elif current_user.role != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="forbidden")

    # Already delivered and not forced -> edit in place instead of re-sending.
    if not force_new and order.telegram_chat_id and order.telegram_message_id:
        ok, reason = order_service.sync_order_to_telegram(db, order)
        db.refresh(order)
        if not ok and reason not in ("not_sent",):
            # Surface a real failure (bot blocked / message gone / network).
            code = reason or "telegram_send_failed"
            raise HTTPException(status_code=_tg_http_status(code), detail=code)
        return _serialize(db, order)

    # Priority: explicit request > order's own chat > system default group.
    target = chat_id or order.telegram_chat_id or get_default_chat_id(db)
    if not target:
        raise HTTPException(status_code=400, detail="no_chat_id")
    client = _client(db)
    ok, error_code = order_service.send_order_to_telegram(db, order, target, client)
    db.refresh(order)
    if not ok:
        # Return the specific reason (chat not found / not admin / network...)
        # so the UI can explain the failure instead of a generic error.
        code = error_code or "telegram_send_failed"
        raise HTTPException(status_code=_tg_http_status(code), detail=code)
    return _serialize(db, order)


@router.post("/{order_id}/retry-send", response_model=OrderOut)
def retry_send(
    order_id: int,
    chat_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """重新发送一条全新的群消息。

    与 ``/send`` 的区别：这里**总是**新发一条消息，会把订单的
    ``telegram_message_id`` 指向新消息，旧消息不再受管理。
    仅在原消息被删除或确实需要重新推送时使用。
    """
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="order_not_found")
    if current_user.role == ROLE_DISPATCHER:
        if order.order_owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="forbidden")
        chat_id = order_service.dispatcher_default_chat(db, current_user)
        if not chat_id:
            raise HTTPException(status_code=400, detail="dispatcher_no_chat")
    elif current_user.role != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="forbidden")
    target = chat_id or order.telegram_chat_id or get_default_chat_id(db)
    if not target:
        raise HTTPException(status_code=400, detail="no_chat_id")
    client = _client(db)
    ok, error_code = order_service.send_order_to_telegram(db, order, target, client)
    db.refresh(order)
    if not ok:
        code = error_code or "telegram_send_failed"
        raise HTTPException(status_code=_tg_http_status(code), detail=code)
    return _serialize(db, order)


@router.get("/{order_id}/events", response_model=list[OrderEventOut])
def order_events(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="order_not_found")
    if not order_service.partner_can_access(order, current_user):
        raise HTTPException(status_code=403, detail="forbidden")
    evs = db.execute(
        select(OrderEvent).where(OrderEvent.order_id == order_id)
        .order_by(OrderEvent.created_at)
    ).scalars().all()
    return [OrderEventOut.model_validate(e) for e in evs]
