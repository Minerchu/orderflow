"""Worker-facing features: completion DM, /count, and per-cycle numbering.

These are conveniences the group staff asked for, so the tests focus on the
guarantees that matter:

* a completion DM must never be able to undo the order action
* `/count` must never leak another worker's numbers
* after settlement, numbering restarts instead of continuing forever
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.constants import (
    ORDER_STATUS_COMPLETED,
    ORDER_STATUS_PENDING,
    ORDER_STATUS_PROCESSING,
    ROLE_PARTNER,
    SETTLEMENT_CONFIRMED,
)
from app.db.models.order import Order
from app.db.models.settlement import SettlementBatch
from app.db.models.user import User
from app.core.security import hash_password
from app.services.notify import build_count_reply, completed_count
from app.services.orders import current_cycle_id
from app.services.telegram_bot import (
    MockTelegramClient,
    build_sequence_map,
    handle_callback,
    parse_callback_data,
    sequence_for,
)


@pytest.fixture(autouse=True)
def chinese(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "TELEGRAM_MESSAGE_LANGUAGE", "zh-CN")


def _worker(db, username="zhangsan", tg_id="tg_zhang"):
    u = User(username=username, password_hash=hash_password("x"), role=ROLE_PARTNER,
             telegram_user_id=tg_id, telegram_username=username, is_active=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _order(db, number, amount="1390", status=ORDER_STATUS_PENDING, worker=None):
    o = Order(order_number=number, currency="INR", amount=Decimal(amount),
              note="n", order_status=status, telegram_chat_id="999",
              completed_by_user_id=worker.id if worker else None,
              accepted_by_user_id=worker.id if worker else None)
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


def test_completion_dm_tells_worker_which_number(db):
    """The point of the DM: "you completed No.3"."""
    import app.services.telegram_bot as tb

    worker = _worker(db)
    order = _order(db, "D1", status=ORDER_STATUS_PENDING)
    _order(db, "D2", status=ORDER_STATUS_PENDING)
    order3 = _order(db, "D3", status=ORDER_STATUS_PENDING)
    assert sequence_for(db, order3) == 3

    client = MockTelegramClient()
    ctx = parse_callback_data("accept:D3")
    ctx.chat_id, ctx.user_id, ctx.username = "999", worker.telegram_user_id, "zhangsan"
    handle_callback(db, ctx, client)

    ctx2 = parse_callback_data("complete:D3")
    ctx2.chat_id, ctx2.user_id, ctx2.username = "999", worker.telegram_user_id, "zhangsan"
    handle_callback(db, ctx2, client)

    # A DM went to the worker's private chat.
    dms = [m for m in client.sent if m["chat_id"] == worker.telegram_user_id]
    assert dms, "worker was not notified in private"
    body = dms[-1]["text"]
    assert "第 3 单" in body
    assert "1390.00" in body


def test_completion_still_succeeds_when_dm_fails(db):
    """A broken DM must not undo a completed order."""
    worker = _worker(db)
    _order(db, "E1", status=ORDER_STATUS_PROCESSING, worker=worker)

    class BrokenDM(MockTelegramClient):
        def send_message(self, chat_id, text, reply_markup=None):
            if str(chat_id) == worker.telegram_user_id:
                raise RuntimeError("blocked by user")
            return super().send_message(chat_id, text, reply_markup)

    client = BrokenDM()
    ctx = parse_callback_data("complete:E1")
    ctx.chat_id, ctx.user_id, ctx.username = "999", worker.telegram_user_id, "zhangsan"
    assert handle_callback(db, ctx, client)["ok"]

    db.expire_all()
    db.refresh(client and db.query(Order).filter_by(order_number="E1").one())
    assert db.query(Order).filter_by(order_number="E1").one().order_status == ORDER_STATUS_COMPLETED


def test_count_reply_shows_only_my_numbers(db):
    worker = _worker(db, "zhangsan", "tg_zhang")
    other = _worker(db, "lisi", "tg_li")
    _order(db, "M1", status=ORDER_STATUS_COMPLETED, worker=worker)
    _order(db, "M2", status=ORDER_STATUS_COMPLETED, worker=other)

    reply = build_count_reply(db, worker.telegram_user_id)
    assert "zhangsan" in reply
    assert "已完成：1 单" in reply
    assert "lisi" not in reply


def test_count_reply_for_unknown_user_is_helpful(db):
    reply = build_count_reply(db, "tg_nobody")
    assert "合作伙伴" in reply  # tells them how to get bound


def test_count_command_answered_in_private_chat(client, db):
    # Stored id must match the "from.id" the webhook will send.
    worker = _worker(db, "zhangsan", "999")
    _order(db, "P1", status=ORDER_STATUS_COMPLETED, worker=worker)

    import app.api.telegram as tg_api

    sent = []

    class SpyClient(MockTelegramClient):
        def send_message(self, chat_id, text, reply_markup=None):
            sent.append((chat_id, text))
            return super().send_message(chat_id, text, reply_markup)

    tg_api.get_telegram_client = lambda db, dry_run=False: SpyClient()

    from app.config import settings

    resp = client.post("/api/telegram/webhook", json={
        "message": {
            "from": {"id": 999, "username": "zhangsan"},
            "chat": {"id": 555, "type": "private"},
            "text": "/count",
        }
    }, headers={"X-Telegram-Bot-Api-Secret-Token": settings.TELEGRAM_WEBHOOK_SECRET})
    assert resp.status_code == 200
    assert sent, "/count produced no reply"
    assert "已完成：1 单" in sent[-1][1]


def test_command_in_group_is_ignored(client, db):
    """Group chatter must not trigger a stats reply."""
    _worker(db, "zhangsan", "tg_zhang")
    import app.api.telegram as tg_api

    sent = []

    class SpyClient(MockTelegramClient):
        def send_message(self, chat_id, text, reply_markup=None):
            sent.append((chat_id, text))
            return super().send_message(chat_id, text, reply_markup)

    tg_api.get_telegram_client = lambda db, dry_run=False: SpyClient()

    from app.config import settings

    resp = client.post("/api/telegram/webhook", json={
        "message": {
            "from": {"id": 999},
            "chat": {"id": -100123, "type": "supergroup"},
            "text": "/count",
        }
    }, headers={"X-Telegram-Bot-Api-Secret-Token": settings.TELEGRAM_WEBHOOK_SECRET})
    assert resp.status_code == 200
    assert not sent, "replied inside a group"


def test_sequence_restarts_after_settlement(db):
    """After a batch is confirmed, the next cycle counts from No.1 again."""
    a1 = _order(db, "C1")
    _order(db, "C2")

    assert sequence_for(db, a1) == 1
    assert current_cycle_id(db) is None

    # Confirm a settlement covering those two orders.
    batch = SettlementBatch(settlement_id="SET-1", status=SETTLEMENT_CONFIRMED, order_count=2)
    db.add(batch)
    db.commit()
    db.refresh(batch)

    for number in ("C1", "C2"):
        o = db.query(Order).filter_by(order_number=number).one()
        o.financial_status = "settled"
        o.cycle_id = batch.id
    db.commit()

    assert current_cycle_id(db) == batch.id

    # A new order joins the new cycle and starts numbering again.
    new = _order(db, "C3")
    new.cycle_id = batch.id
    db.commit()

    assert sequence_for(db, new) == 1


def test_orders_before_settlement_keep_their_numbers(db):
    """Settling must not renumber the already-visible historical messages."""
    a1 = _order(db, "H1")
    a2 = _order(db, "H2")
    before = {sequence_for(db, a1), sequence_for(db, a2)}
    assert before == {1, 2}

    batch = SettlementBatch(settlement_id="SET-2", status=SETTLEMENT_CONFIRMED, order_count=2)
    db.add(batch)
    db.commit()
    db.refresh(batch)
    for o in (a1, a2):
        o.cycle_id = batch.id
    db.commit()

    # Both were in the previous cycle, so their stored numbering is unchanged
    # and they now belong to that cycle only.
    assert sequence_for(db, a1) == 1
    assert sequence_for(db, a2) == 2