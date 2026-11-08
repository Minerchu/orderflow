from __future__ import annotations

import logging
from pathlib import Path
import re
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.constants import ROLE_ADMIN, ROLE_DISPATCHER, ROLE_PARTNER, ROLE_WORKER
from app.core.deps import require_admin
from app.core.security import encrypt_secret, hash_password
from app.db.models.audit import AuditLog
from app.db.models.product import Product
from app.db.models.user import (
    DispatcherProductAccess,
    PartnerChatAccess,
    TelegramBindToken,
    User,
)
from app.db.models.order import Order
from app.db.session import get_db
from app.schemas.product import ProductOut
from app.schemas.user import UserOut
from app.services.system_config import get_or_create_system_config, get_telegram_runtime_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


class PartnerCreateReq(BaseModel):
    username: str
    password: str
    telegram_user_id: str | None = None
    telegram_username: str | None = None
    preferred_language: str = "en"


class PartnerUpdateReq(BaseModel):
    is_active: bool


class TelegramSettingsReq(BaseModel):
    bot_token: str | None = None
    default_chat_id: str
    allowed_chat_ids: str = ""
    admin_telegram_user_ids: str = ""

    @field_validator("bot_token", "default_chat_id", "allowed_chat_ids", "admin_telegram_user_ids")
    @classmethod
    def strip_values(cls, value: str | None):
        return value.strip() if isinstance(value, str) else value

    @field_validator("default_chat_id")
    @classmethod
    def validate_chat_id(cls, value: str):
        if not value:
            raise ValueError("default_chat_id_required")
        if not value.lstrip("-").isdigit():
            raise ValueError("invalid_default_chat_id")
        return value

    @field_validator("allowed_chat_ids", "admin_telegram_user_ids")
    @classmethod
    def validate_id_list(cls, value: str):
        for item in (part.strip() for part in value.split(",")):
            if item and not item.lstrip("-").isdigit():
                raise ValueError("invalid_id_list")
        return value


