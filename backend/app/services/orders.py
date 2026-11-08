from __future__ import annotations

import secrets
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import (
    ACTOR_ADMIN,
    FAIL_OTHER,
    ORDER_STATUS_CLOSED,
    ORDER_STATUS_COMPLETED,
    ORDER_STATUS_DRAFT,
    ORDER_STATUS_FAILED,
    ORDER_STATUS_PENDING,
    ORDER_STATUS_PROCESSING,
    ACTOR_DISPATCHER,
    ROLE_ADMIN,
    ROLE_DISPATCHER,
    ROLE_WORKER,
    TG_SEND_FAILED,
    TG_SEND_SENT,
    FIN_STATUS_EXCLUDED,
    FIN_STATUS_UNSETTLED,
    LOGIN_METHODS,
)
from app.core.security import encrypt_secret, hash_password
from app.db.models.audit import AuditLog
from app.db.models.order import Order, OrderEvent
from app.db.models.product import Product
from app.db.models.telegram import TelegramOutbox
from app.db.models.user import DispatcherProductAccess, User
from app.schemas.order import OrderCreate, OrderUpdate


def _now() -> datetime:
    return datetime.now(timezone.utc)


def generate_order_number(order_id: int, created_at: datetime) -> str:
    """Human-readable order number: creation date plus the stable DB sequence."""
    return f"{created_at:%Y%m%d}-{order_id:06d}"


def current_cycle_id(db: Session):
    """The newest confirmed settlement batch, used to scope sequence numbers.

    ``None`` means "the original cycle" -- orders created before the first
    settlement keeps its original numbering.
    """
    from app.constants import SETTLEMENT_CONFIRMED
    from app.db.models.settlement import SettlementBatch

    return db.execute(
        select(SettlementBatch.id)
        .where(SettlementBatch.status == SETTLEMENT_CONFIRMED)
        .order_by(SettlementBatch.id.desc())
        .limit(1)
    ).scalar()


def dispatcher_allowed_product_ids(db: Session, user: User) -> set[int]:
    """Product ids this dispatcher may send (empty set for other roles)."""
    if user.role != ROLE_DISPATCHER:
        return set()
    rows = db.execute(
        select(DispatcherProductAccess.product_id).where(
            DispatcherProductAccess.user_id == user.id
        )
    ).scalars().all()
    return {int(r) for r in rows}


def dispatcher_default_chat(db: Session, user: User) -> Optional[str]:
    """The group a dispatcher's orders go to -- never chosen by the dispatcher.

    Falls back to the single authorized group when the admin forgot to set an
    explicit default, and finally to the system default group.
    """
    if user.default_chat_id:
        return user.default_chat_id
    chats = [a.chat_id for a in user.chat_accesses]
    if len(chats) == 1:
        return chats[0]
    from app.services.telegram_bot import get_default_chat_id

    return get_default_chat_id(db)


