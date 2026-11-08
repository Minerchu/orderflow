import os
import tempfile
import uuid

# ---- Set environment BEFORE importing any app module ----
os.environ.setdefault("APP_ENV", "test")
os.environ["APP_SECRET_KEY"] = "test_secret_key_for_tests_only"
os.environ["SESSION_SECRET"] = "test_session_secret_for_tests_only"
# Unique DB file per process run (Windows temp dirs are not auto-cleaned,
# so a stale file with a different schema would break create_all).
_TEST_DB_DIR = tempfile.mkdtemp()
_TEST_DB_PATH = os.path.join(_TEST_DB_DIR, f"test_{uuid.uuid4().hex}.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH}"
os.environ["STORAGE_BACKEND"] = "local"
os.environ["LOCAL_STORAGE_PATH"] = tempfile.mkdtemp()
os.environ["TELEGRAM_BOT_TOKEN"] = ""  # no real token in tests
# Tests exercise the send path via the in-memory client. Production forbids this.
os.environ["TELEGRAM_DRY_RUN"] = "true"
os.environ["TELEGRAM_WEBHOOK_SECRET"] = "test_webhook_secret"

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.db.base import Base
from app.db import models  # noqa: F401  (register every table before create_all)
from app.db.session import get_db
from app.config import settings
from app.constants import ROLE_ADMIN, ROLE_PARTNER
from app.core.security import hash_password
from app.db.models.user import User

# File-based sqlite: each session gets its own connection, so there is no
# shared-connection lock contention. Schema is created once for the whole suite;
# each test isolates its data by deleting all rows in teardown (no per-test DDL,
# which avoids SQLite "index already exists" lock issues between tests).
engine = create_engine(settings.DATABASE_URL, future=True, pool_pre_ping=True)
TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base.metadata.create_all(bind=engine)


@pytest.fixture
def db():
    s = TestSession()
    try:
        yield s
    finally:
        # Clean all data so tests are isolated (children first).
        for table in reversed(Base.metadata.sorted_tables):
            s.execute(table.delete())
        s.commit()
        s.close()


@pytest.fixture
def client(db):
    from app.main import app

    def override_get_db():
        # Independent session per request; all sessions share the same file-based
        # sqlite database so data is visible across them.
        s = TestSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _make_user(username, password, role, **kw):
    s = TestSession()
    u = User(
        username=username,
        password_hash=hash_password(password),
        role=role,
        is_active=True,
        **kw,
    )
    s.add(u)
    s.commit()
    s.refresh(u)
    uid = u.id
    s.close()
    return uid


def _login(c, username, password):
    r = c.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture
def admin(client):
    _make_user("admin", "adminpass", ROLE_ADMIN)
    return _login(client, "admin", "adminpass")


@pytest.fixture
def partner(client):
    _make_user("partner1", "ppass", ROLE_PARTNER)
    return _login(client, "partner1", "ppass")


@pytest.fixture
def partner2(client):
    _make_user("partner2", "ppass2", ROLE_PARTNER)
    return _login(client, "partner2", "ppass2")
