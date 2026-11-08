"""P0 business-rule tests: payment-count statistics, settlement integrity,
partner isolation, image persistence, and Excel/UI consistency.

These exercise the core services and APIs directly so the strict financial
rules (count occurrences per currency+amount, never sum, never convert) are
continuously verified.
"""
from decimal import Decimal

import io

import openpyxl
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import (
    FIN_STATUS_EXCLUDED,
    FIN_STATUS_RESERVED,
    FIN_STATUS_SETTLED,
    FIN_STATUS_UNSETTLED,
    ORDER_STATUS_COMPLETED,
    ORDER_STATUS_DRAFT,
    ORDER_STATUS_FAILED,
    ORDER_STATUS_PROCESSING,
)
from app.db.models.order import Order
from app.db.models.user import User
from app.schemas.settlement import SettlementFilter
from app.services.settlement import (
    cancel_settlement,
    confirm_settlement,
    create_settlement_batch,
)
from app.services.statistics import build_settlement_preview


def _mk_order(db: Session, **kw) -> Order:
    i = _mk_order.counter = getattr(_mk_order, "counter", 0) + 1
    defaults = dict(
        order_number=f"ORD-T{i:04d}",
        currency="INR",
        order_status=ORDER_STATUS_COMPLETED,
        financial_status=FIN_STATUS_UNSETTLED,
        amount_confirmed=True,
        amount=Decimal("100.00"),
    )
    defaults.update(kw)
    o = Order(**defaults)
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


# --------------------------------------------------------------------------
# D. Successful-payment-count statistics
# --------------------------------------------------------------------------
def test_payment_count_statistics(db):
    # Build the exact scenario from the spec (section 22.D).
    _mk_order(db, currency="INR", amount=Decimal("250.00"), order_status=ORDER_STATUS_COMPLETED, amount_confirmed=True, financial_status=FIN_STATUS_UNSETTLED)
    _mk_order(db, currency="INR", amount=Decimal("250.00"), order_status=ORDER_STATUS_COMPLETED, amount_confirmed=True, financial_status=FIN_STATUS_UNSETTLED)
    _mk_order(db, currency="INR", amount=Decimal("500.00"), order_status=ORDER_STATUS_COMPLETED, amount_confirmed=True, financial_status=FIN_STATUS_UNSETTLED)
    _mk_order(db, currency="USD", amount=Decimal("3.40"), order_status=ORDER_STATUS_COMPLETED, amount_confirmed=True, financial_status=FIN_STATUS_UNSETTLED)
    _mk_order(db, currency="USD", amount=Decimal("3.40"), order_status=ORDER_STATUS_COMPLETED, amount_confirmed=True, financial_status=FIN_STATUS_UNSETTLED)
    # excluded cases
    _mk_order(db, currency="USD", amount=Decimal("5.00"), order_status=ORDER_STATUS_FAILED)  # failed
    _mk_order(db, currency="INR", amount=Decimal("250.00"), order_status=ORDER_STATUS_PROCESSING)  # not completed
    _mk_order(db, currency="INR", amount=None, order_status=ORDER_STATUS_COMPLETED)  # null amount
    _mk_order(db, currency="INR", amount=Decimal("250.00"), order_status=ORDER_STATUS_COMPLETED, amount_confirmed=False)  # unconfirmed
    _mk_order(db, currency="INR", amount=Decimal("250.00"), order_status=ORDER_STATUS_COMPLETED, financial_status=FIN_STATUS_SETTLED)  # settled
    _mk_order(db, currency="USD", amount=Decimal("3.40"), order_status=ORDER_STATUS_COMPLETED, financial_status=FIN_STATUS_EXCLUDED)  # excluded

    preview = build_settlement_preview(db, SettlementFilter())
    counts = {(r.currency, str(r.amount)): r.quantity for r in preview.payment_counts}

    assert counts[("INR", "250.00")] == 2
    assert counts[("INR", "500.00")] == 1
    assert counts[("USD", "3.40")] == 2
    assert "USD" in {c[0] for c in counts} and "INR" in {c[0] for c in counts}
    # Nothing else should be counted.
    assert set(counts.keys()) == {
        ("INR", "250.00"), ("INR", "500.00"), ("USD", "3.40")
    }
    # No currency totals are ever produced.
    assert preview.eligible_order_count == 5
    assert preview.already_settled_count == 1
    assert preview.excluded_count == 1
    assert preview.reserved_count == 0


