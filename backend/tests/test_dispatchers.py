from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.models.order import Order
from app.db.models.user import TelegramBindToken, User


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _product(client, admin_token, name):
    r = client.post("/api/products", json={"name": name}, headers=_auth(admin_token))
    assert r.status_code == 201, r.text
    return r.json()


def _dispatcher(client, admin_token, **overrides):
    payload = {
        "username": "disp1",
        "password": "dpass",
        "display_name": "Dispatcher One",
        "chat_ids": ["-1001"],
        "default_chat_id": "-1001",
        "product_ids": [],
        "is_active": True,
    }
    payload.update(overrides)
    r = client.post("/api/admin/dispatchers", json=payload, headers=_auth(admin_token))
    assert r.status_code == 201, r.text
    return r.json()


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_admin_creates_dispatcher_with_group_and_products(client, admin):
    p1 = _product(client, admin, "Product A")
    p2 = _product(client, admin, "Product B")
    d = _dispatcher(client, admin, product_ids=[p1["id"]])

    assert d["role"] == "dispatcher"
    assert d["assigned_chat_ids"] == ["-1001"]
    assert d["default_chat_id"] == "-1001"
    assert d["allowed_product_ids"] == [p1["id"]]
    assert d["telegram_bound"] is False

    rows = client.get("/api/admin/dispatchers", headers=_auth(admin)).json()
    assert [r["username"] for r in rows] == ["disp1"]

    # Update the whitelist: B only, default group unchanged.
    r = client.put(
        f"/api/admin/dispatchers/{d['id']}",
        json={"product_ids": [p2["id"]], "chat_ids": ["-1001", "-1002"],
              "default_chat_id": "-1002"},
        headers=_auth(admin),
    )
    assert r.status_code == 200, r.text
    assert r.json()["allowed_product_ids"] == [p2["id"]]
    assert r.json()["default_chat_id"] == "-1002"


def test_dispatcher_cannot_send_product_outside_whitelist(client, admin):
    p1 = _product(client, admin, "Allowed")
    p2 = _product(client, admin, "Forbidden")
    _dispatcher(client, admin, product_ids=[p1["id"]])
    token = _login(client, "disp1", "dpass")

    bad = client.post(
        "/api/orders",
        json={"product_id": p2["id"], "amount": "10", "currency": "INR"},
        headers=_auth(token),
    )
    assert bad.status_code == 400
    assert bad.json()["detail"] == "product_not_allowed"

    ok = client.post(
        "/api/orders",
        json={"product_id": p1["id"], "amount": "10", "currency": "INR"},
        headers=_auth(token),
    )
    assert ok.status_code == 201, ok.text
    order = ok.json()
    assert order["order_owner_id"] == order["created_by_user_id"]

    # Send goes to the admin-configured default group, not a caller choice.
    sent = client.post(f"/api/orders/{order['id']}/send", headers=_auth(token))
    assert sent.status_code == 200, sent.text
    assert sent.json()["telegram_chat_id"] == "-1001"


def test_amount_is_required_for_admin_and_dispatcher(client, admin):
    p1 = _product(client, admin, "Amount product")
    _dispatcher(client, admin, product_ids=[p1["id"]])
    token = _login(client, "disp1", "dpass")

    for headers in (_auth(admin), _auth(token)):
        missing = client.post(
            "/api/orders",
            json={"product_id": p1["id"], "currency": "INR"},
            headers=headers,
        )
        assert missing.status_code == 400, missing.text
        assert missing.json()["detail"] == "amount_required"

        zero = client.post(
            "/api/orders",
            json={"product_id": p1["id"], "amount": "0", "currency": "INR"},
            headers=headers,
        )
        assert zero.status_code == 400, zero.text
        assert zero.json()["detail"] == "amount_invalid"


def test_dispatcher_sees_only_own_orders(client, admin):
    p1 = _product(client, admin, "P1")
    _dispatcher(client, admin, product_ids=[p1["id"]])
    token = _login(client, "disp1", "dpass")

    own = client.post("/api/orders", json={"product_id": p1["id"], "amount": "5"},
                      headers=_auth(token)).json()
    client.post("/api/orders", json={"product_id": p1["id"], "amount": "7"},
                headers=_auth(admin))

    rows = client.get("/api/orders", headers=_auth(token)).json()
    assert [r["id"] for r in rows] == [own["id"]]


def test_partner_cannot_create_orders(client, partner, admin):
    r = client.post("/api/orders", json={"amount": "5"}, headers=_auth(partner))
    assert r.status_code == 403


