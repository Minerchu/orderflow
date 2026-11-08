"""The group message must remain a readable record of the order.

Regression cover for: "就算完成了订单，群里也看不出完成还是失败，按钮消失了
像完全没有存在过" -- the message text used to be written once at send time and
never touched again, so the group lost all history.
"""

import pytest

from app.constants import (
    ORDER_STATUS_COMPLETED,
    ORDER_STATUS_FAILED,
    ORDER_STATUS_PENDING,
    ORDER_STATUS_PROCESSING,
    ROLE_PARTNER,
)
from app.db.models.order import Order
from app.services.telegram_bot import (
    MockTelegramClient,
    build_keyboard,
    handle_callback,
    parse_callback_data,
    render_order_message,
    _refresh_group_message,
)


@pytest.fixture(autouse=True)
def chinese(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "TELEGRAM_MESSAGE_LANGUAGE", "zh-CN")
    monkeypatch.setattr(settings, "SHOW_ORDER_ID_IN_GROUP", False)
    monkeypatch.setattr(settings, "SHOW_CREDENTIALS_IN_GROUP", True)
    monkeypatch.setattr(settings, "SHOW_PASSWORD_IN_GROUP", True)


def test_status_banner_reflects_each_state():
    order = Order(order_number="ORD-S", note="n", order_status=ORDER_STATUS_PENDING)
    assert "等待接单" in render_order_message(order)

    order.order_status = ORDER_STATUS_PROCESSING
    assert "进行中" in render_order_message(order)

    order.order_status = ORDER_STATUS_COMPLETED
    assert "已完成" in render_order_message(order)

    order.order_status = ORDER_STATUS_FAILED
    assert "已失败" in render_order_message(order)


def test_completed_order_shows_who_and_when(db):
    """A finished order must still show status + actor, not just lose buttons."""
    from app.core.security import hash_password
    from app.db.models.user import User

    worker = User(username="zhangsan", password_hash=hash_password("x"),
                  role=ROLE_PARTNER, is_active=True)
    db.add(worker)
    db.commit()
    db.refresh(worker)

    order = Order(
        order_number="ORD-DONE", currency="INR", note="已处理",
        order_status=ORDER_STATUS_COMPLETED,
        telegram_chat_id="999", telegram_message_id="55",
        accepted_by_user_id=worker.id,
        completed_by_user_id=worker.id,
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    text = render_order_message(order, db)
    assert "已完成" in text
    assert "zhangsan" in text
    # The original business content is still there.
    assert "已处理" in text


def test_failed_order_shows_reason(db):
    order = Order(
        order_number="ORD-F", currency="INR", note="充值失败",
        order_status=ORDER_STATUS_FAILED,
        failure_reason="recharge_failed", telegram_chat_id="999",
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    text = render_order_message(order, db)
    assert "已失败" in text
    assert "充值失败" in text  # the reason, not a raw enum


def test_completed_order_keeps_record_and_offers_void(db):
    """A finished order keeps its record AND lets mistakes be corrected."""
    order = Order(order_number="ORD-K", currency="INR", note="x",
                  order_status=ORDER_STATUS_COMPLETED, telegram_chat_id="999")
    db.add(order)
    db.commit()
    db.refresh(order)

    # Record stays visible...
    assert "已完成" in render_order_message(order, db)
    # ...and the handler can still void it.
    kb = build_keyboard(order)
    assert kb and kb[0][0]["callback_data"] == "void:ORD-K"


def test_callback_rewrites_group_message(db):
    """End-to-end: pressing 接单 must edit the message, not only its buttons."""
    order = Order(order_number="ORD-RW", currency="INR", note="测试",
                  order_status=ORDER_STATUS_PENDING,
                  telegram_chat_id="999", telegram_message_id="42")
    db.add(order)
    db.commit()

    client = MockTelegramClient()
    ctx = parse_callback_data("accept:ORD-RW")
    ctx.chat_id, ctx.user_id, ctx.username = "999", "u1", "worker"
    assert handle_callback(db, ctx, client)["ok"]

    # The message text was updated in place...
    assert client.text_edits, "group message text was never updated"
    edit = client.text_edits[-1]
    assert "进行中" in edit["text"]
    assert "worker" in edit["text"] or "u1" in edit["text"]
    # ...and the keyboard moved to the next step.
    assert edit["reply_markup"][0][0]["callback_data"] == f"complete:ORD-RW"


def test_refresh_falls_back_when_text_edit_fails(db):
    """A failed text edit must not stop the buttons from updating."""
    order = Order(order_number="ORD-FB", currency="INR", note="x",
                  order_status=ORDER_STATUS_PENDING,
                  telegram_chat_id="999", telegram_message_id="7")
    db.add(order)
    db.commit()

    class BrokenText(MockTelegramClient):
        def edit_message_text(self, *a, **kw):
            raise RuntimeError("can't parse entities")

    client = BrokenText()
    _refresh_group_message(db, order, client)
    assert client.edited, "keyboard refresh fallback did not run"


def test_buttons_have_emoji(monkeypatch):
    """Buttons should be scannable at a glance in a busy group."""
    from app.config import settings

    monkeypatch.setattr(settings, "TELEGRAM_MESSAGE_LANGUAGE", "zh-CN")
    order = Order(order_number="ORD-E", order_status=ORDER_STATUS_PENDING)

    accept = build_keyboard(order)[0][0]["text"]
    assert accept.startswith("✅")

    order.order_status = ORDER_STATUS_PROCESSING
    row = build_keyboard(order)[0]
    done, fail = row[0]["text"], row[1]["text"]
    assert done.startswith("✅")
    assert fail.startswith("❌")


def test_draft_image_order_can_be_accepted(db):
    """An image order that never flipped to pending (e.g. the initial send
    failed but the accept button is still offered) must be claimable -- this is
    what produced the 'not pending' error on image orders."""
    from app.db.models.order import OrderAttachment

    order = Order(order_number="ORD-DRAFTIMG", currency="INR", note="截图",
                  order_status=ORDER_STATUS_PENDING)  # build_keyboard shows accept
    order.attachments = [OrderAttachment(storage_key="k", original_filename="s.png",
                                         mime_type="image/png")]
    db.add(order)
    db.commit()
    db.refresh(order)
    # Simulate the order still sitting in draft (send failed / not flipped).
    order.order_status = "draft"
    db.commit()

    assert build_keyboard(order) is not None  # button is offered
    client = MockTelegramClient()
    ctx = parse_callback_data("accept:ORD-DRAFTIMG")
    ctx.chat_id, ctx.user_id, ctx.username = "999", "u_img", "shooter"
    result = handle_callback(db, ctx, client)
    assert result["ok"], result
    db.refresh(order)
    assert order.order_status == ORDER_STATUS_PROCESSING
    assert order.accepted_by_user_id is not None