def test_statistics_never_sums_currencies(db):
    _mk_order(db, currency="INR", amount=Decimal("10.00"), order_status=ORDER_STATUS_COMPLETED, amount_confirmed=True)
    _mk_order(db, currency="USD", amount=Decimal("10.00"), order_status=ORDER_STATUS_COMPLETED, amount_confirmed=True)
    preview = build_settlement_preview(db, SettlementFilter())
    # The summary is strictly grouped occurrences; there is no aggregate field.
    assert {(r.currency, str(r.amount)): r.quantity for r in preview.payment_counts} == {
        ("INR", "10.00"): 1, ("USD", "10.00"): 1
    }


# --------------------------------------------------------------------------
# E. Settlement preview / reserve / confirm / cancel / idempotency
# --------------------------------------------------------------------------
def test_settlement_reserve_then_confirm(db):
    o1 = _mk_order(db, currency="INR", amount=Decimal("250.00"), order_status=ORDER_STATUS_COMPLETED, amount_confirmed=True)
    o2 = _mk_order(db, currency="INR", amount=Decimal("250.00"), order_status=ORDER_STATUS_COMPLETED, amount_confirmed=True)

    admin = db.query(User).filter(User.role == "admin").first()
    if admin is None:
        admin = User(username="admin_x", password_hash="x", role="admin", is_active=True)
        db.add(admin); db.commit(); db.refresh(admin)

    batch = create_settlement_batch(db, SettlementFilter(), admin)
    db.refresh(o1); db.refresh(o2)
    assert o1.financial_status == FIN_STATUS_RESERVED
    assert o2.financial_status == FIN_STATUS_RESERVED

    # Preview after reservation should no longer count them as eligible.
    preview = build_settlement_preview(db, SettlementFilter())
    assert preview.eligible_order_count == 0

    confirmed = confirm_settlement(db, batch.settlement_id, admin)
    db.refresh(o1); db.refresh(o2)
    assert confirmed.status == "confirmed"
    assert o1.financial_status == FIN_STATUS_SETTLED
    assert o2.financial_status == FIN_STATUS_SETTLED

    # Re-confirm must be rejected (idempotency / no double settle).
    with pytest.raises(ValueError):
        confirm_settlement(db, batch.settlement_id, admin)


def test_settlement_cancel_releases_reserved(db):
    o = _mk_order(db, currency="USD", amount=Decimal("3.40"), order_status=ORDER_STATUS_COMPLETED, amount_confirmed=True)
    admin = db.query(User).filter(User.role == "admin").first()
    if admin is None:
        admin = User(username="admin_y", password_hash="x", role="admin", is_active=True)
        db.add(admin); db.commit(); db.refresh(admin)

    batch = create_settlement_batch(db, SettlementFilter(), admin)
    db.refresh(o)
    assert o.financial_status == FIN_STATUS_RESERVED

    cancel_settlement(db, batch.settlement_id, admin)
    db.refresh(o)
    assert o.financial_status == FIN_STATUS_UNSETTLED

    # A cancelled (never confirmed) batch may be re-confirmed through a new batch.
    preview = build_settlement_preview(db, SettlementFilter())
    assert preview.eligible_order_count == 1


