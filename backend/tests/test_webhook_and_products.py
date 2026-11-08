"""Regression tests for the two bugs that made the group button look dead."""

import pytest
from unittest.mock import Mock

from app.config import settings
from app.services.telegram_bot import MockTelegramClient
from app.services.webhook import (
    WebhookURLError,
    build_webhook_url,
    inspect_webhook,
    register_webhook,
)


@pytest.mark.parametrize("base,expected", [
    ("https://order.example.com", "https://order.example.com/api/telegram/webhook"),
    ("https://order.example.com/", "https://order.example.com/api/telegram/webhook"),
    ("http://1.2.3.4:8080", "http://1.2.3.4:8080/api/telegram/webhook"),
    # Bare host gets https:// so a copy-pasted domain still works.
    ("order.example.com", "https://order.example.com/api/telegram/webhook"),
])
def test_build_webhook_url(base, expected):
    assert build_webhook_url(base) == expected


def test_build_webhook_url_requires_value():
    with pytest.raises(WebhookURLError):
        build_webhook_url("")


def test_register_webhook_sets_callback_only_updates():
    client = Mock()
    client.set_webhook = Mock(return_value={"ok": True, "result": True})
    register_webhook(client, "https://x.test/api/telegram/webhook", secret_token="s3cr3t")

    _, kwargs = client.set_webhook.call_args
    # Buttons plus private messages: /start bind_<token> and /count arrive as
    # plain messages, so filtering them out breaks Telegram binding entirely.
    assert kwargs["allowed_updates"] == ["callback_query", "message"]
    assert kwargs["secret_token"] == "s3cr3t"


def test_register_webhook_raises_on_failure():
    client = Mock()
    client.set_webhook = Mock(return_value={
        "ok": False, "error_code": 400, "description": "Bad Request: can't use https"
    })
    with pytest.raises(RuntimeError) as exc:
        register_webhook(client, "https://x.test/api/telegram/webhook")
    assert "telegram_bad_request" in str(exc.value)


def test_inspect_detects_missing_registration():
    """The exact cause of '接单 has no effect': an empty webhook URL."""
    client = Mock()
    client.get_webhook_info = Mock(return_value={
        "ok": True,
        "result": {"url": "", "pending_update_count": 3, "last_error_message": None},
    })
    state = inspect_webhook(client, "https://x.test/api/telegram/webhook")
    assert state.registered is False
    assert state.matches_expected is False
    assert state.pending_update_count == 3


def test_inspect_detects_registered():
    client = Mock()
    client.get_webhook_info = Mock(return_value={
        "ok": True,
        "result": {"url": "https://x.test/api/telegram/webhook", "pending_update_count": 0},
    })
    state = inspect_webhook(client, "https://x.test/api/telegram/webhook")
    assert state.registered is True
    assert state.matches_expected is True


def test_inspect_requires_message_updates():
    """A URL-only match is not enough.

    The production webhook was registered before /start binding existed, with
    allowed_updates=["callback_query"]. inspect() said "already registered", so
    startup never repaired it and every bind token was dropped by Telegram.
    """
    url = "https://x.test/api/telegram/webhook"
    stale = Mock()
    stale.get_webhook_info = Mock(return_value={
        "ok": True,
        "result": {"url": url, "pending_update_count": 0,
                   "allowed_updates": ["callback_query"]},
    })
    state = inspect_webhook(stale, url)
    assert state.registered is True
    assert state.matches_expected is False
    assert state.allowed_updates == ("callback_query",)

    current = Mock()
    current.get_webhook_info = Mock(return_value={
        "ok": True,
        "result": {"url": url, "pending_update_count": 0,
                   "allowed_updates": ["callback_query", "message"]},
    })
    assert inspect_webhook(current, url).matches_expected is True

    # null / [] means "all update types" to Telegram.
    all_updates = Mock()
    all_updates.get_webhook_info = Mock(return_value={
        "ok": True, "result": {"url": url, "allowed_updates": None},
    })
    assert inspect_webhook(all_updates, url).matches_expected is True


