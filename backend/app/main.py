from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    admin, attachments, auth, dispatcher, orders, partner, products,
    settlements, telegram,
)
from app.config import settings

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    """Make the app's own log records actually reach the log stream.

    Uvicorn only configures its own loggers, so the root logger keeps no
    handler and Python's ``lastResort`` handler silently drops everything below
    WARNING. Every ``logger.info(...)`` in this codebase -- webhook
    registration, callback outcomes, sequence refreshes -- therefore vanished,
    which made production problems impossible to diagnose from
    ``docker compose logs``.
    """
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # httpx includes the full request URL in INFO logs. Telegram Bot API URLs
    # carry the bot token in the path, so those logs must never be emitted.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


_configure_logging()

os.makedirs(settings.LOCAL_STORAGE_PATH, exist_ok=True)

app = FastAPI(title="OrderFlow", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(orders.router)
app.include_router(products.router)
app.include_router(attachments.router)
app.include_router(settlements.router)
app.include_router(partner.router)
app.include_router(dispatcher.router)
app.include_router(telegram.router)
app.include_router(admin.router)


def _sync_webhook() -> None:
    """Register the callback URL with Telegram at startup.

    Button taps go nowhere unless setWebhook has been called. Doing it here
    means a fresh deployment works without a manual step. Failures are logged
    but never block boot: the API must still come up so orders can be sent.
    """
    if not settings.AUTO_REGISTER_WEBHOOK:
        logger.info("webhook auto-registration disabled")
        return

    from app.db.session import SessionLocal
    from app.services.system_config import get_telegram_runtime_config
    from app.services.telegram_bot import get_telegram_client
    from app.services.webhook import (
        build_webhook_url,
        check_webhook_url,
        inspect_webhook,
        register_webhook,
    )

    db = SessionLocal()
    try:
        client = get_telegram_client(db)
        url = build_webhook_url(get_telegram_runtime_config(db).public_base_url)

        reason = check_webhook_url(url)
        if reason:
            # Almost always APP_BASE_URL left at localhost/http. Say so loudly
            # in the logs -- this is the #1 cause of "buttons do nothing".
            logger.warning(
                "telegram webhook NOT registered: %s "
                "(set the public URL in 系统设置 → 按钮回调, or APP_BASE_URL)",
                reason,
            )
            return

        state = inspect_webhook(client, url)
        if state.matches_expected:
            logger.info("telegram webhook already registered: %s", url)
            return
        register_webhook(client, url)
        logger.info("telegram webhook auto-registered: %s", url)
    except Exception as e:
        logger.warning("telegram webhook auto-registration skipped: %s", e)
    finally:
        db.close()


@app.on_event("startup")
def on_startup() -> None:
    settings.validate_required()
    _sync_webhook()


@app.get("/health")
def health():
    return {"status": "ok"}