def create_order(db: Session, payload: OrderCreate, admin: User) -> Order:
    if payload.currency not in ("INR", "USD"):
        raise ValueError("unsupported_currency")
    if payload.login_method and payload.login_method not in LOGIN_METHODS:
        raise ValueError("invalid_login_method")
    # Amount is mandatory for both admin and dispatcher: settlement batches are
    # built from it, and an order without a price cannot be reconciled.
    if payload.amount is None:
        raise ValueError("amount_required")
    if payload.amount <= 0:
        raise ValueError("amount_invalid")

    # Selecting a product type fills in its name so the group message shows
    # something useful. An explicit name wins, and choosing no type is fine.
    product_name = (payload.product_name or "").strip() or None
    product_id = payload.product_id

    is_dispatcher = admin.role == ROLE_DISPATCHER
    owner_id = payload.order_owner_id
    if is_dispatcher:
        # A dispatcher acts like the admin but only within the granted scope:
        # the order is always theirs, and the product must be whitelisted.
        owner_id = admin.id
        if product_id is None:
            raise ValueError("product_required_for_dispatcher")
        allowed = dispatcher_allowed_product_ids(db, admin)
        if int(product_id) not in allowed:
            raise ValueError("product_not_allowed")

    if product_id is not None:
        product = db.get(Product, product_id)
        if product is None:
            raise ValueError("product_not_found")
        if not product.is_active:
            raise ValueError("product_inactive")
        product_name = product_name or product.name

    order = Order(
        # Use a unique temporary value for the first insert, then replace it
        # with a readable date + numeric ID once the database assigns the ID.
        order_number="TMP-" + secrets.token_hex(12).upper(),
        product_id=product_id,
        order_owner_id=owner_id,
        product_name_snapshot=product_name,
        amount=payload.amount,
        currency=payload.currency,
        email=payload.email,
        login_method=payload.login_method,
        account=payload.account,
        account_info=payload.account_info,
        note=payload.note,
        order_status=ORDER_STATUS_DRAFT,
        financial_status=FIN_STATUS_UNSETTLED,
        created_by_user_id=admin.id,
        # Orders created after a settlement belong to the new cycle, so their
        # numbering starts from No.1 again.
        cycle_id=current_cycle_id(db),
    )
    if payload.password:
        order.password_encrypted = encrypt_secret(payload.password)
    db.add(order)
    db.flush()
    order.order_number = generate_order_number(order.id, order.created_at)
    db.flush()
    db.add(OrderEvent(order_id=order.id, event_type="create",
                      to_status=ORDER_STATUS_DRAFT, actor_user_id=admin.id))
    db.add(AuditLog(
        actor_type=ACTOR_DISPATCHER if is_dispatcher else ACTOR_ADMIN,
        actor_user_id=admin.id,
        action="order_create", entity_type="order",
        entity_id=order.order_number,
    ))
    db.commit()
    db.refresh(order)
    return order


def send_order_to_telegram(db: Session, order: Order, chat_id: str, client) -> tuple[bool, str]:
    """Send to Telegram. Returns (ok, error_code).

    ``error_code`` is a stable diagnostic code, never a raw Telegram response,
    so the UI can tell the admin what actually went wrong.
    """
    from app.services.telegram_bot import TelegramSendError, send_order_to_chat

    order.telegram_chat_id = chat_id
    try:
        result = send_order_to_chat(order, client, chat_id, db)
        msg_id = result.message_id
        if not msg_id:
            raise TelegramSendError("telegram_invalid_response")
        order.telegram_message_id = msg_id
        # Remember whether the anchor is a photo so later edits use
        # editMessageCaption instead of editMessageText.
        order.telegram_message_is_media = bool(result.is_media)
        order.order_status = ORDER_STATUS_PENDING
        order.telegram_send_status = TG_SEND_SENT
        order.telegram_sent_at = _now()
        db.add(OrderEvent(order_id=order.id, event_type="send",
                          from_status=ORDER_STATUS_DRAFT, to_status=ORDER_STATUS_PENDING))
        db.add(TelegramOutbox(order_id=order.id, chat_id=chat_id,
                              message_type="order", payload="", status=TG_SEND_SENT,
                              telegram_message_id=msg_id, sent_at=_now()))
        db.commit()
        return True, ""
    except Exception as e:
        # Preserve the specific reason so the admin sees an actionable message.
        error_code = str(e) if isinstance(e, TelegramSendError) else "telegram_send_failed"
        db.rollback()
        # NOTE: deliberately NOT re-pointing order.telegram_chat_id here. A
        # failed send (wrong chat id, bot not in the group, ...) used to
        # overwrite the binding with the chat that failed, which permanently
        # broke the order: every later button tap in the real group was
        # rejected with "access denied" because the stored chat no longer
        # matched. The binding must only ever be written by a successful send.
        order.telegram_send_status = TG_SEND_FAILED
        db.add(TelegramOutbox(order_id=order.id, chat_id=chat_id,
                              message_type="order", payload="", status=TG_SEND_FAILED,
                              last_error=error_code))
        db.commit()
        return False, error_code