def test_answer_callback_records_feedback():
    """A tap must always be acknowledged, or the button spins forever."""
    client = MockTelegramClient()
    client.answer_callback("cb-1", "Done")
    assert client.answered == [{"id": "cb-1", "text": "Done"}]


def test_webhook_endpoint_answers_callback(client, db, monkeypatch):
    """End-to-end: a POST /webhook tap must answer and flip the order.

    This is the regression test for "点接单没反应" -- a real tap must both
    acknowledge the user AND move the order to processing.
    """
    from app.constants import ORDER_STATUS_PENDING
    from app.db.models.order import Order
    import app.api.telegram as tg_api

    order = Order(order_number="ORD-CB", currency="INR",
                  order_status=ORDER_STATUS_PENDING, telegram_chat_id="999")
    db.add(order)
    db.commit()

    answered: list[str] = []

    class SpyClient(MockTelegramClient):
        def answer_callback(self, cid, text="", show_alert=False):
            answered.append(text)
            return super().answer_callback(cid, text, show_alert)

    monkeypatch.setattr(tg_api, "get_telegram_client", lambda db, dry_run=False: SpyClient())
    monkeypatch.setattr(settings, "TELEGRAM_MESSAGE_LANGUAGE", "zh-CN")

    resp = client.post("/api/telegram/webhook", json={
        "callback_query": {
            "id": "cb-1",
            "from": {"id": 555, "username": "worker"},
            "message": {"id": 42, "chat": {"id": 999}},
            "data": "accept:ORD-CB",
        }
    }, headers={"X-Telegram-Bot-Api-Secret-Token": settings.TELEGRAM_WEBHOOK_SECRET})

    assert resp.status_code == 200
    # The user got an acknowledgement...
    assert answered, "callback was never acknowledged"
    db.expire_all()
    # ...and the order actually moved.
    db.refresh(order)
    assert order.order_status == "processing"


def test_product_type_requires_name(db):
    """Products are pure names now: nothing but `name` (+ is_active)."""
    from app.db.models.product import Product

    p = Product(name="Netflix", is_active=True)
    db.add(p)
    db.commit()
    db.refresh(p)
    assert p.name == "Netflix"
    # All the old rule-engine / default columns are gone for good.
    for attr in ("require_amount", "require_email", "require_password",
                 "allow_screenshot", "code", "default_currency",
                 "default_login_method"):
        assert not hasattr(p, attr), attr


def test_selecting_product_fills_order_name(db):
    """Picking a type in the dropdown must surface its name in the order."""
    from app.constants import ROLE_ADMIN
    from app.core.security import hash_password
    from app.db.models.product import Product
    from app.db.models.user import User
    from app.schemas.order import OrderCreate
    from app.services.orders import create_order

    admin = User(username="a1", password_hash=hash_password("x"), role=ROLE_ADMIN, is_active=True)
    db.add(admin)
    p = Product(name="Netflix", is_active=True)
    db.add(p)
    db.commit()
    db.refresh(p)
    db.refresh(admin)

    order = create_order(db, OrderCreate(product_id=p.id, amount="50"), admin)
    db.refresh(order)
    assert order.product_name_snapshot == "Netflix"
    # A type must not silently change the login method anymore.
    assert order.login_method is None

    explicit = create_order(db, OrderCreate(product_id=p.id, product_name="Custom", amount="50"), admin)
    assert explicit.product_name_snapshot == "Custom"

    none_selected = create_order(db, OrderCreate(amount="10"), admin)
    assert none_selected.product_name_snapshot is None


def test_inactive_product_rejected(db):
    from app.constants import ROLE_ADMIN
    from app.core.security import hash_password
    from app.db.models.product import Product
    from app.db.models.user import User
    from app.schemas.order import OrderCreate
    from app.services.orders import create_order

    admin = User(username="a2", password_hash=hash_password("x"), role=ROLE_ADMIN, is_active=True)
    db.add(admin)
    p = Product(name="Retired", is_active=False)
    db.add(p)
    db.commit()
    db.refresh(p)
    db.refresh(admin)

    with pytest.raises(ValueError, match="product_inactive"):
        create_order(db, OrderCreate(product_id=p.id, amount="5"), admin)