def test_confirmed_batch_cannot_be_cancelled(db):
    o = _mk_order(db, currency="INR", amount=Decimal("100.00"), order_status=ORDER_STATUS_COMPLETED, amount_confirmed=True)
    admin = db.query(User).filter(User.role == "admin").first()
    if admin is None:
        admin = User(username="admin_z", password_hash="x", role="admin", is_active=True)
        db.add(admin); db.commit(); db.refresh(admin)
    batch = create_settlement_batch(db, SettlementFilter(), admin)
    confirm_settlement(db, batch.settlement_id, admin)
    with pytest.raises(ValueError):
        cancel_settlement(db, batch.settlement_id, admin)


# --------------------------------------------------------------------------
# F. Partner isolation & image persistence
# --------------------------------------------------------------------------
def _partner_id(db, username):
    return db.query(User).filter(User.username == username).first().id


def test_partner_sees_only_own_orders(db, client, admin, partner, partner2):
    p1 = _partner_id(db, "partner1")
    p2 = _partner_id(db, "partner2")
    # admin creates two orders owned by different partners
    r1 = client.post("/api/orders", json={"amount": 10, "currency": "INR", "order_owner_id": p1}, headers={"Authorization": f"Bearer {admin}"})
    r2 = client.post("/api/orders", json={"amount": 20, "currency": "USD", "order_owner_id": p2}, headers={"Authorization": f"Bearer {admin}"})
    o1 = r1.json()["id"]
    o2 = r2.json()["id"]

    # partner1 sees only o1
    my = client.get("/api/partner/orders", headers={"Authorization": f"Bearer {partner}"})
    ids = {x["id"] for x in my.json()}
    assert o1 in ids and o2 not in ids

    # partner1 cannot open partner2's order
    forbidden = client.get(f"/api/orders/{o2}", headers={"Authorization": f"Bearer {partner}"})
    assert forbidden.status_code == 403


def test_image_persists_and_is_partner_scoped(db, client, admin, partner, partner2):
    p1 = _partner_id(db, "partner1")
    p2 = _partner_id(db, "partner2")
    r = client.post("/api/orders", json={"amount": 10, "currency": "INR", "order_owner_id": p1}, headers={"Authorization": f"Bearer {admin}"})
    oid = r.json()["id"]

    # partner1 uploads an attachment to their order
    upload = client.post(
        f"/api/orders/{oid}/attachments",
        headers={"Authorization": f"Bearer {partner}"},
        files={"file": ("shot.png", b"\x89PNG\r\n\x1a\n fake-png", "image/png")},
    )
    assert upload.status_code == 200, upload.text
    att_id = upload.json()["id"]

    # partner1 can download it
    dl = client.get(f"/api/attachments/{att_id}/download", headers={"Authorization": f"Bearer {partner}"})
    assert dl.status_code == 200
    assert dl.content == b"\x89PNG\r\n\x1a\n fake-png"

    # partner2 cannot download partner1's private image
    dl2 = client.get(f"/api/attachments/{att_id}/download", headers={"Authorization": f"Bearer {partner2}"})
    assert dl2.status_code == 403


def test_deactivated_partner_loses_access(db, client, admin, partner2):
    pid = _partner_id(db, "partner2")
    # admin deactivates partner2
    r = client.patch(f"/api/admin/partners/{pid}", json={"is_active": False}, headers={"Authorization": f"Bearer {admin}"})
    assert r.status_code == 200
    # login now fails
    login = client.post("/api/auth/login", json={"username": "partner2", "password": "ppass2"})
    assert login.status_code == 401


