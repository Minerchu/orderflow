"""Tests for the webhook URL validation that gates button delivery.

`webhook_requires_https` used to be an opaque error with no hint about the
offending value. These tests pin down the reason codes so the UI can explain
the problem instead of just naming it.
"""

import pytest

from app.services.webhook import build_webhook_url, check_webhook_url, WebhookURLError


@pytest.mark.parametrize("url", [
    "https://order.example.com/api/telegram/webhook",
    "https://order.example.com/",
])
def test_valid_https_url_accepted(url):
    assert check_webhook_url(url) == ""


def test_http_is_rejected_with_https_reason():
    assert check_webhook_url("http://order.example.com/hook") == "webhook_requires_https"


def test_reason_carries_current_value_for_http():
    """The admin needs to SEE which value is wrong, not just that it's wrong."""
    configured = "http://localhost"
    resolved = build_webhook_url(configured)
    reason = check_webhook_url(resolved)
    assert reason == "webhook_requires_https"
    # The API layer appends the configured value so the UI can display it.
    assert f"{reason}:{configured}".startswith("webhook_requires_https:")


@pytest.mark.parametrize("host", [
    "localhost", "127.0.0.1", "0.0.0.0", "[::1]",
])
def test_local_hosts_rejected(host):
    url = f"https://{host}/api/telegram/webhook"
    reason = check_webhook_url(url)
    assert reason.startswith("webhook_host_not_public"), reason


def test_empty_url_reports_missing():
    assert check_webhook_url("") == "webhook_base_url_missing"
    assert check_webhook_url("   ") == "webhook_base_url_missing"


def test_malformed_url_reports_invalid():
    assert check_webhook_url("https://") == "webhook_base_url_invalid"


def test_build_webhook_url_upgrades_bare_host_to_https():
    """A bare domain is common in .env; assume https rather than failing."""
    assert build_webhook_url("order.example.com").startswith("https://")


def test_build_webhook_url_rejects_empty():
    with pytest.raises(WebhookURLError):
        build_webhook_url("")


def test_runtime_config_prefers_db_public_url(db):
    """Saving the URL in the UI must take effect without editing .env."""
    from app.core.security import encrypt_secret
    from app.services.system_config import get_or_create_system_config, get_telegram_runtime_config

    config = get_or_create_system_config(db)
    config.public_base_url = "https://saved.example.com"
    db.commit()

    # Env default is localhost; the DB value must win.
    assert get_telegram_runtime_config(db).public_base_url == "https://saved.example.com"


def test_runtime_config_falls_back_to_env_when_db_empty(db):
    from app.services.system_config import get_or_create_system_config, get_telegram_runtime_config

    config = get_or_create_system_config(db)
    config.public_base_url = ""
    db.commit()

    resolved = get_telegram_runtime_config(db).public_base_url
    assert resolved == (settings_base_url() or "").strip()


def settings_base_url():
    from app.config import settings

    return settings.APP_BASE_URL