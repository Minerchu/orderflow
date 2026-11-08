"""Regression tests for the reported production bugs (2026-10).

Covers:
  1. image orders: the group message must carry a working accept button, and
     later state changes must edit the *caption* (photos reject editMessageText)
  2. the failure-reason picker must offer a cancel path and restore buttons
  3. admin status changes must push the new state to the group automatically
  4. admin edits to group-visible fields must also sync
"""
import pytest
from unittest.mock import Mock

from app.config import settings
from app.db.models.order import Order, OrderAttachment
from app.services.orders import send_order_to_telegram, update_order, sync_order_to_telegram
from app.services.telegram_bot import (
    MockTelegramClient, handle_callback, parse_callback_data,
    build_fail_reason_keyboard, _refresh_group_message,
)
from app.schemas.order import OrderUpdate


@pytest.fixture
def display_defaults(monkeypatch):
    monkeypatch.setattr(settings, "SHOW_ORDER_ID_IN_GROUP", False)
    monkeypatch.setattr(settings, "SHOW_CREDENTIALS_IN_GROUP", True)
    monkeypatch.setattr(settings, "SHOW_PASSWORD_IN_GROUP", True)
    monkeypatch.setattr(settings, "TELEGRAM_MESSAGE_LANGUAGE", "zh-CN")


def _photos(order, monkeypatch, count=1):
    order.attachments = [
        OrderAttachment(storage_key=f"k{i}", original_filename=f"o{i}.png", mime_type="image/png")
        for i in range(count)
    ]
    monkeypatch.setattr("app.services.storage.get_storage",
                        lambda: Mock(get_bytes=Mock(return_value=b"image")))


# ---- 1. image orders ------------------------------------------------------

def test_media_flag_persisted_on_send(db, display_defaults, monkeypatch):
    """An image order must remember that its anchor message is media."""
    order = Order(order_number="ORD-M1", product_name_snapshot="P", order_status="draft")
    _photos(order, monkeypatch)
    db.add(order)
    db.commit()
    client = MockTelegramClient()
    ok, err = send_order_to_telegram(db, order, "999", client)
    assert ok is True, err
    db.refresh(order)
    assert order.telegram_message_is_media is True


def test_media_refresh_uses_caption_edit(db, display_defaults, monkeypatch):
    """Refreshing an image order must call editMessageCaption, not
    editMessageText -- Telegram rejects the latter on media messages."""
    order = Order(order_number="ORD-M2", product_name_snapshot="P",
                  order_status="processing", telegram_chat_id="999",
                  telegram_message_id="42", telegram_message_is_media=True)
    db.add(order)
    db.commit()
    client = MockTelegramClient()
    ok = _refresh_group_message(db, order, client)
    assert ok is True
    assert client.caption_edits, "expected an editMessageCaption call"
    assert not client.text_edits, "editMessageText must not be used on media"


def test_text_refresh_uses_text_edit(db, display_defaults):
    order = Order(order_number="ORD-M3", note="x", order_status="processing",
                  telegram_chat_id="999", telegram_message_id="43",
                  telegram_message_is_media=False)
    db.add(order)
    db.commit()
    client = MockTelegramClient()
    ok = _refresh_group_message(db, order, client)
    assert ok is True
    assert client.text_edits
    assert not client.caption_edits


def test_media_caption_trimmed_to_1024(db, display_defaults):
    """A long status block must be trimmed so editMessageCaption does not fail."""
    order = Order(order_number="ORD-M4", note="长" * 800, order_status="processing",
                  telegram_chat_id="999", telegram_message_id="44",
                  telegram_message_is_media=True)
    db.add(order)
    db.commit()
    client = MockTelegramClient()
    _refresh_group_message(db, order, client)
    caption = client.caption_edits[0]["caption"]
    assert len(caption.encode("utf-16-le")) // 2 <= 1024


# ---- 2. failure-reason picker -------------------------------------------

def test_fail_reason_keyboard_has_cancel():
    kb = build_fail_reason_keyboard("ORD-F1", lang="zh-CN")
    flat = [b for row in kb for b in row]
    actions = {b["callback_data"] for b in flat}
    assert "cancelfail:ORD-F1" in actions
    # All four reasons remain available.
    assert sum(1 for c in actions if c.startswith("fail:ORD-F1:")) == 4


def test_cancel_fail_restores_buttons(db, display_defaults):
    """Cancelling the reason picker must leave the order untouched and restore
    the normal action buttons on the group message."""
    order = Order(order_number="ORD-F2", note="x", order_status="processing",
                  telegram_chat_id="999", telegram_message_id="77")
    db.add(order)
    db.commit()
    client = MockTelegramClient()
    ctx = parse_callback_data("cancelfail:ORD-F2")
    ctx.chat_id = "999"
    ctx.user_id = "555"
    result = handle_callback(db, ctx, client)
    assert result.get("ok") is True
    db.refresh(order)
    # No state change: it is still processing.
    assert order.order_status == "processing"
    # Buttons were rewritten.
    assert client.text_edits


