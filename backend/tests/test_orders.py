from fastapi.testclient import TestClient

from app.db.models.order import Order
from app.services.telegram_bot import build_telegram_order_message


def test_create_order_requires_admin(client, admin, partner):
    r = client.post(
        "/api/orders", json={"amount": 10, "currency": "INR"},
        headers={"Authorization": f"Bearer {partner}"},
    )
    assert r.status_code == 403

    r = client.post(
        "/api/orders", json={"amount": 10, "currency": "INR"},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["order_number"].startswith("2026") and "-" in body["order_number"]
    assert body["order_status"] == "draft"
    assert body["amount"] == "10.00"  # Decimal is serialized as a string
    assert body["currency"] == "INR"


def test_empty_amount_is_rejected(client, admin):
    """Both admin and dispatcher must price an order: settlement depends on it."""
    r = client.post(
        "/api/orders", json={"currency": "INR"},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "amount_required"


def test_send_order_sets_pending(client, admin):
    r = client.post(
        "/api/orders", json={"email": "a@b.com", "amount": "10", "currency": "INR"},
        headers={"Authorization": f"Bearer {admin}"},
    )
    oid = r.json()["id"]
    r2 = client.post(
        f"/api/orders/{oid}/send?chat_id=12345",
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["order_status"] == "pending"
    assert body["telegram_send_status"] == "sent"
    assert body["telegram_chat_id"] == "12345"


def test_message_shows_only_filled():
    o = Order(
        order_number="ORD-TEST", email="u@x.com", login_method="code_send",
        currency="INR",
    )
    msg = build_telegram_order_message(o)
    assert "u@x.com" in msg
    assert "Code Send" in msg
    assert "Password" not in msg
    assert "N/A" not in msg
    assert "Account" not in msg
    assert "Amount" not in msg  # amount was None -> not rendered
