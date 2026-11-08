"""Webhook registration helpers.

Telegram only delivers button taps (``callback_query``) to a URL registered
via ``setWebhook``. The HTTP endpoint existing is NOT enough -- without
registration every tap is silently dropped, which looks exactly like a dead
button. This module owns the register / inspect / unregister flow.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlparse

from app.config import settings

logger = logging.getLogger(__name__)

# We only care about button presses; filtering other update types keeps the
# queue small and avoids pointless work on every message in the group.
# Button taps AND private text messages. The latter carry /start bind_<token>
# (Telegram binding) and /count; filtering them out silently broke both.
CALLBACK_UPDATES = ["callback_query", "message"]


class WebhookURLError(ValueError):
    pass


def build_webhook_url(base_url: str, path: str = "/api/telegram/webhook") -> str:
    """Normalise APP_BASE_URL into an absolute webhook URL.

    Telegram requires a public HTTPS URL; we validate the shape early so the
    admin gets a clear message instead of a confusing Telegram error.
    """
    base = (base_url or "").strip().rstrip("/")
    if not base:
        raise WebhookURLError("webhook_base_url_missing")
    if "://" not in base:
        base = f"https://{base}"
    parsed = urlparse(base)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise WebhookURLError("webhook_base_url_invalid")
    return f"{base}{path}"


# Reasons a URL cannot work as a Telegram webhook, checked before we bother
# Telegram -- each maps to a concrete admin action.
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", ""}


def check_webhook_url(url: str) -> str:
    """Return "" when the URL is usable, otherwise a stable reason code.

    Reason codes deliberately carry no user data so they are safe to log and
    to return to the browser:
      webhook_base_url_missing / webhook_base_url_invalid
      webhook_requires_https:<current APP_BASE_URL>
      webhook_host_not_public:<host>
    """
    candidate = (url or "").strip()
    if not candidate:
        return "webhook_base_url_missing"

    parsed = urlparse(candidate)
    if not parsed.netloc:
        return "webhook_base_url_invalid"

    if parsed.scheme != "https":
        return "webhook_requires_https"

    if (parsed.hostname or "") in _LOCAL_HOSTS:
        return f"webhook_host_not_public:{parsed.hostname or candidate}"

    return ""


@dataclass(frozen=True)
class WebhookState:
    url: str
    has_custom_certificate: bool
    pending_update_count: int
    last_error_message: str | None
    registered: bool
    matches_expected: bool
    allowed_updates: tuple[str, ...] | None = None


def _updates_ok(result: dict) -> bool:
    """True when the registered update filters cover what this app needs.

    Telegram returns ``null`` (and treats ``[]``) as "all updates", which is a
    superset of CALLBACK_UPDATES. Any explicit list must contain every type we
    rely on -- an old webhook registered with only ``callback_query`` silently
    drops /start bind_<token> and /count, which is why this check exists.
    """
    raw = result.get("allowed_updates")
    if not raw:
        return True
    return set(CALLBACK_UPDATES).issubset({str(x) for x in raw})


def inspect_webhook(client, expected_url: str) -> WebhookState:
    """Read Telegram's view of the current webhook."""
    resp = client.get_webhook_info()
    result = (resp or {}).get("result") or {}
    current = (result.get("url") or "").strip()
    raw_updates = result.get("allowed_updates")
    allowed = None if raw_updates is None else tuple(str(x) for x in raw_updates)
    # Telegram may append nothing, but be tolerant about trailing slashes.
    url_ok = current.rstrip("/") == expected_url.rstrip("/")
    return WebhookState(
        url=current,
        has_custom_certificate=bool(result.get("has_custom_certificate")),
        pending_update_count=int(result.get("pending_update_count") or 0),
        last_error_message=result.get("last_error_message"),
        registered=bool(current),
        matches_expected=url_ok and _updates_ok(result),
        allowed_updates=allowed,
    )


def register_webhook(client, url: str, secret_token: str = "") -> dict:
    """Point the bot at our webhook. Safe to call repeatedly."""
    resp = client.set_webhook(
        url,
        secret_token=(secret_token or settings.TELEGRAM_WEBHOOK_SECRET or "").strip(),
        allowed_updates=CALLBACK_UPDATES,
    )
    if not isinstance(resp, dict) or resp.get("ok") is not True:
        from app.services.telegram_bot import describe_telegram_failure

        raise RuntimeError(describe_telegram_failure(resp, "webhook_register_failed"))
    logger.info("telegram_webhook_registered url=%s", url)
    return {"ok": True, "url": url}


def unregister_webhook(client) -> dict:
    resp = client.delete_webhook()
    if not isinstance(resp, dict) or resp.get("ok") is not True:
        from app.services.telegram_bot import describe_telegram_failure

        raise RuntimeError(describe_telegram_failure(resp, "webhook_delete_failed"))
    logger.info("telegram_webhook_deleted")
    return {"ok": True}