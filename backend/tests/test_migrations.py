"""Guards the migration chain and the name-only `products` shape.

The subtle bug these lock down: **an already-published Alembic revision is never
re-run.** Editing `c3e8f1a94b21` in place after it shipped left databases
stamped at that revision with three columns still present, because Alembic only
compares revision ids. `d5a7c3e91b44` exists to reconcile that, and the tests
below make sure it stays idempotent and reachable.
"""

import subprocess
import os
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND_DIR = Path(__file__).resolve().parents[1]

EXPECTED_PRODUCTS_COLUMNS = {"id", "name", "is_active", "created_at", "updated_at"}
EXPECTED_HEAD = "a91c7e4f2b3d"


def _isolated_tmpdir() -> Path:
    """pytest's tmp_path can collide under this sandbox; make our own."""
    path = Path(tempfile.mkdtemp(prefix=f"of_mig_{uuid.uuid4().hex}_"))
    return path


def _alembic_env(url: str, tmp_path: Path) -> dict:
    """Environment for a subprocess alembic run.

    PATH is inherited rather than hardcoded to POSIX paths: on Windows the
    interpreter needs the real PATH to resolve its own DLLs, and replacing it
    with /usr/bin:/bin made every subprocess crash. PYTHONIOENCODING keeps the
    child's output UTF-8 so a non-UTF-8 console locale cannot kill the reader
    thread with a UnicodeDecodeError.
    """
    env = dict(os.environ)
    env.update({
        "DATABASE_URL": url,
        "APP_SECRET_KEY": "test",
        "APP_ENV": "test",
        "LOCAL_STORAGE_PATH": str(tmp_path),
        "PYTHONIOENCODING": "utf-8",
    })
    return env


def _script_directory() -> ScriptDirectory:
    return ScriptDirectory.from_config(Config(str(BACKEND_DIR / "alembic.ini")))


def test_migration_chain_is_linear_and_has_one_head():
    script = _script_directory()
    revisions = [r.revision for r in script.walk_revisions()][::-1]
    assert revisions == [
        "7333717e53eb",
        "9f4d1b8a2c77",
        "c3e8f1a94b21",
        "d5a7c3e91b44",
        "e8b2d4f60c17",
        "f2c9e6b48d05",
        "a7f3c9d2b1e4",
        "b6d1f7a30e58",
        "d1a7c4e92f60",
        "c8d4f2a91b70",
        "a91c7e4f2b3d",
    ], f"unexpected migration chain: {revisions}"
    assert script.get_current_head() == EXPECTED_HEAD


def test_shipped_revision_does_not_try_to_drop_code():
    """`c3e8f1a94b21` already shipped; it must not be edited to drop more.

    Databases already stamped at that id will never re-run it, so any new
    work has to live in a later revision.
    """
    source = (BACKEND_DIR / "migrations" / "versions"
              / "c3e8f1a94b21_simplify_products_into_types.py").read_text()
    upgrade_body = source.split("def upgrade")[1].split("def downgrade")[0]
    assert "op.drop_column(\"products\", \"code\")" not in upgrade_body
    assert "default_currency" not in upgrade_body


def test_reconciliation_revision_handles_half_migrated_database():
    """A DB stamped at c3e8f1a94b21 with leftovers must reach the final shape."""
    import sqlalchemy as sa

    tmp_path = _isolated_tmpdir()
    db_path = tmp_path / "half.db"
    url = f"sqlite:///{db_path}"
    env = _alembic_env(url, tmp_path)

    def run_alembic(*args):
        return subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=str(BACKEND_DIR), env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )

    # 1) Build the v3 schema.
    assert run_alembic("upgrade", "9f4d1b8a2c77").returncode == 0

    # 2) Simulate the half-migrated state: flags gone, leftovers remain,
    #    version stamped at c3e8f1a94b21.
    engine = sa.create_engine(url)
    with engine.begin() as conn:
        for col in ("require_amount", "require_email", "require_password", "allow_screenshot"):
            conn.exec_driver_sql(f"ALTER TABLE products DROP COLUMN {col}")
        conn.exec_driver_sql(
            "INSERT INTO products (name, code, default_currency, is_active,"
            " created_at, updated_at)"
            " VALUES ('Netflix', 'NF', 'INR', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        conn.exec_driver_sql("UPDATE alembic_version SET version_num='c3e8f1a94b21'")

    # 3) `upgrade head` must reconcile it.
    result = run_alembic("upgrade", "head")
    assert result.returncode == 0, result.stderr

    inspector = sa.inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("products")}
    assert cols == EXPECTED_PRODUCTS_COLUMNS, f"leftover columns: {cols}"

    # Data must survive.
    with engine.connect() as conn:
        names = {r[0] for r in conn.exec_driver_sql("SELECT name FROM products")}
    assert "Netflix" in names


def test_reconciliation_is_idempotent():
    """Running the chain twice must not error or change anything."""
    import sqlalchemy as sa

    tmp_path = _isolated_tmpdir()
    db_path = tmp_path / "idem.db"
    url = f"sqlite:///{db_path}"
    env = _alembic_env(url, tmp_path)

    def run_alembic(*args):
        return subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=str(BACKEND_DIR), env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )

    assert run_alembic("upgrade", "head").returncode == 0
    assert run_alembic("upgrade", "head").returncode == 0

    engine = sa.create_engine(url)
    cols = {c["name"] for c in sa.inspect(engine).get_columns("products")}
    assert cols == EXPECTED_PRODUCTS_COLUMNS