@router.get("/audit-logs", response_model=list)
def audit_logs(
    db: Session = Depends(get_db), _=Depends(require_admin), limit: int = 200
):
    rows = db.execute(
        select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    ).scalars().all()
    return [
        {
            "id": r.id,
            "actor_type": r.actor_type,
            "actor_user_id": r.actor_user_id,
            "action": r.action,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "detail": r.detail,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.get("/partners", response_model=list[UserOut])
def list_partners(db: Session = Depends(get_db), _=Depends(require_admin)):
    rows = db.execute(
        select(User).where(User.role.in_((ROLE_PARTNER, ROLE_WORKER))).order_by(User.username)
    ).scalars().all()
    return [
        {**UserOut.model_validate(r).model_dump(),
         "assigned_chat_ids": [access.chat_id for access in r.chat_accesses]}
        for r in rows
    ]


@router.get("/partners/chat-groups")
def partner_chat_groups(db: Session = Depends(get_db), _=Depends(require_admin)):
    counts = db.execute(
        select(Order.telegram_chat_id, func.count(Order.id))
        .where(Order.telegram_chat_id.is_not(None))
        .group_by(Order.telegram_chat_id)
    ).all()
    groups = {str(chat_id): int(count) for chat_id, count in counts if chat_id}
    runtime = get_telegram_runtime_config(db)
    for chat_id in [runtime.default_chat_id, *runtime.allowed_chat_ids]:
        if chat_id:
            groups.setdefault(chat_id, 0)
    return [{"chat_id": chat_id, "order_count": groups[chat_id]} for chat_id in sorted(groups)]


class PartnerAccessReq(BaseModel):
    chat_ids: list[str] = []
    is_active: bool

    @field_validator("chat_ids")
    @classmethod
    def validate_chat_ids(cls, values: list[str]):
        values = list(dict.fromkeys(value.strip() for value in values))
        if any(not re.fullmatch(r"-?\d+", value) for value in values):
            raise ValueError("invalid_chat_id")
        return values


@router.get("/partners/{user_id}/access")
def get_partner_access(user_id: int, db: Session = Depends(get_db), _=Depends(require_admin)):
    user = db.get(User, user_id)
    if user is None or user.role not in (ROLE_PARTNER, ROLE_WORKER):
        raise HTTPException(status_code=404, detail="partner_not_found")
    return {"chat_ids": [access.chat_id for access in user.chat_accesses], "is_active": user.is_active}


@router.put("/partners/{user_id}/access")
def update_partner_access(user_id: int, payload: PartnerAccessReq, db: Session = Depends(get_db),
                          admin: User = Depends(require_admin)):
    user = db.get(User, user_id)
    if user is None or user.role not in (ROLE_PARTNER, ROLE_WORKER):
        raise HTTPException(status_code=404, detail="partner_not_found")
    if user.role == ROLE_WORKER and payload.is_active and not payload.chat_ids:
        raise HTTPException(status_code=400, detail="worker_requires_group")
    user.chat_accesses.clear()
    user.chat_accesses.extend(PartnerChatAccess(chat_id=chat_id) for chat_id in payload.chat_ids)
    user.is_active = payload.is_active
    db.add(AuditLog(actor_type="admin", actor_user_id=admin.id,
                    action="partner_access_update", entity_type="user", entity_id=str(user.id),
                    detail=",".join(payload.chat_ids)))
    db.commit()
    return {"ok": True, "chat_ids": payload.chat_ids, "is_active": user.is_active}


@router.post("/partners", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_partner(payload: PartnerCreateReq, db: Session = Depends(get_db),
                   _=Depends(require_admin)):
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status_code=400, detail="username_exists")
    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        role=ROLE_PARTNER,
        telegram_user_id=payload.telegram_user_id,
        telegram_username=payload.telegram_username,
        preferred_language=payload.preferred_language,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserOut.model_validate(user)


@router.patch("/partners/{user_id}", response_model=UserOut)
def update_partner(user_id: int, payload: PartnerUpdateReq, db: Session = Depends(get_db),
                   _=Depends(require_admin)):
    user = db.get(User, user_id)
    if user is None or user.role not in (ROLE_PARTNER, ROLE_WORKER):
        raise HTTPException(status_code=404, detail="partner_not_found")
    if user.role == ROLE_WORKER and payload.is_active and not user.chat_accesses:
        raise HTTPException(status_code=400, detail="worker_requires_group")
    user.is_active = payload.is_active
    db.commit()
    db.refresh(user)
    return UserOut.model_validate(user)


def _system_settings_response(db: Session):
    telegram = get_telegram_runtime_config(db)
    return {
        "default_currency": settings.DEFAULT_CURRENCY,
        "supported_currencies": settings.supported_currencies,
        "default_language": settings.DEFAULT_LANGUAGE,
        "telegram_message_language": settings.TELEGRAM_MESSAGE_LANGUAGE,
        "show_order_id_in_group": settings.SHOW_ORDER_ID_IN_GROUP,
        "show_credentials_in_group": settings.SHOW_CREDENTIALS_IN_GROUP,
        "show_password_in_group": settings.SHOW_PASSWORD_IN_GROUP,
        "allow_any_group_member_to_complete": settings.ALLOW_ANY_GROUP_MEMBER_TO_COMPLETE,
        "allow_any_group_member_to_fail": settings.ALLOW_ANY_GROUP_MEMBER_TO_FAIL,
        "allow_any_group_member_to_reopen": settings.ALLOW_ANY_GROUP_MEMBER_TO_REOPEN,
        "allow_any_group_member_to_close": settings.ALLOW_ANY_GROUP_MEMBER_TO_CLOSE,
        "storage_backend": settings.STORAGE_BACKEND,
        "max_upload_size_mb": settings.MAX_UPLOAD_SIZE_MB,
        "telegram_configured": bool(telegram.bot_token),
        "default_chat_id": telegram.default_chat_id,
        "allowed_chat_ids": ",".join(telegram.allowed_chat_ids),
        "admin_telegram_user_ids": ",".join(telegram.admin_telegram_user_ids),
        "allowed_chat_count": len(telegram.allowed_chat_ids),
    }


@router.get("/settings")
def system_settings(db: Session = Depends(get_db), _=Depends(require_admin)):
    return _system_settings_response(db)


@router.put("/settings/telegram")
def update_telegram_settings(
    payload: TelegramSettingsReq,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    config = get_or_create_system_config(db)
    if payload.bot_token:
        config.telegram_bot_token_encrypted = encrypt_secret(payload.bot_token)
    config.telegram_default_chat_id = payload.default_chat_id
    config.telegram_allowed_chat_ids = payload.allowed_chat_ids
    config.admin_telegram_user_ids = payload.admin_telegram_user_ids
    db.commit()
    return _system_settings_response(db)


class TelegramTestReq(BaseModel):
    chat_id: str | None = None
    send_test_message: bool = False

    @field_validator("chat_id")
    @classmethod
    def validate_chat_id(cls, value: str | None):
        if value is None:
            return value
        value = value.strip()
        if value and not value.lstrip("-").isdigit():
            raise ValueError("invalid_default_chat_id")
        return value


@router.post("/settings/telegram/test")
def test_telegram_connection(
    payload: TelegramTestReq,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    """Diagnose the bot end-to-end.

    Walks the layers in order and reports the first one that fails:
      1. bot token present          -> telegram_not_configured
      2. token accepted by Telegram-> telegram_unauthorized
      3. network / proxy reachable  -> telegram_network_error
      4. bot can see the chat       -> telegram_chat_not_found
      5. optional live test message -> send result
    """
    from app.services.telegram_bot import (
        TelegramAPIClient,
        describe_telegram_failure,
    )

    runtime = get_telegram_runtime_config(db)
    chat_id = (payload.chat_id or runtime.default_chat_id or "").strip()

    result: dict = {
        "ok": False,
        "bot_token_configured": bool(runtime.bot_token),
        "default_chat_id": runtime.default_chat_id,
        "tested_chat_id": chat_id,
        "proxy_configured": bool((settings.TELEGRAM_PROXY or "").strip()),
    }

    if not runtime.bot_token:
        result["stage"] = "token"
        result["code"] = "telegram_not_configured"
        return result

    client = TelegramAPIClient(runtime.bot_token, proxy=(settings.TELEGRAM_PROXY or "").strip())

    # 2) Token validity (also proves the network path works).
    try:
        me = client.get_me()
    except Exception as e:
        result["stage"] = "network"
        result["code"] = str(e) or "telegram_network_error"
        return result
    if not isinstance(me, dict) or me.get("ok") is not True:
        result["stage"] = "token"
        result["code"] = describe_telegram_failure(me, "telegram_unauthorized")
        return result

    me_result = me.get("result") or {}
    result["bot_username"] = me_result.get("username")
    result["bot_name"] = me_result.get("first_name")

    if not chat_id:
        result["stage"] = "chat"
        result["code"] = "no_chat_id"
        return result

    # 3) Can the bot see the target chat?
    try:
        chat = client.get_chat(chat_id)
    except Exception as e:
        result["stage"] = "chat"
        result["code"] = str(e) or "telegram_chat_not_found"
        return result
    if not isinstance(chat, dict) or chat.get("ok") is not True:
        result["stage"] = "chat"
        result["code"] = describe_telegram_failure(chat, "telegram_chat_not_found")
        return result

    chat_result = chat.get("result") or {}
    result["chat_title"] = chat_result.get("title")
    result["chat_type"] = chat_result.get("type")

    # 4) Optional live send — the only way to prove posting rights.
    if payload.send_test_message:
        try:
            sent = client.send_message(chat_id, "OrderFlow \u8fde\u901a\u6d4b\u8bd5\uff0c\u6536\u5230\u8fd9\u91cc\u8bf4\u660e\u53d1\u5355\u6b63\u5e38\u3002")
        except Exception as e:
            result["stage"] = "send"
            result["code"] = str(e) or "telegram_send_failed"
            return result
        if not isinstance(sent, dict) or sent.get("ok") is not True:
            result["stage"] = "send"
            result["code"] = describe_telegram_failure(sent, "telegram_send_failed")
            return result
        result["message_id"] = (sent.get("result") or {}).get("message_id")

    result["ok"] = True
    result["stage"] = "done"
    result["code"] = ""
    return result


class WebhookRegisterReq(BaseModel):
    url: str | None = None


@router.get("/settings/telegram/webhook")
def get_webhook_status(db: Session = Depends(get_db), _=Depends(require_admin)):
    """Report whether button taps can reach us.

    An unregistered webhook is THE reason "接单" appears to do nothing.
    """
    from app.services.telegram_bot import TelegramAPIClient
    from app.services.webhook import (
        WebhookURLError,
        build_webhook_url,
        check_webhook_url,
        inspect_webhook,
    )

    configured = get_telegram_runtime_config(db).public_base_url
    payload: dict = {
        "app_base_url": configured,
        # Pre-flight so the UI can explain the problem before the user clicks.
        "config_ok": False,
        "config_reason": "",
    }

    try:
        expected = build_webhook_url(configured)
    except WebhookURLError as e:
        return {**payload, "registered": False, "code": str(e), "expected_url": ""}

    reason = check_webhook_url(expected)
    payload["config_ok"] = not reason
    payload["config_reason"] = (
        f"{reason}:{configured}" if reason.startswith("webhook_requires_https") else reason
    )

    runtime = get_telegram_runtime_config(db)
    if not runtime.bot_token:
        return {
            **payload, "registered": False, "code": "telegram_not_configured",
            "expected_url": expected,
        }

    client = TelegramAPIClient(runtime.bot_token, proxy=(settings.TELEGRAM_PROXY or "").strip())
    try:
        state = inspect_webhook(client, expected)
    except Exception as e:
        return {**payload, "registered": False, "code": str(e), "expected_url": expected}

    return {
        **payload,
        "registered": state.registered,
        "matches_expected": state.matches_expected,
        "current_url": state.url,
        "expected_url": expected,
        "pending_update_count": state.pending_update_count,
        "last_error_message": state.last_error_message,
        "allowed_updates": list(state.allowed_updates or []),
        "required_updates": ["callback_query", "message"],
        "code": "",
    }


@router.post("/settings/telegram/webhook")
def register_webhook_endpoint(
    payload: WebhookRegisterReq,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    """Register the callback webhook. Required for inline buttons to work."""
    from app.services.telegram_bot import TelegramAPIClient
    from app.services.webhook import (
        WebhookURLError,
        build_webhook_url,
        check_webhook_url,
        register_webhook,
    )

    runtime = get_telegram_runtime_config(db)
    if not runtime.bot_token:
        raise HTTPException(status_code=400, detail="telegram_not_configured")

    configured = get_telegram_runtime_config(db).public_base_url

    # Admin may type a URL directly; otherwise derive it from APP_BASE_URL.
    explicit = (payload.url or "").strip()
    if explicit:
        target = explicit if "://" in explicit else f"https://{explicit}"
    else:
        try:
            target = build_webhook_url(configured)
        except WebhookURLError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None

    # The most common cause is APP_BASE_URL still being localhost/http, so the
    # reason code echoes the offending value instead of a bare error.
    reason = check_webhook_url(target)
    if reason:
        logger.warning(
            "webhook register rejected: APP_BASE_URL=%r resolved=%r reason=%s",
            configured, target, reason.split(":")[0],
        )
        if reason.startswith("webhook_requires_https"):
            reason = f"{reason}:{configured or '(empty)'}"
        raise HTTPException(status_code=400, detail=reason) from None

    client = TelegramAPIClient(runtime.bot_token, proxy=(settings.TELEGRAM_PROXY or "").strip())
    try:
        register_webhook(client, target)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from None

    return {"ok": True, "url": target}


class PublicBaseUrlReq(BaseModel):
    public_base_url: str

    @field_validator("public_base_url")
    @classmethod
    def validate_url(cls, value: str):
        value = (value or "").strip().rstrip("/")
        if not value:
            return ""
        # Accept a bare host and assume https, but reject obvious nonsense.
        if "://" not in value:
            value = f"https://{value}"
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("webhook_base_url_invalid")
        return value


@router.put("/settings/public-url")
def update_public_base_url(
    payload: PublicBaseUrlReq,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    """Persist the public URL used for the Telegram webhook.

    Saved in the database (not .env) so admins can fix a broken callback
    without touching the host or restarting containers.
    """
    config = get_or_create_system_config(db)
    config.public_base_url = payload.public_base_url
    db.commit()
    return {"ok": True, "public_base_url": config.public_base_url}


# ---------------------------------------------------------------------------
# Dispatchers (collaborative senders)
# ---------------------------------------------------------------------------
# A dispatcher does what the admin does -- send an order -- but only inside the
# groups and product whitelist the admin granted. They are intentionally NOT
# `partner`: partners accept and process orders in the group.


class DispatcherCreateReq(BaseModel):
    username: str
    password: str
    display_name: str | None = None
    preferred_language: str = "en"
    chat_ids: list[str] = []
    default_chat_id: str | None = None
    product_ids: list[int] = []
    is_active: bool = True

    @field_validator("chat_ids")
    @classmethod
    def validate_chat_ids(cls, values: list[str]):
        values = list(dict.fromkeys(v.strip() for v in values))
        if any(not re.fullmatch(r"-?\d+", v) for v in values):
            raise ValueError("invalid_chat_id")
        return values


class DispatcherUpdateReq(BaseModel):
    password: str | None = None
    display_name: str | None = None
    preferred_language: str | None = None
    chat_ids: list[str] | None = None
    default_chat_id: str | None = None
    product_ids: list[int] | None = None
    is_active: bool | None = None

    @field_validator("chat_ids")
    @classmethod
    def validate_chat_ids(cls, values: list[str] | None):
        if values is None:
            return values
        values = list(dict.fromkeys(v.strip() for v in values))
        if any(not re.fullmatch(r"-?\d+", v) for v in values):
            raise ValueError("invalid_chat_id")
        return values


def _dispatcher_out(db: Session, user: User) -> dict:
    product_ids = db.execute(
        select(DispatcherProductAccess.product_id).where(
            DispatcherProductAccess.user_id == user.id
        )
    ).scalars().all()
    out = UserOut.model_validate(user).model_dump()
    out.update({
        "assigned_chat_ids": [a.chat_id for a in user.chat_accesses],
        "default_chat_id": user.default_chat_id,
        "allowed_product_ids": sorted(int(p) for p in product_ids),
        "telegram_bound": bool(user.telegram_user_id),
    })
    return out


def _validate_scope(db: Session, chat_ids: list[str], default_chat_id: str | None,
                    product_ids: list[int]) -> str | None:
    if not chat_ids:
        raise HTTPException(status_code=400, detail="dispatcher_requires_group")
    chosen_default = (default_chat_id or "").strip() or None
    if chosen_default is None:
        if len(chat_ids) != 1:
            raise HTTPException(status_code=400, detail="dispatcher_default_group_required")
        chosen_default = chat_ids[0]
    if chosen_default not in chat_ids:
        raise HTTPException(status_code=400, detail="default_group_not_assigned")
    if product_ids:
        found = set(db.execute(
            select(Product.id).where(Product.id.in_(product_ids))
        ).scalars().all())
        missing = [p for p in product_ids if p not in found]
        if missing:
            raise HTTPException(status_code=400, detail="product_not_found")
    return chosen_default


def _apply_dispatcher_scope(db: Session, user: User, chat_ids: list[str],
                            default_chat_id: str | None, product_ids: list[int]) -> None:
    user.default_chat_id = default_chat_id
    # Flush the deletes before re-inserting: SQLite/PostgreSQL both reject the
    # new row if the old (user_id, chat_id) is still pending deletion in the
    # same flush batch.
    user.chat_accesses.clear()
    db.query(DispatcherProductAccess).filter(
        DispatcherProductAccess.user_id == user.id
    ).delete(synchronize_session=False)
    db.flush()
    user.chat_accesses.extend(PartnerChatAccess(chat_id=cid) for cid in chat_ids)
    for pid in dict.fromkeys(product_ids):
        db.add(DispatcherProductAccess(user_id=user.id, product_id=pid))


@router.get("/dispatchers")
def list_dispatchers(db: Session = Depends(get_db), _=Depends(require_admin)):
    rows = db.execute(
        select(User).where(User.role == ROLE_DISPATCHER).order_by(User.username)
    ).scalars().all()
    return [_dispatcher_out(db, u) for u in rows]


@router.post("/dispatchers", status_code=status.HTTP_201_CREATED)
def create_dispatcher(payload: DispatcherCreateReq, db: Session = Depends(get_db),
                      admin: User = Depends(require_admin)):
    username = (payload.username or "").strip()
    if not username:
        raise HTTPException(status_code=400, detail="username_required")
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=400, detail="username_exists")

    default_chat = _validate_scope(
        db, payload.chat_ids, payload.default_chat_id, payload.product_ids
    )
    user = User(
        username=username,
        password_hash=hash_password(payload.password),
        role=ROLE_DISPATCHER,
        display_name=(payload.display_name or "").strip() or None,
        preferred_language=payload.preferred_language or "en",
        is_active=payload.is_active,
    )
    db.add(user)
    db.flush()
    _apply_dispatcher_scope(db, user, payload.chat_ids, default_chat, payload.product_ids)
    db.add(AuditLog(
        actor_type="admin", actor_user_id=admin.id,
        action="dispatcher_create", entity_type="user", entity_id=str(user.id),
        detail=username,
    ))
    db.commit()
    db.refresh(user)
    return _dispatcher_out(db, user)


@router.put("/dispatchers/{user_id}")
def update_dispatcher(user_id: int, payload: DispatcherUpdateReq,
                      db: Session = Depends(get_db),
                      admin: User = Depends(require_admin)):
    user = db.get(User, user_id)
    if user is None or user.role != ROLE_DISPATCHER:
        raise HTTPException(status_code=404, detail="dispatcher_not_found")

    chat_ids = payload.chat_ids if payload.chat_ids is not None else [
        a.chat_id for a in user.chat_accesses
    ]
    product_ids = payload.product_ids if payload.product_ids is not None else list(
        db.execute(
            select(DispatcherProductAccess.product_id).where(
                DispatcherProductAccess.user_id == user.id
            )
        ).scalars().all()
    )
    default_chat = (
        payload.default_chat_id if payload.default_chat_id is not None
        else user.default_chat_id
    )
    default_chat = _validate_scope(db, chat_ids, default_chat, product_ids)

    _apply_dispatcher_scope(db, user, chat_ids, default_chat, product_ids)
    if payload.password:
        user.password_hash = hash_password(payload.password)
    if payload.display_name is not None:
        user.display_name = payload.display_name.strip() or None
    if payload.preferred_language is not None:
        user.preferred_language = payload.preferred_language
    if payload.is_active is not None:
        user.is_active = payload.is_active
    db.add(AuditLog(
        actor_type="admin", actor_user_id=admin.id,
        action="dispatcher_update", entity_type="user", entity_id=str(user.id),
        detail=",".join(chat_ids),
    ))
    db.commit()
    db.refresh(user)
    return _dispatcher_out(db, user)


@router.post("/dispatchers/{user_id}/unbind-telegram")
def unbind_dispatcher_telegram(user_id: int, db: Session = Depends(get_db),
                               admin: User = Depends(require_admin)):
    user = db.get(User, user_id)
    if user is None or user.role != ROLE_DISPATCHER:
        raise HTTPException(status_code=404, detail="dispatcher_not_found")
    user.telegram_user_id = None
    user.telegram_username = None
    db.query(TelegramBindToken).filter(
        TelegramBindToken.user_id == user.id,
        TelegramBindToken.used_at.is_(None),
    ).delete(synchronize_session=False)
    db.add(AuditLog(
        actor_type="admin", actor_user_id=admin.id,
        action="dispatcher_telegram_unbind", entity_type="user", entity_id=str(user.id),
    ))
    db.commit()
    return {"ok": True}
