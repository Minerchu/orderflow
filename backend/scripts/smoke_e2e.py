"""End-to-end smoke test against a running OrderFlow backend.

Run with the backend up on 127.0.0.1:8000 and admin/admin123 seeded.
Uses httpx directly (no shell proxy interference).
"""
import sys

import httpx

B = "http://127.0.0.1:8000"
ok = 0
fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {name} {extra}")
    else:
        fail += 1
        print(f"  FAIL  {name} {extra}")


# httpx respects trust_env=False -> ignore HTTP_PROXY for localhost.
c = httpx.Client(base_url=B, timeout=20.0, trust_env=False)

print("== health ==")
r = c.get("/health")
check("health 200", r.status_code == 200, r.text)

print("== login ==")
r = c.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
check("login 200", r.status_code == 200, f"({r.status_code})")
if r.status_code != 200:
    print(r.text)
    sys.exit(1)
tok = r.json()["access_token"]
H = {"Authorization": f"Bearer {tok}"}

print("== auth/me ==")
r = c.get("/api/auth/me", headers=H)
check("me 200 + role admin", r.status_code == 200 and r.json()["role"] == "admin", r.text[:120])

print("== admin/settings (regression: missing settings import) ==")
r = c.get("/api/admin/settings", headers=H)
check("settings 200", r.status_code == 200, f"({r.status_code}) {r.text[:200]}")
if r.status_code == 200:
    s = r.json()
    check("settings has default_currency", "default_currency" in s, s.get("default_currency"))
    check("settings has supported_currencies", bool(s.get("supported_currencies")))

print("== products ==")
r = c.post("/api/products", headers=H, json={"name": "SmokeProd", "code": "SMK1", "default_currency": "INR"})
check("create product 201", r.status_code == 201, f"({r.status_code})")
r = c.get("/api/products", headers=H)
check("list products", r.status_code == 200 and len(r.json()) >= 1, f"count={len(r.json()) if r.status_code==200 else '?'}")

print("== partner ==")
r = c.post("/api/admin/partners", headers=H, json={
    "username": "p_smoke", "password": "ppass123",
    "telegram_username": "psmoke", "preferred_language": "zh-CN"})
if r.status_code == 400 and "exists" in r.text:
    print("  (partner already exists, reusing)")
else:
    check("create partner 201", r.status_code == 201, f"({r.status_code}) {r.text[:150]}")
r = c.get("/api/admin/partners", headers=H)
partners = r.json()
pid = next(p["id"] for p in partners if p["username"] == "p_smoke")
check("partner listed", pid > 0, f"id={pid}")

print("== orders ==")
r = c.post("/api/orders", headers=H, json={
    "product_name": "SmokeProd", "amount": "250.00", "currency": "INR",
    "order_owner_id": pid, "email": "a@b.c"})
check("create order 201", r.status_code == 201, f"({r.status_code}) {r.text[:200]}")
oid = r.json()["id"] if r.status_code == 201 else None
check("order status draft", r.status_code == 201 and r.json()["order_status"] == "draft",
      r.json().get("order_status") if r.status_code == 201 else "")
check("financial unsettled", r.status_code == 201 and r.json()["financial_status"] == "unsettled",
      r.json().get("financial_status") if r.status_code == 201 else "")

print("== send to telegram (no bot configured -> expected 502, must NOT 500) ==")
r = c.post(f"/api/orders/{oid}/send", headers=H, params={"chat_id": "-100123"})
check("send gracefully fails (400/502, not 500)", r.status_code in (400, 502),
      f"({r.status_code}) {r.text[:120]}")

print("== order events ==")
r = c.get(f"/api/orders/{oid}/events", headers=H)
check("events 200", r.status_code == 200, f"({r.status_code})")
check("has create event", r.status_code == 200 and any(e["event_type"] == "create" for e in r.json()))

print("== amount confirm (admin financial control) ==")
r = c.patch(f"/api/orders/{oid}", headers=H, json={"amount_confirmed": True})
check("confirm amount 200", r.status_code == 200 and r.json()["amount_confirmed"] is True,
      f"({r.status_code})")

print("== settlement preview (counts, never sums) ==")
r = c.post("/api/settlements/preview", headers=H, json={})
check("preview 200", r.status_code == 200, f"({r.status_code})")
if r.status_code == 200:
    pv = r.json()
    check("has payment_counts key", "payment_counts" in pv)
    check("no total/sum field", not any(k in pv for k in ("total", "sum", "total_amount")))

print("== settlement create + export ==")
r = c.post("/api/settlements", headers=H, json={})
check("create settlement 201", r.status_code == 201, f"({r.status_code}) {r.text[:150]}")
sid = r.json()["settlement_id"] if r.status_code == 201 else None
if sid:
    r = c.get(f"/api/settlements/{sid}/export", headers=H)
    check("export 200 xlsx", r.status_code == 200 and r.content[:2] == b"PK",
          f"({r.status_code}, {len(r.content)} bytes)")
    r = c.get("/api/settlements", headers=H)
    check("list settlements", r.status_code == 200 and len(r.json()) >= 1)
    r = c.post(f"/api/settlements/{sid}/cancel", headers=H)
    check("cancel draft 200", r.status_code == 200 and r.json()["status"] == "cancelled",
          f"({r.status_code}) {r.text[:120]}")

print("== partner login + isolation ==")
r = c.post("/api/auth/login", json={"username": "p_smoke", "password": "ppass123"})
check("partner login 200", r.status_code == 200, f"({r.status_code})")
if r.status_code == 200:
    PH = {"Authorization": f"Bearer {r.json()['access_token']}"}
    r = c.get("/api/partner/orders", headers=PH)
    check("partner orders 200", r.status_code == 200, f"({r.status_code})")
    check("partner sees own order", r.status_code == 200 and any(o["id"] == oid for o in r.json()))
    r = c.get("/api/partner/dashboard", headers=PH)
    check("partner dashboard 200", r.status_code == 200, f"({r.status_code})")
    r = c.get("/api/partner/payment-counts", headers=PH)
    check("partner payment-counts 200", r.status_code == 200, f"({r.status_code})")
    r = c.get("/api/partner/settlements", headers=PH)
    check("partner settlements 200", r.status_code == 200, f"({r.status_code})")
    # partner must NOT reach admin endpoints
    r = c.get("/api/admin/settings", headers=PH)
    check("partner blocked from admin (403)", r.status_code == 403, f"({r.status_code})")

print("== audit logs ==")
r = c.get("/api/admin/audit-logs", headers=H)
check("audit logs 200", r.status_code == 200, f"({r.status_code})")
check("audit has entries", r.status_code == 200 and len(r.json()) >= 1,
      f"count={len(r.json()) if r.status_code==200 else '?'}")

print()
print(f"RESULT: {ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