def test_fail_reason_selection_records_reason(db, display_defaults, monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_ANY_GROUP_MEMBER_TO_FAIL", True)
    order = Order(order_number="ORD-F3", note="x", order_status="processing",
                  telegram_chat_id="999", telegram_message_id="78")
    db.add(order)
    db.commit()
    client = MockTelegramClient()
    ctx = parse_callback_data("fail:ORD-F3:invalid_account")
    ctx.chat_id = "999"
    ctx.user_id = "666"
    ctx.username = "tester"
    result = handle_callback(db, ctx, client)
    assert result.get("ok") is True, result
    db.refresh(order)
    assert order.order_status == "failed"
    assert order.failure_reason == "invalid_account"
    # The group card must reflect the new state.
    assert client.text_edits


# ---- 3/4. auto-sync on admin changes ------------------------------------

def test_admin_status_change_syncs_group(db, display_defaults, monkeypatch):
    """Changing status from the admin UI must push to the group automatically
    (no manual 're-send to group' step)."""
    admin = _mk_admin(db)
    order = Order(order_number="ORD-S1", note="x", order_status="processing",
                  telegram_chat_id="999", telegram_message_id="88")
    order.created_by_user_id = admin.id
    db.add(order)
    db.commit()

    client = MockTelegramClient()
    monkeypatch.setattr("app.services.telegram_bot.get_telegram_client",
                        lambda d, dry_run=False: client)

    update_order(db, order, OrderUpdate(order_status="completed"), admin)
    db.refresh(order)
    assert order.order_status == "completed"
    assert client.text_edits, "status change should have synced to the group"


def test_admin_field_edit_syncs_group(db, display_defaults, monkeypatch):
    admin = _mk_admin(db)
    order = Order(order_number="ORD-S2", note="old", order_status="pending",
                  telegram_chat_id="999", telegram_message_id="89")
    order.created_by_user_id = admin.id
    db.add(order)
    db.commit()

    client = MockTelegramClient()
    monkeypatch.setattr("app.services.telegram_bot.get_telegram_client",
                        lambda d, dry_run=False: client)

    update_order(db, order, OrderUpdate(note="new note"), admin)
    db.refresh(order)
    assert order.note == "new note"
    assert client.text_edits


def test_sync_skips_when_never_sent(db, display_defaults):
    admin = _mk_admin(db)
    order = Order(order_number="ORD-S3", note="x", order_status="draft")
    order.created_by_user_id = admin.id
    db.add(order)
    db.commit()
    ok, reason = sync_order_to_telegram(db, order)
    assert ok is False
    assert reason == "not_sent"


def test_no_change_does_not_sync(db, display_defaults, monkeypatch):
    """Saving an unchanged form must not spam the group with edits."""
    admin = _mk_admin(db)
    order = Order(order_number="ORD-S4", note="same", order_status="pending",
                  telegram_chat_id="999", telegram_message_id="90")
    order.created_by_user_id = admin.id
    db.add(order)
    db.commit()

    client = MockTelegramClient()
    monkeypatch.setattr("app.services.telegram_bot.get_telegram_client",
                        lambda d, dry_run=False: client)

    update_order(db, order, OrderUpdate(note="same"), admin)
    assert not client.text_edits


# ---- 5. the two buttons must actually differ ---------------------------

def test_send_endpoint_syncs_in_place(db, display_defaults, monkeypatch):
    """`/send` on an already-delivered order must edit the existing message
    rather than post a duplicate -- that is what 「同步到群」 promises."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db.session import get_db

    admin = _mk_admin(db, username="admin_send", password="pw")
    order = Order(order_number="ORD-B1", note="x", order_status="pending",
                  telegram_chat_id="999", telegram_message_id="111")
    order.created_by_user_id = admin.id
    db.add(order)
    db.commit()
    order_id = order.id

    client_tg = MockTelegramClient()
    # api/orders.py binds get_telegram_client at import time, so patch there;
    # sync_order_to_telegram() imports it lazily, so patch that module too.
    monkeypatch.setattr("app.api.orders.get_telegram_client",
                        lambda d, dry_run=False: client_tg)
    monkeypatch.setattr("app.services.telegram_bot.get_telegram_client",
                        lambda d, dry_run=False: client_tg)

    token = _login_admin(db, "admin_send", "pw")
    with TestClient(app) as c:
        app.dependency_overrides[get_db] = lambda: db
        r = c.post(f"/api/orders/{order_id}/send", headers={"Authorization": f"Bearer {token}"})
        app.dependency_overrides.clear()
    assert r.status_code == 200, r.text
    # In-place: an edit happened, and NO new send was made.
    assert client_tg.text_edits
    assert not client_tg.sent


def test_retry_send_posts_new_message(db, display_defaults, monkeypatch):
    """`/retry-send` must post a NEW message (the old one is abandoned)."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db.session import get_db

    admin = _mk_admin(db, username="admin_retry", password="pw")
    order = Order(order_number="ORD-B2", note="x", order_status="pending",
                  telegram_chat_id="999", telegram_message_id="222")
    order.created_by_user_id = admin.id
    db.add(order)
    db.commit()
    order_id = order.id

    client_tg = MockTelegramClient()
    monkeypatch.setattr("app.api.orders.get_telegram_client",
                        lambda d, dry_run=False: client_tg)

    token = _login_admin(db, "admin_retry", "pw")
    with TestClient(app) as c:
        app.dependency_overrides[get_db] = lambda: db
        r = c.post(f"/api/orders/{order_id}/retry-send",
                   headers={"Authorization": f"Bearer {token}"})
        app.dependency_overrides.clear()
    assert r.status_code == 200, r.text
    # A brand-new message was posted.
    assert client_tg.sent


def _mk_admin(db, username="admin_t", password="x"):
    from app.core.security import hash_password
    from app.db.models.user import User
    u = db.query(User).filter(User.username == username).first()
    if u is not None:
        return u
    u = User(username=username, password_hash=hash_password(password),
             role="admin", is_active=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _login_admin(db, username, password) -> str:
    """Mint a session token the same way the login endpoint does."""
    from app.core.security import create_session_token
    from app.db.models.user import User
    u = db.query(User).filter(User.username == username).first()
    return create_session_token(u.id)

# ---- 6. failure picker must survive a deleted / stale group message -------

def test_fail_reason_picker_falls_back_to_new_message(db, display_defaults):
    """If the order card cannot be edited, post a standalone picker instead.

    This is the exact production symptom: the toast said "pick a reason" but
    no buttons appeared because editMessageReplyMarkup had been rejected.
    """
    from app.api.telegram import _show_fail_reason_picker

    order = Order(order_number="ORD-P1", note="x", order_status="processing",
                  telegram_chat_id="999", telegram_message_id="100")
    db.add(order)
    db.commit()

    class BrokenEdit(MockTelegramClient):
        def edit_message_reply_markup(self, *a, **kw):
            raise RuntimeError("telegram_message_not_found")

    client = BrokenEdit()
    ok, err = _show_fail_reason_picker(db, client, order, "999", "99")
    assert ok is True, err
    assert client.sent, "expected a standalone reason picker message"
    sent = client.sent[-1]
    assert sent["reply_markup"], "reason keyboard missing from fallback message"
    flat = [b for row in sent["reply_markup"] for b in row]
    assert any(b["callback_data"].startswith("fail:ORD-P1:") for b in flat)


def test_fail_reason_picker_uses_current_anchor_when_tap_is_stale(db, display_defaults):
    """A tap on an older duplicate should still update the current order card."""
    from app.api.telegram import _show_fail_reason_picker

    order = Order(order_number="ORD-P2", note="x", order_status="processing",
                  telegram_chat_id="999", telegram_message_id="100")
    db.add(order)
    db.commit()

    class OnlyStaleBroken(MockTelegramClient):
        def edit_message_reply_markup(self, chat_id, message_id, reply_markup=None):
            if str(message_id) == "99":
                raise RuntimeError("telegram_message_not_found")
            return super().edit_message_reply_markup(chat_id, message_id, reply_markup)

    client = OnlyStaleBroken()
    ok, err = _show_fail_reason_picker(db, client, order, "999", "99")
    assert ok is True, err
    assert client.edited, "expected an edit on the order's current anchor"
    assert client.edited[-1]["message_id"] == "100"
    assert not client.sent


def test_dispatch_deletes_standalone_picker_after_reason(db, display_defaults, monkeypatch):
    """A fallback picker message must disappear once the reason is recorded."""
    from app.api import telegram as telegram_api

    # Any group member may fail an order in this scenario; the test is about
    # picker cleanup, not about the permission matrix.
    monkeypatch.setattr(settings, "ALLOW_ANY_GROUP_MEMBER_TO_FAIL", True)

    order = Order(order_number="ORD-P3", note="x", order_status="processing",
                  telegram_chat_id="999", telegram_message_id="100")
    db.add(order)
    db.commit()

    client = MockTelegramClient()
    monkeypatch.setattr(telegram_api, "get_telegram_client",
                        lambda d, dry_run=False: client)

    body = {
        "callback_query": {
            "id": "cb-p3",
            "data": "fail:ORD-P3:other",
            "from": {"id": "555", "username": "worker"},
            "message": {"id": 777, "chat": {"id": 999}},
        }
    }
    telegram_api._dispatch(db, body)
    db.refresh(order)
    assert order.order_status == "failed"
    assert client.deleted and str(client.deleted[-1]["message_id"]) == "777"