def sync_order_to_telegram(db: Session, order: Order) -> tuple[bool, str]:
    """Push the order's CURRENT state onto its existing group message.

    This is the single entry point used after any admin-side change so the
    group card never goes stale. Before this existed the admin had to remember
    to press "重新发送到群" after every edit, and forgetting meant the group saw
    the old state.

    Returns (ok, reason). Never raises: syncing is best-effort and must not roll
    back the database change that already succeeded.
    """
    from app.services.telegram_bot import (
        TelegramNotConfigured,
        TelegramSendError,
        _refresh_group_message,
        get_telegram_client,
    )

    if not order.telegram_chat_id or not order.telegram_message_id:
        return False, "not_sent"
    try:
        client = get_telegram_client(db)
    except TelegramNotConfigured:
        return False, "telegram_not_configured"
    try:
        ok = _refresh_group_message(db, order, client)
        return (True, "") if ok else (False, "edit_failed")
    except TelegramSendError as e:
        return False, str(e)
    except Exception:
        return False, "telegram_send_failed"


def _apply_status_override(db: Session, order: Order, new_status: str,
                           payload: OrderUpdate, user: User) -> None:
    """Move an order to a new status on the admin's authority.

    Each transition clears the fields belonging to the state being left, so a
    reopened order does not keep a stale "failed by" / "completed at", and the
    settlement flags stay coherent.
    """
    from_st = order.order_status
    now = _now()

    if new_status == ORDER_STATUS_FAILED:
        order.failure_reason = payload.failure_reason or FAIL_OTHER
        order.failed_by_user_id = user.id
        order.failed_at = now
        # A voided order must not settle.
        order.amount_confirmed = False
        order.amount_confirmed_by = None
        order.amount_confirmed_at = None
        order.completed_by_user_id = None
        order.completed_at = None

    elif new_status == ORDER_STATUS_COMPLETED:
        order.completed_at = now
        order.completed_by_user_id = user.id
        order.failure_reason = None
        order.failed_by_user_id = None
        order.failed_at = None
        order.closed_by_user_id = None
        order.closed_at = None
        # Completion is the confirmation (see the group flow).
        order.amount_confirmed = True
        order.amount_confirmed_by = user.id
        order.amount_confirmed_at = now

    elif new_status == ORDER_STATUS_PROCESSING:
        order.failure_reason = None
        order.failed_by_user_id = None
        order.failed_at = None
        order.closed_by_user_id = None
        order.closed_at = None
        order.completed_by_user_id = None
        order.completed_at = None
        order.amount_confirmed = False
        order.amount_confirmed_by = None
        order.amount_confirmed_at = None

    elif new_status == ORDER_STATUS_PENDING:
        # Back to the pool: clear the whole assignment chain.
        order.accepted_by_user_id = None
        order.accepted_at = None
        order.completed_by_user_id = None
        order.completed_at = None
        order.failed_by_user_id = None
        order.failed_at = None
        order.failure_reason = None
        order.failure_note = None
        order.closed_by_user_id = None
        order.closed_at = None
        order.amount_confirmed = False
        order.amount_confirmed_by = None
        order.amount_confirmed_at = None

    elif new_status == ORDER_STATUS_CLOSED:
        order.closed_by_user_id = user.id
        order.closed_at = now

    order.order_status = new_status
    db.add(OrderEvent(
        order_id=order.id,
        event_type="admin_status_change",
        from_status=from_st,
        to_status=new_status,
        actor_user_id=user.id,
        note=payload.failure_reason if new_status == ORDER_STATUS_FAILED else None,
    ))
    db.add(AuditLog(
        actor_type=ACTOR_ADMIN,
        actor_user_id=user.id,
        action="order_status_override",
        entity_type="order",
        entity_id=order.order_number,
        detail=f"{from_st}->{new_status}",
    ))


