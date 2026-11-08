"""Per-amount sequence numbering and self-service voiding.

Two admin requirements are covered here:

1. Orders are created one per customer at the same amount (e.g. 1390), so the
   group should show 第 1 单 / 第 2 单 ...
2. Tapping 完成 is the confirmation -- no second manual step. If a handler taps
   it by mistake, they (or the admin) can void it, and the sequence must close
   the gap in every same-amount order.
"""

import pytest
from decimal import Decimal

from app.constants import (
    ORDER_STATUS_COMPLETED,
    ORDER_STATUS_FAILED,
    ORDER_STATUS_PENDING,
    ORDER_STATUS_PROCESSING,
)
from app.db.models.order import Order
from app.services.telegram_bot import (
    MockTelegramClient,
    build_sequence_map,
    handle_callback,
    parse_callback_data,
    render_order_message,
    sequence_for,
)


@pytest.fixture(autouse=True)
def chinese(monkeypatch):
    """Group messages are configured for Chinese in the deployment."""
    from app.config import settings

    monkeypatch.setattr(settings, "TELEGRAM_MESSAGE_LANGUAGE", "zh-CN")
    monkeypatch.setattr(settings, "SHOW_ORDER_ID_IN_GROUP", False)


def _make(db, number: str, amount: str, status: str, currency: str = "INR", msg_id=None):
    order = Order(
        order_number=number, currency=currency, amount=Decimal(amount),
        order_status=status, note="n",
        telegram_chat_id="999", telegram_message_id=msg_id,
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def test_sequence_numbers_per_amount(db):
    a1 = _make(db, "A1", "1390", ORDER_STATUS_PENDING)
    a2 = _make(db, "A2", "1390", ORDER_STATUS_PENDING)
    _make(db, "B1", "500", ORDER_STATUS_PENDING)

    assert sequence_for(db, a1) == 1
    assert sequence_for(db, a2) == 2
    # A different amount counts independently.
    assert sequence_for(db, db.execute(
        __import__("sqlalchemy").select(Order).where(Order.order_number == "B1")
    ).scalar_one()) == 1


def test_sequence_rendered_in_chinese_message(db):
    a1 = _make(db, "A1", "1390", ORDER_STATUS_PENDING)
    _make(db, "A2", "1390", ORDER_STATUS_PENDING)

    assert "第 1 单" in render_order_message(a1, db)


def test_failed_orders_are_excluded_from_sequence(db):
    """A voided order must not leave a hole in the numbering."""
    a1 = _make(db, "A1", "1390", ORDER_STATUS_PENDING)
    a2 = _make(db, "A2", "1390", ORDER_STATUS_PENDING)
    a3 = _make(db, "A3", "1390", ORDER_STATUS_PENDING)

    assert [sequence_for(db, o) for o in (a1, a2, a3)] == [1, 2, 3]

    a2.order_status = ORDER_STATUS_FAILED
    db.commit()

    # a2 drops out, a3 shifts down.
    assert sequence_for(db, a1) == 1
    assert sequence_for(db, a2) is None
    assert sequence_for(db, a3) == 2


def test_reopened_order_reclaims_its_slot(db):
    a1 = _make(db, "A1", "1390", ORDER_STATUS_PENDING)
    a2 = _make(db, "A2", "1390", ORDER_STATUS_FAILED)
    assert sequence_for(db, a2) is None

    a2.order_status = ORDER_STATUS_PENDING
    db.commit()
    assert sequence_for(db, a2) == 2
    assert sequence_for(db, a1) == 1


def test_currency_sequences_are_independent(db):
    inr1 = _make(db, "I1", "100", ORDER_STATUS_PENDING, currency="INR")
    usd1 = _make(db, "U1", "100", ORDER_STATUS_PENDING, currency="USD")
    assert sequence_for(db, inr1) == 1
    assert sequence_for(db, usd1) == 1


def test_orders_without_amount_have_no_sequence(db):
    order = Order(order_number="NOAMT", currency="INR", note="n",
                  order_status=ORDER_STATUS_PENDING)
    db.add(order)
    db.commit()
    db.refresh(order)
    assert sequence_for(db, order) is None


def _accept(db, order, tg_user="u1", username="worker"):
    """Drive an order from pending to processing (creates an acceptor)."""
    client = MockTelegramClient()
    ctx = parse_callback_data(f"accept:{order.order_number}")
    ctx.chat_id, ctx.user_id, ctx.username = "999", tg_user, username
    handle_callback(db, ctx, client)
    db.refresh(order)
    return client


def _complete(db, order, tg_user="u1", username="worker"):
    client = MockTelegramClient()
    ctx = parse_callback_data(f"complete:{order.order_number}")
    ctx.chat_id, ctx.user_id, ctx.username = "999", tg_user, username
    result = handle_callback(db, ctx, client)
    db.refresh(order)
    return result, client


def test_completing_auto_confirms_amount(db):
    """No second manual confirmation step — the admin asked for this."""
    order = _make(db, "C1", "1390", ORDER_STATUS_PENDING)
    assert order.amount_confirmed is False

    _accept(db, order)
    db.refresh(order)
    assert order.order_status == ORDER_STATUS_PROCESSING

    result, _ = _complete(db, order)
    assert result["ok"]
    assert order.order_status == ORDER_STATUS_COMPLETED
    # Completion itself is the confirmation.
    assert order.amount_confirmed is True


def test_acceptor_can_void_completed_order(db):
    order = _make(db, "V1", "1390", ORDER_STATUS_PENDING, msg_id="1")

    _accept(db, order, "tgacc", "zhang")
    result, _ = _complete(db, order, "tgacc", "zhang")
    assert result["ok"]
    assert order.order_status == ORDER_STATUS_COMPLETED
    assert order.amount_confirmed is True

    # The same person realises the mistake and voids it.
    client = MockTelegramClient()
    void = parse_callback_data(f"void:{order.order_number}")
    void.chat_id, void.user_id, void.username = "999", "tgacc", "zhang"
    assert handle_callback(db, void, client)["ok"]

    db.refresh(order)
    assert order.order_status == ORDER_STATUS_FAILED
    # Voided orders must not sneak into settlement.
    assert order.amount_confirmed is False


def test_unrelated_member_cannot_void(db):
    order = _make(db, "V2", "1390", ORDER_STATUS_PENDING, msg_id="2")

    _accept(db, order, "tgowner", "owner")
    result, _ = _complete(db, order, "tgowner", "owner")
    assert result["ok"]

    # A bystander tries to void someone else's order.
    client = MockTelegramClient()
    void = parse_callback_data(f"void:{order.order_number}")
    void.chat_id, void.user_id, void.username = "999", "tgsomeone", "random"
    out = handle_callback(db, void, client)
    assert out["ok"] is False
    assert out["detail"] == "forbidden"

    db.refresh(order)
    assert order.order_status == ORDER_STATUS_COMPLETED


def test_reopen_also_refreshes_siblings(db):
    """Reopening takes a slot back, so later siblings shift up.

    Only refreshing on `void` left the group showing stale numbers after a
    reopen -- the mirror image of the original bug.
    """
    from app.services.telegram_bot import _refresh_same_amount_messages

    a1 = _make(db, "R1", "1390", ORDER_STATUS_FAILED, msg_id="11")
    a2 = _make(db, "R2", "1390", ORDER_STATUS_COMPLETED, msg_id="22")

    # While a1 is failed, a2 is No.1.
    assert sequence_for(db, a2) == 1

    client = MockTelegramClient()
    a1.order_status = ORDER_STATUS_PENDING
    db.commit()
    _refresh_same_amount_messages(db, a1, client)

    rewritten = {e["message_id"]: e["text"] for e in client.text_edits}
    assert "第 2 单" in rewritten["22"], "sibling should have been renumbered upward"


def test_voiding_renumbers_sibling_messages(db):
    """The visible requirement: after a void, No.3 becomes No.2 in the group."""
    a1 = _make(db, "S1", "1390", ORDER_STATUS_COMPLETED, msg_id="11")
    a2 = _make(db, "S2", "1390", ORDER_STATUS_COMPLETED, msg_id="22")
    a3 = _make(db, "S3", "1390", ORDER_STATUS_COMPLETED, msg_id="33")

    client = MockTelegramClient()
    assert "第 3 单" in render_order_message(a3, db)

    # Void the middle one as the admin.
    from app.services.telegram_bot import _refresh_same_amount_messages

    a2.order_status = ORDER_STATUS_FAILED
    db.commit()
    _refresh_same_amount_messages(db, a2, client)

    # Both siblings were rewritten with the new numbering.
    rewritten = {e["message_id"]: e["text"] for e in client.text_edits}
    assert "第 2 单" in rewritten["33"], "No.3 should have become No.2"
    assert "第 1 单" in rewritten["11"]