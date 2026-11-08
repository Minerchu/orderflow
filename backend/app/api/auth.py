from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.security import (
    create_session_token,
    hash_password,
    is_locked,
    record_attempt,
    verify_password,
)
from app.db.session import get_db
from app.db.models.user import User
from app.schemas.auth import LoginIn, TokenOut
from app.schemas.user import UserOut
from app.constants import ROLE_WORKER
from app.config import settings
from app.services.system_config import get_telegram_runtime_config
from app.services.telegram_bot import TelegramAPIClient

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/telegram/config")
def telegram_login_config(db: Session = Depends(get_db)):
    runtime = get_telegram_runtime_config(db)
    if not runtime.bot_token:
        raise HTTPException(status_code=503, detail="telegram_not_configured")
    try:
        client = TelegramAPIClient(runtime.bot_token, proxy=(settings.TELEGRAM_PROXY or "").strip())
        result = client.get_me()
    except Exception:
        raise HTTPException(status_code=502, detail="telegram_login_unavailable") from None
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise HTTPException(status_code=502, detail="telegram_login_unavailable")
    bot = result.get("result") or {}
    username = bot.get("username")
    if not username:
        raise HTTPException(status_code=502, detail="telegram_login_unavailable")
    return {"bot_username": username}


@router.post("/telegram")
def telegram_login(payload: dict, db: Session = Depends(get_db)):
    runtime = get_telegram_runtime_config(db)
    if not runtime.bot_token:
        raise HTTPException(status_code=503, detail="telegram_not_configured")

    try:
        telegram_id = str(int(payload["id"]))
        auth_date = int(payload["auth_date"])
        received_hash = str(payload["hash"]).lower()
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=401, detail="telegram_login_invalid") from None
    now = int(time.time())
    if auth_date > now + 30 or now - auth_date > 600:
        raise HTTPException(status_code=401, detail="telegram_login_expired")
    fields = {}
    for key, value in payload.items():
        if key == "hash" or value is None:
            continue
        if isinstance(value, bool):
            fields[key] = "true" if value else "false"
        elif isinstance(value, (str, int, float)):
            fields[key] = str(value)
        else:
            raise HTTPException(status_code=401, detail="telegram_login_invalid")
    data_check_string = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret_key = hashlib.sha256(runtime.bot_token.encode("utf-8")).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        raise HTTPException(status_code=401, detail="telegram_login_invalid")

    user = db.query(User).filter(User.telegram_user_id == telegram_id).first()
    display_name = " ".join(part for part in (fields.get("first_name"), fields.get("last_name")) if part).strip()[:128]
    now_utc = datetime.now(timezone.utc)
    if user is None:
        username = f"tg_{telegram_id}"
        if db.query(User).filter(User.username == username).first():
            username = f"tg_{telegram_id}_{secrets.token_hex(3)}"
        user = User(
            username=username,
            password_hash=hash_password(secrets.token_urlsafe(32)),
            role=ROLE_WORKER,
            telegram_user_id=telegram_id,
            telegram_username=(fields.get("username", "") or "")[:64] or None,
            display_name=display_name or None,
            preferred_language="en",
            is_active=False,
            last_login_at=now_utc,
        )
        db.add(user)
        db.flush()
        from app.db.models.audit import AuditLog
        db.add(AuditLog(actor_type="telegram", action="telegram_login_pending", entity_type="user", entity_id=str(user.id), detail=fields.get("username") or telegram_id))
        db.commit()
        return {"status": "pending_approval"}

    if fields.get("username"):
        user.telegram_username = fields["username"][:64]
    if display_name:
        user.display_name = display_name
    user.last_login_at = now_utc
    db.commit()
    if not user.is_active:
        return {"status": "pending_approval"}
    return {
        "status": "ok",
        "access_token": create_session_token(user.id),
        "token_type": "bearer",
        "user": UserOut.model_validate(user),
    }


@router.post("/login", response_model=TokenOut)
def login(data: LoginIn, db: Session = Depends(get_db)):
    if is_locked(db, data.username):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed attempts. Please try later.",
        )
    user = db.query(User).filter(User.username == data.username).first()
    if user is None or not user.is_active or not verify_password(
        data.password, user.password_hash
    ):
        record_attempt(db, data.username, False)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    record_attempt(db, data.username, True)
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    token = create_session_token(user.id)
    return TokenOut(access_token=token, user=UserOut.model_validate(user))


@router.post("/logout")
def logout():
    # Stateless token: client discards it. Endpoint provided for UX symmetry.
    return {"message": "logged_out"}


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return UserOut.model_validate(current_user)