def update_order(db: Session, order: Order, payload: OrderUpdate, user: User,
                 sync_telegram: bool = True) -> Order:
    """Edit an order. Admin only.

    Any change that alters what the group sees (fields or status) is pushed to
    the existing Telegram message automatically -- unless the caller explicitly
    opts out with ``sync_telegram=False`` (the dedicated send/retry endpoints
    manage the message themselves).
    """
    is_admin = user.role == ROLE_ADMIN

    # Basic editable fields (admin only may edit, per rules).
    if not is_admin:
        raise PermissionError("only_admin_edits")

    _GROUP_VISIBLE_FIELDS = (
        "product_id", "order_owner_id", "product_name_snapshot",
        "email", "login_method", "account", "account_info", "note",
    )
    changed = False
    for field in _GROUP_VISIBLE_FIELDS:
        val = getattr(payload, field, None)
        if val is not None:
            if getattr(order, field, None) != val:
                changed = True
            setattr(order, field, val)

    if payload.currency is not None:
        if payload.currency not in ("INR", "USD"):
            raise ValueError("unsupported_currency")
        if order.currency != payload.currency:
            changed = True
        order.currency = payload.currency
    if payload.amount is not None:
        if payload.amount <= 0:
            raise ValueError("amount_invalid")
        if order.amount != payload.amount:
            changed = True
        order.amount = payload.amount
    if payload.password is not None and payload.password != "":
        order.password_encrypted = encrypt_secret(payload.password)
        changed = True

    # ---- Admin workflow override -------------------------------------
    # Without this an order that was marked failed by mistake was stuck
    # forever: the group can only reopen, and the admin had no control at all.
    if payload.order_status is not None:
        new_status = payload.order_status
        if new_status not in (
            ORDER_STATUS_PENDING,
            ORDER_STATUS_PROCESSING,
            ORDER_STATUS_COMPLETED,
            ORDER_STATUS_FAILED,
            ORDER_STATUS_CLOSED,
        ):
            raise ValueError("invalid_order_status")
        if new_status == ORDER_STATUS_DRAFT:
            raise ValueError("cannot_set_draft_via_update")

        if new_status != order.order_status:
            _apply_status_override(db, order, new_status, payload, user)
            changed = True

    # Admin financial controls
    if payload.amount_confirmed is not None:
        if not is_admin:
            raise PermissionError("only_admin_confirms")
        order.amount_confirmed = payload.amount_confirmed
        order.amount_confirmed_by = user.id
        order.amount_confirmed_at = _now()
    if payload.exclude_from_settlement is not None:
        if not is_admin:
            raise PermissionError("only_admin_excludes")
        order.financial_status = (
            FIN_STATUS_EXCLUDED if payload.exclude_from_settlement
            else FIN_STATUS_UNSETTLED
        )
    if payload.financial_status is not None and is_admin:
        order.financial_status = payload.financial_status

    db.add(AuditLog(actor_type=ACTOR_ADMIN, actor_user_id=user.id,
                    action="order_update", entity_type="order",
                    entity_id=order.order_number))
    db.commit()
    db.refresh(order)

    if changed and sync_telegram:
        # Best-effort: a Telegram hiccup must never undo a saved edit.
        try:
            sync_order_to_telegram(db, order)
        except Exception:
            pass

    return order


def partner_can_access(order: Order, user: User) -> bool:
    if user.role == ROLE_ADMIN:
        return True
    if user.role == ROLE_WORKER:
        return bool(order.telegram_chat_id and any(
            access.chat_id == order.telegram_chat_id for access in user.chat_accesses
        ))
    if user.role == ROLE_DISPATCHER:
        # A dispatcher only sees the orders they sent; nothing else.
        return order.order_owner_id == user.id
    if order.order_owner_id == user.id:
        return True
    if order.accepted_by_user_id == user.id:
        return True
    return False