def test_attachment_signed_url_download_without_auth_header(db, client, admin, partner, partner2):
    """Browser-driven downloads (<img>/window.open) cannot send Authorization.
    The /url endpoint mints a short-lived signed URL that works header-less."""
    p1 = _partner_id(db, "partner1")
    r = client.post("/api/orders", json={"amount": 10, "currency": "INR", "order_owner_id": p1},
                    headers={"Authorization": f"Bearer {admin}"})
    oid = r.json()["id"]
    upload = client.post(
        f"/api/orders/{oid}/attachments",
        headers={"Authorization": f"Bearer {partner}"},
        files={"file": ("shot.png", b"\x89PNG\r\n\x1a\n signed-png", "image/png")},
    )
    assert upload.status_code == 200, upload.text
    att_id = upload.json()["id"]

    # Mint a signed URL (requires auth to obtain).
    mint = client.get(f"/api/attachments/{att_id}/url", headers={"Authorization": f"Bearer {partner}"})
    assert mint.status_code == 200, mint.text
    url = mint.json()["url"]
    assert "token=" in url

    # Fetch the signed URL with NO Authorization header -> must succeed.
    dl = client.get(url)
    assert dl.status_code == 200
    assert dl.content == b"\x89PNG\r\n\x1a\n signed-png"

    # Tampering the token must be rejected.
    bad = client.get(url.replace("token=", "token=x"))
    assert bad.status_code == 403


def test_x_send_order_without_bot_token_is_not_a_false_success(client, admin, db, monkeypatch):
    """Regression: with no TELEGRAM_BOT_TOKEN (and dry-run off) the send endpoint
    must surface an error (400 telegram_not_configured), never a fake success."""
    from app.config import settings

    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(settings, "TELEGRAM_DRY_RUN", False)

    o = _mk_order(db, currency="INR", amount=Decimal("10.00"),
                  order_status=ORDER_STATUS_DRAFT, financial_status=FIN_STATUS_UNSETTLED)
    r = client.post(f"/api/orders/{o.id}/send", params={"chat_id": "-100123"},
                    headers={"Authorization": f"Bearer {admin}"})
    assert r.status_code != 200, "send must not report success without a bot token"
    assert r.status_code == 400
    assert r.json()["detail"] == "telegram_not_configured"
    db.refresh(o)
    assert o.telegram_send_status != "sent"


