"""Readable names in the group, and admin status override.

Two issues raised after the first live deploy:

* the group showed "接单人: tg_123456789" because auto-created accounts were
  named after the id instead of the person's Telegram handle
* an order marked failed could not be changed back -- the admin had no control
  at all, only the group could reopen it
"""

from datetime import datetime, timezone

import pytest
from decimal import Decimal

from app.constants import (
    ORDER_STATUS_CLOSED,
    ORDER_STATUS_COMPLETED,
    ORDER_STATUS_FAILED,
    ORDER_STATUS_PENDING,
    ORDER_STATUS_PROCESSING,
    ROLE_ADMIN,
    ROLE_PARTNER,
)
from app.core.security import hash_password
from app.db.models.order import Order, OrderEvent
from app.db.models.user import User
from app.schemas.order import OrderUpdate
from app.services.orders import update_order
from app.services.telegram_bot import (
    CallbackContext,
    MockTelegramClient,
    _display_name,
    _ensure_telegram_user,
    build_keyboard,
    handle_callback,
    parse_callback_data,
    render_order_message,
)


@pytest.fixture(autouse=True)
def chinese(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "TELEGRAM_MESSAGE_LANGUAGE", "zh-CN")


def _ctx(chat_id="999", user_id="42", username="zhangsan"):
    return CallbackContext(action="accept", order_number="", chat_id=chat_id,
                           user_id=user_id, username=username)


def test_auto_account_uses_telegram_handle_not_id(db):
    """The group must show @zhangsan, not tg_42."""
    ctx = _ctx()
    uid = _ensure_telegram_user(db, ctx)
    db.commit()

    user = db.get(User, uid)
    assert user.username == "zhangsan", "placeholder id leaked into the username"
    assert not user.username.startswith("tg_")


def test_existing_placeholder_is_upgraded(db):
    """Rows created before the fix still read tg_42; fix them on next action."""
    user = User(username="tg_42", password_hash="__telegram__", role=ROLE_PARTNER,
                telegram_user_id="42", telegram_username="zhangsan", is_active=True)
    db.add(user)
    db.commit()

    _ensure_telegram_user(db, _ctx())
    db.commit()
    db.refresh(user)
    assert user.username == "zhangsan"


def test_real_admin_name_is_not_overwritten(db):
    """Never rename an account the admin created by hand."""
    user = User(username="wangfang", password_hash=hash_password("x"), role=ROLE_PARTNER,
                telegram_user_id="42", telegram_username="wf_handle", is_active=True)
    db.add(user)
    db.commit()

    _ensure_telegram_user(db, _ctx(username="wf_handle"))
    db.commit()
    db.refresh(user)
    assert user.username == "wangfang"


def test_group_message_shows_handle_for_auto_accounts(db):
    auto = User(username="tg_42", password_hash="__telegram__", role=ROLE_PARTNER,
                telegram_user_id="42", telegram_username="zhangsan", is_active=True)
    db.add(auto)
    db.commit()
    db.refresh(auto)

    order = Order(order_number="ORD-N", currency="INR", amount=Decimal("1390"),
                  order_status=ORDER_STATUS_PROCESSING, accepted_by_user_id=auto.id)
    db.add(order)
    db.commit()
    db.refresh(order)

    text = render_order_message(order, db)
    assert "@zhangsan" in text
    assert "tg_42" not in text


def test_missing_username_falls_back_to_id(db):
    user = User(username="tg_99", password_hash="__telegram__", role=ROLE_PARTNER,
                telegram_user_id="99", telegram_username=None, is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    # Nothing better available: show something rather than nothing.
    assert _display_name(None, user.id, db) in ("tg_99", "99")


# ---------------- Admin status override ----------------

def _admin(db):
    u = User(username="boss", password_hash=hash_password("x"), role=ROLE_ADMIN,
             is_active=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _order(db, status=ORDER_STATUS_FAILED):
    o = Order(order_number="ORD-S", currency="INR", amount=Decimal("1390"),
              order_status=status, failure_reason="other",
              failed_by_user_id=1, failed_at=datetime.now(timezone.utc))
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


def test_admin_can_unstick_a_failed_order(db):
    admin = _admin(db)
    order = _order(db)

    update_order(db, order, OrderUpdate(order_status=ORDER_STATUS_COMPLETED), admin)
    db.commit()
    db.refresh(order)

    assert order.order_status == ORDER_STATUS_COMPLETED
    # Completion implies confirmation, and the stale failure data is cleared.
    assert order.amount_confirmed is True
    assert order.failure_reason is None
    assert order.failed_at is None


def test_failed_override_records_a_reason_and_resets_confirmation(db):
    admin = _admin(db)
    order = _order(db, status=ORDER_STATUS_COMPLETED)

    update_order(
        db, order,
        OrderUpdate(order_status=ORDER_STATUS_FAILED, failure_reason="recharge_failed"),
        admin,
    )
    db.commit()
    db.refresh(order)

    assert order.order_status == ORDER_STATUS_FAILED
    assert order.failure_reason == "recharge_failed"
    # A voided order must not be settled.
    assert order.amount_confirmed is False


def test_override_to_pending_clears_the_whole_chain(db):
    admin = _admin(db)
    order = _order(db, status=ORDER_STATUS_COMPLETED)
    update_order(db, order, OrderUpdate(order_status=ORDER_STATUS_PENDING), admin)
    db.commit()
    db.refresh(order)

    assert order.order_status == ORDER_STATUS_PENDING
    assert order.accepted_by_user_id is None
    assert order.completed_by_user_id is None
    assert order.failure_reason is None
    assert order.amount_confirmed is False


def test_override_is_audited(db):
    admin = _admin(db)
    order = _order(db)
    update_order(db, order, OrderUpdate(order_status=ORDER_STATUS_CLOSED), admin)
    db.commit()

    events = db.query(OrderEvent).filter_by(order_id=order.id).all()
    assert any(e.event_type == "admin_status_change" for e in events)


def test_draft_cannot_be_set_via_override(db):
    admin = _admin(db)
    order = _order(db)
    with pytest.raises(ValueError):
        update_order(db, order, OrderUpdate(order_status="draft"), admin)


def test_partner_cannot_change_status(db):
    partner = User(username="p", password_hash=hash_password("x"), role=ROLE_PARTNER,
                   is_active=True)
    db.add(partner)
    db.commit()
    db.refresh(partner)
    order = _order(db)

    with pytest.raises(PermissionError):
        update_order(db, order, OrderUpdate(order_status=ORDER_STATUS_COMPLETED), partner)


def test_failed_order_keyboard_allows_reopen(db, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "ALLOW_ANY_GROUP_MEMBER_TO_REOPEN", True)
    order = _order(db)
    kb = build_keyboard(order)
    assert kb and kb[0][0]["callback_data"] == "reopen:ORD-S"