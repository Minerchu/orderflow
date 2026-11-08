import pytest
from unittest.mock import Mock

from app.config import settings
from app.core.security import encrypt_secret
from app.db.models.order import OrderAttachment
from app.db.models.telegram import TelegramOutbox
from app.services.orders import send_order_to_telegram
from app.services.telegram_bot import (
    build_telegram_order_message, render_order_message, send_order_to_chat,
    TelegramSendError,
)
from app.constants import ORDER_STATUS_COMPLETED, ORDER_STATUS_PENDING, ORDER_STATUS_PROCESSING
from app.db.models.order import Order
from app.services.telegram_bot import MockTelegramClient, handle_callback, parse_callback_data


@pytest.fixture
def display_defaults(monkeypatch):
    monkeypatch.setattr(settings, "SHOW_ORDER_ID_IN_GROUP", False)
    monkeypatch.setattr(settings, "SHOW_CREDENTIALS_IN_GROUP", True)
    monkeypatch.setattr(settings, "SHOW_PASSWORD_IN_GROUP", True)
    monkeypatch.setattr(settings, "TELEGRAM_MESSAGE_LANGUAGE", "en")


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_only_email_note_rendered(empty, display_defaults):
    order = Order(order_number="ORD-PRIVATE", email="buyer@example.test", note="code send",
                  product_name_snapshot=empty, account=empty, login_method=empty)
    assert build_telegram_order_message(order) == "Order: ORD-PRIVATE\nEmail: buyer@example.test\nNote: code send"


def test_password_and_security_switches(display_defaults, monkeypatch):
    order = Order(order_number="ORD-PW", account="customer", password_encrypted=encrypt_secret("test-password"))
    assert build_telegram_order_message(order) == "Order: ORD-PW\nAccount: customer\nPassword: test-password"
    monkeypatch.setattr(settings, "SHOW_PASSWORD_IN_GROUP", False)
    monkeypatch.setattr(settings, "SHOW_CREDENTIALS_IN_GROUP", False)
    assert build_telegram_order_message(order) == "Order: ORD-PW"


def test_qr_scan_login_method_rendered(display_defaults):
    order = Order(order_number="ORD-QR", login_method="qr_scan")
    text = build_telegram_order_message(order)
    assert "Login Method: QR Scan" in text


def _photos(order, monkeypatch, count=1):
    order.attachments = [OrderAttachment(storage_key=f"key-{i}", original_filename=f"original-{i}.png",
                                        mime_type="image/png") for i in range(count)]
    monkeypatch.setattr("app.services.storage.get_storage", lambda: Mock(get_bytes=Mock(return_value=b"image")))


def test_amount_is_bold_and_leads_the_card(display_defaults):
    from decimal import Decimal

    order = Order(order_number="ORD-AMT", currency="INR", amount=Decimal("1390.00"),
                  note="hello")
    text = build_telegram_order_message(order)
    # Bold, own line, and before every other business field.
    assert text.startswith("<b>💰 Amount: 1390.00 INR</b>")
    assert text.index("Amount:") < text.index("Order:")


def test_status_banner_uses_html_bold_not_markdown(display_defaults):
    order = Order(order_number="ORD-ST", currency="INR", order_status="failed")
    text = render_order_message(order)
    assert text.startswith("<b>🔴 Failed</b>")
    # Markdown markers used to leak into Telegram as literal asterisks because
    # no parse_mode was set.
    assert "**" not in text


def test_free_text_is_html_escaped(display_defaults, monkeypatch):
    from decimal import Decimal

    monkeypatch.setattr(settings, "SHOW_CREDENTIALS_IN_GROUP", True)
    order = Order(order_number="ORD-ESC", currency="INR", amount=Decimal("10"),
                  note="<script>&", account_info="user <a> & pass")
    text = build_telegram_order_message(order)
    assert "&lt;script&gt;&amp;" in text
    assert "user &lt;a&gt; &amp; pass" in text
    assert "<script>" not in text


def test_image_name_and_draft_button(display_defaults, monkeypatch):
    order = Order(order_number="ORD-IMAGE", product_name_snapshot="Screenshot title", order_status="draft")
    _photos(order, monkeypatch)
    client = MockTelegramClient()
    result = send_order_to_chat(order, client, "999")
    assert result.message_id == "1"
    # A photo anchor must be flagged as media so later edits use
    # editMessageCaption (editMessageText is rejected on media messages).
    assert result.is_media is True
    assert len(client.sent) == 1
    # The status banner leads, the business fields follow.
    caption = client.sent[0]["caption"]
    assert caption.startswith("<b>")
    assert "Draft" in caption
    assert caption.endswith("Product: Screenshot title")
    assert client.sent[0]["filename"] == "original-0.png"
    assert client.sent[0]["reply_markup"][0][0]["callback_data"] == "accept:ORD-IMAGE"


