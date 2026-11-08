from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import settings
from app.core.security import decrypt_secret
from app.db.models.system_config import SystemConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TelegramRuntimeConfig:
    bot_token: str
    default_chat_id: str
    allowed_chat_ids: list[str]
    admin_telegram_user_ids: list[str]
    public_base_url: str


def parse_id_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def get_system_config(db: Session) -> SystemConfig | None:
    return db.get(SystemConfig, 1)


def get_or_create_system_config(db: Session) -> SystemConfig:
    config = get_system_config(db)
    if config is None:
        config = SystemConfig(id=1)
        db.add(config)
        db.flush()
    return config


def get_telegram_runtime_config(db: Session) -> TelegramRuntimeConfig:
    config = get_system_config(db)
    bot_token = settings.TELEGRAM_BOT_TOKEN
    default_chat_id = settings.TELEGRAM_DEFAULT_CHAT_ID
    allowed_chat_ids = settings.allowed_chat_ids
    admin_user_ids = settings.admin_telegram_user_ids
    # Env is the fallback; the settings UI can override it without a restart.
    public_base_url = (settings.APP_BASE_URL or "").strip()

    # Database values take priority, but ONLY when actually filled in.
    # A SystemConfig row created by an earlier save (or by
    # get_or_create_system_config) may hold empty strings; blindly
    # overwriting the env fallback with "" silently discarded the default
    # group and caused "no_chat_id" / wrong-chat sends.
    if config is not None:
        if config.telegram_bot_token_encrypted:
            try:
                bot_token = decrypt_secret(config.telegram_bot_token_encrypted)
            except Exception:
                # Key rotation / corrupted value: fall back to env rather
                # than failing every send with a confusing error.
                logger.warning("stored_telegram_token_undecryptable; using env fallback")
                bot_token = settings.TELEGRAM_BOT_TOKEN
        if config.telegram_default_chat_id and config.telegram_default_chat_id.strip():
            default_chat_id = config.telegram_default_chat_id.strip()
        if config.telegram_allowed_chat_ids and config.telegram_allowed_chat_ids.strip():
            allowed_chat_ids = parse_id_list(config.telegram_allowed_chat_ids)
        if config.admin_telegram_user_ids and config.admin_telegram_user_ids.strip():
            admin_user_ids = parse_id_list(config.admin_telegram_user_ids)
        if config.public_base_url and config.public_base_url.strip():
            public_base_url = config.public_base_url.strip().rstrip("/")

    return TelegramRuntimeConfig(
        bot_token=(bot_token or "").strip(),
        default_chat_id=default_chat_id,
        allowed_chat_ids=allowed_chat_ids,
        admin_telegram_user_ids=admin_user_ids,
        public_base_url=public_base_url,
    )
