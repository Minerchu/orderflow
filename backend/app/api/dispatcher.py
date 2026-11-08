from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import (
    ROLE_DISPATCHER,
    SETTLEMENT_TYPE_DISPATCHER,
    ACTOR_DISPATCHER,
)
from app.core.deps import get_current_user
from app.db.models.audit import AuditLog
from app.db.models.order import Order
from app.db.models.product import Product
from app.db.models.settlement import SettlementBatch
from app.db.models.user import DispatcherProductAccess, TelegramBindToken, User
from app.db.session import get_db
from app.schemas.order import OrderOut
from app.schemas.product import ProductOut
from app.schemas.settlement import SettlementOut

router = APIRouter(prefix="/api/dispatcher", tags=["dispatcher"])

BIND_TOKEN_TTL_MINUTES = 10


def _ensure_dispatcher(user: User) -> User:
    if user.role != ROLE_DISPATCHER:
        raise HTTPException(status_code=403, detail="dispatcher_only")
    return user


def _product_ids(db: Session, user: User) -> list[int]:
    rows = db.execute(
        select(DispatcherProductAccess.product_id).where(
            DispatcherProductAccess.user_id == user.id
        )
    ).scalars().all()
    return sorted(int(r) for r in rows)


def _chat_ids(user: User) -> list[str]:
    return [a.chat_id for a in user.chat_accesses]


def _bot_username(db: Session) -> Optional[str]:
    """Best-effort lookup for the deep-link host; never blocks binding."""
    try:
        from app.services.telegram_bot import get_telegram_client

        client = get_telegram_client(db)
        resp = client.get_me()
        if isinstance(resp, dict) and resp.get("ok") is True:
            return (resp.get("result") or {}).get("username")
    except Exception:
        return None
    return None


@router.get("/profile")
def profile(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _ensure_dispatcher(user)
    product_ids = _product_ids(db, user)
    products = []
    if product_ids:
        products = db.execute(
            select(Product).where(Product.id.in_(product_ids), Product.is_active.is_(True))
            .order_by(Product.name)
        ).scalars().all()
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "is_active": user.is_active,
        "preferred_language": user.preferred_language,
        "default_chat_id": user.default_chat_id,
        "chat_ids": _chat_ids(user),
        "allowed_product_ids": product_ids,
        "products": [ProductOut.model_validate(p).model_dump() for p in products],
        "telegram_user_id": user.telegram_user_id,
        "telegram_username": user.telegram_username,
        "telegram_bound": bool(user.telegram_user_id),
    }


@router.get("/products", response_model=list[ProductOut])
def my_products(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _ensure_dispatcher(user)
    ids = _product_ids(db, user)
    if not ids:
        return []
    rows = db.execute(
        select(Product).where(Product.id.in_(ids), Product.is_active.is_(True))
        .order_by(Product.name)
    ).scalars().all()
    return [ProductOut.model_validate(p) for p in rows]


@router.get("/orders", response_model=list[OrderOut])
def my_orders(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    order_status: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=200),
):
    _ensure_dispatcher(user)
    q = select(Order).where(Order.order_owner_id == user.id)
    if order_status:
        q = q.where(Order.order_status == order_status)
    q = q.order_by(Order.created_at.desc(), Order.id.desc())
    rows = db.execute(q.limit(page_size).offset((page - 1) * page_size)).scalars().all()

    from app.api.orders import _serialize

    return [_serialize(db, o) for o in rows]


@router.post("/telegram/bind-token")
def create_bind_token(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Mint a one-time Telegram binding token for the logged-in dispatcher."""
    _ensure_dispatcher(user)

    # Housekeeping: an old unused token must not stay valid forever.
    db.query(TelegramBindToken).filter(
        TelegramBindToken.user_id == user.id,
        TelegramBindToken.used_at.is_(None),
    ).delete(synchronize_session=False)

    raw = secrets.token_urlsafe(24)
    now = datetime.now(timezone.utc)
    db.add(TelegramBindToken(
        user_id=user.id,
        token_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        expires_at=now + timedelta(minutes=BIND_TOKEN_TTL_MINUTES),
        created_at=now,
    ))
    db.add(AuditLog(
        actor_type=ACTOR_DISPATCHER, actor_user_id=user.id,
        action="telegram_bind_token_created", entity_type="user",
        entity_id=str(user.id),
    ))
    db.commit()

    bot_username = _bot_username(db)
    return {
        "token": raw,
        "expires_in": BIND_TOKEN_TTL_MINUTES * 60,
        "bot_username": bot_username,
        "deep_link": f"https://t.me/{bot_username}?start=bind_{raw}" if bot_username else None,
        "command": f"/bind {raw}",
    }


@router.delete("/telegram/bind")
def unbind_telegram(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _ensure_dispatcher(user)
    user.telegram_user_id = None
    user.telegram_username = None
    db.add(AuditLog(
        actor_type=ACTOR_DISPATCHER, actor_user_id=user.id,
        action="telegram_unbind", entity_type="user", entity_id=str(user.id),
    ))
    db.commit()
    return {"ok": True, "telegram_bound": False}


@router.get("/settlements", response_model=list[SettlementOut])
def my_settlements(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _ensure_dispatcher(user)
    rows = db.execute(
        select(SettlementBatch)
        .where(
            SettlementBatch.settlement_type == SETTLEMENT_TYPE_DISPATCHER,
            SettlementBatch.dispatcher_user_id == user.id,
        )
        .order_by(SettlementBatch.created_at.desc())
    ).scalars().all()
    return [SettlementOut.model_validate(r) for r in rows]