def test_image_order_overlong_caption_still_has_buttons(display_defaults, monkeypatch):
    """Regression: an image order whose text exceeds the 1024-unit caption
    limit must still publish a clickable accept button (on a follow-up text
    message) -- previously the buttons were simply dropped."""
    order = Order(order_number="ORD-IMGLONG", order_status="draft",
                  note="长" * 1200, product_name_snapshot="Big")
    _photos(order, monkeypatch)
    client = MockTelegramClient()
    result = send_order_to_chat(order, client, "999")

    # First: the photo without a caption. Then: a text message WITH the button.
    photos = [m for m in client.sent if m["type"] == "photo"]
    texts = [m for m in client.sent if m["type"] == "message"]
    assert photos and texts
    assert texts[-1]["reply_markup"][0][0]["callback_data"] == "accept:ORD-IMGLONG"
    # The anchor is a text message, so it is NOT media.
    assert result.is_media is False
    assert result.message_id == texts[-1]["message_id"]



def test_multi_photo_failure_not_success(db, display_defaults, monkeypatch):
    order = Order(order_number="ORD-PARTIAL", product_name_snapshot="Photos", order_status="draft")
    _photos(order, monkeypatch, 2)
    db.add(order)
    db.commit()
    client = MockTelegramClient()
    original = client.send_photo
    def fail_second(*args, **kwargs):
        if client.sent:
            return {"ok": False, "description": "secret-token-must-not-leak"}
        return original(*args, **kwargs)
    client.send_photo = fail_second
    ok, error_code = send_order_to_telegram(db, order, "999", client)
    assert ok is False
    # The raw Telegram description must never surface to the caller.
    assert "secret-token" not in error_code
    db.refresh(order)
    assert order.order_status == "draft"
    assert order.telegram_send_status == "failed"
    assert order.telegram_message_id is None
    # A failed send must not bind the order to a chat: only a successful send
    # records telegram_chat_id (otherwise a typo/wrong group poisons the order).
    assert order.telegram_chat_id is None
    assert client.sent[0]["reply_markup"] is None
    assert db.query(TelegramOutbox).one().last_error == error_code


@pytest.mark.parametrize("response,expected", [
    ({"ok": False, "error_code": 400, "description": "Bad Request: chat not found"},
     "telegram_chat_not_found"),
    ({"ok": False, "error_code": 403, "description": "Forbidden: bot was blocked by the user"},
     "telegram_bot_blocked"),
    ({"ok": False, "error_code": 403, "description": "Forbidden: not enough rights to send text messages"},
     "telegram_bot_not_admin"),
    ({"ok": False, "error_code": 403, "description": "Forbidden: bot have no rights to send a message"},
     "telegram_send_forbidden"),
    ({"ok": False, "error_code": 401, "description": "Unauthorized"},
     "telegram_unauthorized"),
    ({"ok": False, "error_code": 429, "description": "Too Many Requests"},
     "telegram_rate_limited"),
    ({"ok": False, "description": "chat not found"}, "telegram_chat_not_found"),
    ({"ok": False}, "telegram_send_failed"),
])
def test_failure_reason_is_specific(response, expected, display_defaults):
    """A wrong chat id / blocked bot must not be reported as a generic failure."""
    order = Order(note="hi", order_status="draft", order_number="ORD-DIAG")
    client = Mock(send_message=Mock(return_value=response))
    with pytest.raises(TelegramSendError) as exc:
        send_order_to_chat(order, client, "-100123")
    assert str(exc.value) == expected


@pytest.mark.parametrize("response", [{"ok": False}, {"ok": True, "result": {}},
                                      {"ok": True, "result": {"message_id": None}},
                                      {"ok": True, "result": {"message_id": 0}}])
def test_invalid_send_response_rejected(response, display_defaults):
    order = Order(note="test", order_status="draft", order_number="ORD-INVALID")
    with pytest.raises(TelegramSendError):
        send_order_to_chat(order, Mock(send_message=Mock(return_value=response)), "999")


