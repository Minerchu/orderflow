from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models.audit import LoginAttempt


# ---------- Password hashing (bcrypt) ----------
def hash_password(password: str) -> str:
    pw = password.encode("utf-8")[:72]  # bcrypt max 72 bytes
    return bcrypt.hashpw(pw, bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, hashed: Optional[str]) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(
            password.encode("utf-8")[:72], hashed.encode("utf-8")
        )
    except (ValueError, TypeError):
        return False


# ---------- Symmetric encryption for credentials ----------
def _fernet():
    from cryptography.fernet import Fernet

    key = base64.urlsafe_b64encode(hashlib.sha256(settings.APP_SECRET_KEY.encode()).digest())
    return Fernet(key)


def encrypt_secret(plain: str) -> str:
    if plain is None:
        raise ValueError("cannot encrypt None")
    return _fernet().encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt_secret(token: str) -> str:
    return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")


# ---------- Session tokens (signed, not encrypted) ----------
_serializer = URLSafeTimedSerializer(settings.SESSION_SECRET, salt="orderflow-session")


def create_session_token(user_id: int) -> str:
    return _serializer.dumps({"uid": user_id})


def verify_session_token(token: str, max_age: int = 60 * 60 * 24 * 7) -> Optional[int]:
    try:
        data = _serializer.loads(token, max_age=max_age)
        return data.get("uid")
    except (BadSignature, SignatureExpired):
        return None


# ---------- Short-lived signed file URLs ----------
_file_serializer = URLSafeTimedSerializer(settings.SESSION_SECRET, salt="orderflow-file")


def create_file_token(storage_key: str) -> str:
    """Sign a storage key so it can be fetched without an Authorization header
    (e.g. browser <img>/window.open/download links)."""
    return _file_serializer.dumps({"k": storage_key})


def verify_file_token(token: str, max_age: int = 900) -> Optional[str]:
    try:
        data = _file_serializer.loads(token, max_age=max_age)
        return data.get("k")
    except (BadSignature, SignatureExpired):
        return None


# ---------- Login attempt throttling ----------
MAX_ATTEMPTS = 5
LOCK_WINDOW_MINUTES = 15


def is_locked(db: Session, username: str) -> bool:
    since = datetime.now(timezone.utc) - timedelta(minutes=LOCK_WINDOW_MINUTES)
    fails = (
        db.query(LoginAttempt)
        .filter(
            LoginAttempt.username == username,
            LoginAttempt.success.is_(False),
            LoginAttempt.attempt_at >= since,
        )
        .count()
    )
    return fails >= MAX_ATTEMPTS


def record_attempt(db: Session, username: str, success: bool, ip: Optional[str] = None) -> None:
    db.add(LoginAttempt(username=username, success=success, ip_address=ip))
    db.commit()