def test_x_settlement_preview_endpoint_responds(client, admin, db):
    """Regression: POST /api/settlements/preview called a non-existent service
    function and returned 500. It must return the preview payload."""
    _mk_order(db, currency="INR", amount=Decimal("250.00"),
              order_status=ORDER_STATUS_COMPLETED, amount_confirmed=True)
    r = client.post("/api/settlements/preview", json={},
                    headers={"Authorization": f"Bearer {admin}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "payment_counts" in body
    assert body["eligible_order_count"] == 1
    assert {"currency": "INR", "amount": "250.00", "quantity": 1} in body["payment_counts"]
    # Never any total/sum/aggregate field.
    assert not any(k in body for k in ("total", "sum", "total_amount", "converted"))


def test_x_admin_settings_endpoint_responds(client, admin):
    """Regression: /api/admin/settings used `settings` without importing it."""
    r = client.get("/api/admin/settings", headers={"Authorization": f"Bearer {admin}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "default_currency" in body
    assert "supported_currencies" in body
    # Secrets are never exposed.
    assert "TELEGRAM_BOT_TOKEN" not in body
    assert "telegram_bot_token" not in body


def test_admin_can_save_telegram_settings_without_exposing_token(client, admin, db):
    headers = {"Authorization": f"Bearer {admin}"}
    payload = {
        "bot_token": "123456:test-secret-token",
        "default_chat_id": "-1001234567890",
        "allowed_chat_ids": "-1001234567890,-1009876543210",
        "admin_telegram_user_ids": "123456789,987654321",
    }

    response = client.put("/api/admin/settings/telegram", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["telegram_configured"] is True
    assert body["default_chat_id"] == payload["default_chat_id"]
    assert body["allowed_chat_ids"] == payload["allowed_chat_ids"]
    assert body["admin_telegram_user_ids"] == payload["admin_telegram_user_ids"]
    assert "bot_token" not in body
    assert payload["bot_token"] not in response.text

    from app.db.models.system_config import SystemConfig

    stored = db.get(SystemConfig, 1)
    assert stored is not None
    assert stored.telegram_bot_token_encrypted
    assert payload["bot_token"] not in stored.telegram_bot_token_encrypted

    keep_response = client.put(
        "/api/admin/settings/telegram",
        headers=headers,
        json={
            "bot_token": "",
            "default_chat_id": "-1001111111111",
            "allowed_chat_ids": "-1001111111111",
            "admin_telegram_user_ids": "123456789",
        },
    )
    assert keep_response.status_code == 200, keep_response.text
    db.expire_all()
    kept = db.get(SystemConfig, 1)
    assert kept.telegram_bot_token_encrypted == stored.telegram_bot_token_encrypted


# --------------------------------------------------------------------------
# G. Language switch never alters stored amount/currency
# --------------------------------------------------------------------------
def test_language_switch_does_not_alter_amount():
    from app.services.telegram_bot import build_telegram_order_message
    o = Order(order_number="ORD-L", currency="USD", amount=Decimal("3.40"))
    en = build_telegram_order_message(o, lang="en")
    zh = build_telegram_order_message(o, lang="zh-CN")
    # Amount + currency preserved; only the label is translated.
    assert "3.40" in en and "3.40" in zh
    assert "USD" in en and "USD" in zh
    assert "Amount" in en and "金额" in zh


def test_excel_export_matches_web_and_has_no_totals(client, admin, db):
    _mk_order(db, currency="INR", amount=Decimal("250.00"), order_status=ORDER_STATUS_COMPLETED, amount_confirmed=True, financial_status=FIN_STATUS_UNSETTLED)
    _mk_order(db, currency="INR", amount=Decimal("250.00"), order_status=ORDER_STATUS_COMPLETED, amount_confirmed=True, financial_status=FIN_STATUS_UNSETTLED)
    _mk_order(db, currency="USD", amount=Decimal("3.40"), order_status=ORDER_STATUS_COMPLETED, amount_confirmed=True, financial_status=FIN_STATUS_UNSETTLED)

    # The live web preview (taken BEFORE a batch reserves the orders) is the
    # source of truth. build_settlement_preview only counts UNSETTLED orders,
    # so it must be captured here, not after the batch reserves them.
    preview = build_settlement_preview(db, SettlementFilter())
    web = {(rr.currency, rr.amount.quantize(Decimal("0.01"))): rr.quantity
           for rr in preview.payment_counts}
    assert web == {("INR", Decimal("250.00")): 2, ("USD", Decimal("3.40")): 1}

    # Now create a settlement batch and export the snapshot.
    r = client.post("/api/settlements", json={}, headers={"Authorization": f"Bearer {admin}"})
    assert r.status_code == 201, r.text
    sid = r.json()["settlement_id"]

    ex = client.get(f"/api/settlements/{sid}/export", headers={"Authorization": f"Bearer {admin}"})
    assert ex.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(ex.content))
    ws = wb["Settlement Summary"]
    rows = list(ws.iter_rows(values_only=True))
    assert rows[0] == ("Currency", "Amount", "Quantity")
    summary = {}
    for (c, a, q) in rows[1:]:
        if c is None:
            continue
        # openpyxl reads the stored Decimal back as a float; normalize to a
        # canonical 2-dp Decimal so it compares equal to the web-side Decimal.
        summary[(c, Decimal(str(a)).quantize(Decimal("0.01")))] = q
    assert summary[("INR", Decimal("250.00"))] == 2
    assert summary[("USD", Decimal("3.40"))] == 1
    # The export must agree with the (pre-reservation) web preview.
    assert web == summary
    # No currency totals anywhere in any sheet.
    flat = [str(v) for sheet in wb.worksheets for row in sheet.iter_rows(values_only=True) for v in row if v is not None]
    assert not any(("Total" in v) or ("Subtotal" in v) or ("总额" in v) or ("合计" in v) for v in flat)
