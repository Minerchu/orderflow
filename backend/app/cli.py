from __future__ import annotations

import argparse

from app.config import settings
from app.constants import ROLE_ADMIN
from app.core.security import hash_password
from app.db.base import Base
from app.db.models import User
from app.db.session import SessionLocal, engine


def init_admin(username: str, password: str) -> None:
    # Ensure tables exist (dev convenience; production uses alembic).
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.username == username).first()
        if existing:
            print(f"[orderflow] admin '{username}' already exists.")
            return
        user = User(
            username=username,
            password_hash=hash_password(password),
            role=ROLE_ADMIN,
            is_active=True,
        )
        db.add(user)
        db.commit()
        print(f"[orderflow] admin '{username}' created.")
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(prog="orderflow")
    sub = parser.add_subparsers(dest="command")
    p = sub.add_parser("init-admin", help="Create the first system administrator.")
    p.add_argument("--username", required=True)
    p.add_argument("--password", required=True)
    args = parser.parse_args()

    if args.command == "init-admin":
        init_admin(args.username, args.password)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