def test_dispatcher_settlement_is_independent_from_group_settlement(client, admin):
    p1 = _product(client, admin, "P1")
    d = _dispatcher(client, admin, product_ids=[p1["id"]])
    token = _login(client, "disp1", "dpass")

    order = client.post("/api/orders", json={"product_id": p1["id"], "amount": "25"},
                        headers=_auth(token)).json()
    done = client.patch(f"/api/orders/{order['id']}", json={"order_status": "completed"},
                        headers=_auth(admin))
    assert done.status_code == 200, done.text

    # Private ledger preview counts it...
    prev = client.post("/api/settlements/preview",
                       json={"dispatcher_user_id": d["id"]}, headers=_auth(admin))
    assert prev.status_code == 200, prev.text
    assert prev.json()["eligible_order_count"] == 1

    batch = client.post("/api/settlements",
                        json={"dispatcher_user_id": d["id"]}, headers=_auth(admin))
    assert batch.status_code == 201, batch.text
    assert batch.json()["settlement_type"] == "dispatcher"

    confirmed = client.post(
        f"/api/settlements/{batch.json()['settlement_id']}/confirm",
        headers=_auth(admin),
    )
    assert confirmed.status_code == 200, confirmed.text

    detail = client.get(f"/api/orders/{order['id']}", headers=_auth(admin)).json()
    assert detail["dispatcher_settlement_status"] == "settled"
    # The group ledger must be completely untouched.
    assert detail["financial_status"] == "unsettled"

    group_batch = client.post("/api/settlements", json={}, headers=_auth(admin))
    assert group_batch.status_code == 201, group_batch.text
    assert group_batch.json()["order_count"] == 1
    assert group_batch.json()["settlement_type"] == "group"

def test_dispatcher_settlement_does_not_restart_group_sequence(client, admin, db):
    """A dispatcher batch is a private ledger and never starts a group cycle.

    Regression: orders created after a dispatcher settlement were stamped with
    that dispatcher batch id. The group sequence is scoped by cycle id, so the
    whole group's "No. N" count restarted at 1.
    """
    from app.services.orders import current_cycle_id
    from app.services.telegram_bot import sequence_for

    p1 = _product(client, admin, "P1")
    d = _dispatcher(client, admin, product_ids=[p1["id"]])
    token = _login(client, "disp1", "dpass")

    # Establish a group cycle with one completed admin order.
    a1 = client.post("/api/orders", json={"amount": "25"},
                     headers=_auth(admin)).json()
    done = client.patch(f"/api/orders/{a1['id']}", json={"order_status": "completed"},
                        headers=_auth(admin))
    assert done.status_code == 200, done.text

    group_batch = client.post("/api/settlements", json={}, headers=_auth(admin))
    assert group_batch.status_code == 201, group_batch.text
    group_id = group_batch.json()["id"]
    confirmed = client.post(
        f"/api/settlements/{group_batch.json()['settlement_id']}/confirm",
        headers=_auth(admin),
    )
    assert confirmed.status_code == 200, confirmed.text
    db.expire_all()
    assert current_cycle_id(db) == group_id

    # A dispatcher order is created inside that same group cycle.
    d1 = client.post("/api/orders",
                     json={"product_id": p1["id"], "amount": "25"},
                     headers=_auth(token)).json()
    done = client.patch(f"/api/orders/{d1['id']}", json={"order_status": "completed"},
                        headers=_auth(admin))
    assert done.status_code == 200, done.text

    disp_batch = client.post("/api/settlements",
                             json={"dispatcher_user_id": d["id"]},
                             headers=_auth(admin))
    assert disp_batch.status_code == 201, disp_batch.text
    assert disp_batch.json()["settlement_type"] == "dispatcher"
    confirmed = client.post(
        f"/api/settlements/{disp_batch.json()['settlement_id']}/confirm",
        headers=_auth(admin),
    )
    assert confirmed.status_code == 200, confirmed.text

    db.expire_all()
    # The private batch must not become the group's current cycle.
    assert current_cycle_id(db) == group_id

    # The next order joins the existing group cycle and continues the count.
    a2 = client.post("/api/orders", json={"amount": "25"},
                     headers=_auth(admin)).json()
    db.expire_all()
    new_order = db.get(Order, a2["id"])
    new_order.order_status = "pending"
    db.commit()
    assert new_order.cycle_id == group_id
    assert sequence_for(db, new_order) == 2


def test_telegram_bind_token_flow(client, admin, db):
    _dispatcher(client, admin)
    token = _login(client, "disp1", "dpass")

    r = client.post("/api/dispatcher/telegram/bind-token", headers=_auth(token))
    assert r.status_code == 200, r.text
    raw = r.json()["token"]

    update = {
        "update_id": 1,
        "message": {
            "message_id": 5,
            "chat": {"id": 777, "type": "private"},
            "from": {"id": 777, "username": "disp_tg", "first_name": "Dis"},
            "text": f"/start bind_{raw}",
        },
    }
    hook = client.post(
        "/api/telegram/webhook", json=update,
        headers={"X-Telegram-Bot-Api-Secret-Token": "test_webhook_secret"},
    )
    assert hook.status_code == 200

    db.expire_all()
    user = db.execute(select(User).where(User.username == "disp1")).scalar_one()
    assert user.telegram_user_id == "777"
    assert user.telegram_username == "disp_tg"

    # The token is single-use.
    again = client.post(
        "/api/telegram/webhook", json={
            "update_id": 2,
            "message": {
                "message_id": 6,
                "chat": {"id": 888, "type": "private"},
                "from": {"id": 888, "username": "other"},
                "text": f"/bind {raw}",
            },
        },
        headers={"X-Telegram-Bot-Api-Secret-Token": "test_webhook_secret"},
    )
    assert again.status_code == 200
    db.expire_all()
    other = db.execute(select(User).where(User.telegram_user_id == "888")).scalar_one_or_none()
    assert other is None
