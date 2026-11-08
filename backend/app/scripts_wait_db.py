"""Tiny helper used by the container entrypoint to wait for the database.

Exits 0 as soon as the database answers `SELECT 1`, non-zero otherwise.
Kept as a module (not an inline heredoc) so the shell loop stays simple.
"""
from __future__ import annotations

import os
import sys


def main() -> int:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        return 0
    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return 0
    except Exception as exc:  # noqa: BLE001 - any failure means "not ready yet"
        print(f"[wait_db] not ready: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