@pytest.mark.parametrize("with_photo", [False, True])
def test_long_text_not_truncated(with_photo, display_defaults, monkeypatch):
    order = Order(note="长内容" * 4000, order_status="draft", order_number="ORD-LONG")
    if with_photo:
        _photos(order, monkeypatch)
    client = MockTelegramClient()
    send_order_to_chat(order, client, "999")
    messages = [m for m in client.sent if m["type"] == "message"]
    assert "".join(m["text"] for m in messages) == render_order_message(order)
    assert all(len(m["text"].encode("utf-16-le")) // 2 <= 4096 for m in messages)
    assert messages[-1]["reply_markup"][0][0]["callback_data"] == "accept:ORD-LONG"
    assert all(not m["reply_markup"] for m in messages[:-1])


@pytest.mark.parametrize("show_id", [False, True])
def test_empty_order_rejected(db, display_defaults, monkeypatch, show_id):
    monkeypatch.setattr(settings, "SHOW_ORDER_ID_IN_GROUP", show_id)
    order = Order(order_number="ORD-EMPTY", order_status="draft")
    db.add(order)
    db.commit()
    client = MockTelegramClient()
    ok, error_code = send_order_to_telegram(db, order, "999", client)
    assert ok is False
    assert not client.sent
    assert order.order_status == "draft"
    assert order.telegram_send_status == "failed"


def test_accept_by_any_member(db):
    o = Order(order_number="ORD-X", currency="INR", order_status=ORDER_STATUS_PENDING,
              telegram_chat_id="999")
    db.add(o)
    db.commit()
    db.refresh(o)
    client = MockTelegramClient()
    ctx = parse_callback_data("accept:ORD-X")
    ctx.chat_id = "999"
    ctx.user_id = "tguser1"
    ctx.username = "bob"
    res = handle_callback(db, ctx, client)
    assert res["ok"]
    db.refresh(o)
    assert o.order_status == ORDER_STATUS_PROCESSING
    assert o.accepted_by_user_id is not None


def test_non_allowed_chat_rejected(db):
    o = Order(order_number="ORD-Y", currency="INR", order_status=ORDER_STATUS_PENDING,
              telegram_chat_id="999")
    db.add(o)
    db.commit()
    db.refresh(o)
    client = MockTelegramClient()
    ctx = parse_callback_data("accept:ORD-Y")
    ctx.chat_id = "888"
    ctx.user_id = "x"
    res = handle_callback(db, ctx, client)
    assert res["ok"] is False
    assert res["detail"] == "access_denied"


def test_only_acceptor_or_admin_completes(db):
    o = Order(order_number="ORD-Z", currency="INR", order_status=ORDER_STATUS_PENDING,
              telegram_chat_id="999")
    db.add(o)
    db.commit()
    db.refresh(o)
    client = MockTelegramClient()
    c1 = parse_callback_data("accept:ORD-Z")
    c1.chat_id = "999"
    c1.user_id = "tguser1"
    assert handle_callback(db, c1, client)["ok"]

    # another member tries complete -> forbidden
    c2 = parse_callback_data("complete:ORD-Z")
    c2.chat_id = "999"
    c2.user_id = "tguser2"
    res = handle_callback(db, c2, client)
    assert res["ok"] is False
    assert res["detail"] == "forbidden"

    # acceptor completes -> ok
    c3 = parse_callback_data("complete:ORD-Z")
    c3.chat_id = "999"
    c3.user_id = "tguser1"
    assert handle_callback(db, c3, client)["ok"]
    db.refresh(o)
    assert o.order_status == ORDER_STATUS_COMPLETED


def test_fake_callback_data_no_bypass(db):
    client = MockTelegramClient()
    ctx = parse_callback_data("accept:NONEXISTENT")
    ctx.chat_id = "999"
    ctx.user_id = "x"
    res = handle_callback(db, ctx, client)
    assert res["ok"] is False
    assert res["detail"] == "order_not_found"


def test_concurrent_accept_only_one(db):
    o = Order(order_number="ORD-C", currency="INR", order_status=ORDER_STATUS_PENDING,
              telegram_chat_id="999")
    db.add(o)
    db.commit()
    db.refresh(o)
    client = MockTelegramClient()
    c1 = parse_callback_data("accept:ORD-C")
    c1.chat_id = "999"
    c1.user_id = "u1"
    c2 = parse_callback_data("accept:ORD-C")
    c2.chat_id = "999"
    c2.user_id = "u2"
    r1 = handle_callback(db, c1, client)
    r2 = handle_callback(db, c2, client)
    assert (r1["ok"] and not r2["ok"]) or (r2["ok"] and not r1["ok"])
    db.refresh(o)
    assert o.accepted_by_user_id is not None
    assert o.order_status == ORDER_STATUS_PROCESSING


def test_admin_can_complete_any(db):
    o = Order(order_number="ORD-A", currency="INR", order_status=ORDER_STATUS_PENDING,
              telegram_chat_id="999")
    db.add(o)
    db.commit()
    db.refresh(o)
    client = MockTelegramClient()
    c1 = parse_callback_data("accept:ORD-A")
    c1.chat_id = "999"
    c1.user_id = "u1"
    handle_callback(db, c1, client)
    # admin tg id
    c2 = parse_callback_data("complete:ORD-A")
    c2.chat_id = "999"
    c2.user_id = "admin_tg"
    # mark admin tg
    from app.db.models.user import User

    admin = User(username="admin_tg_user", password_hash="x", role="admin",
                 telegram_user_id="admin_tg")
    db.add(admin)
    db.commit()
    res = handle_callback(db, c2, client)
    assert res["ok"]
    db.refresh(o)
    assert o.order_status == ORDER_STATUS_COMPLETED
