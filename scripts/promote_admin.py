"""Promote a user to admin (and optionally coach) by email.

Usage:
    python scripts/promote_admin.py admin@example.com
    python scripts/promote_admin.py coach@example.com --coach-only
"""
from __future__ import annotations

import argparse
import sys
from sqlmodel import Session, create_engine, select

from app.settings import get_settings
from app.models import ClientProfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("email", help="User email to promote")
    parser.add_argument("--coach-only", action="store_true", help="Only set is_coach, not is_admin")
    args = parser.parse_args()

    settings = get_settings()
    connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    engine = create_engine(settings.database_url, connect_args=connect_args)

    with Session(engine) as session:
        user = session.exec(select(ClientProfile).where(ClientProfile.email == args.email)).first()
        if not user:
            print(f"❌ No user found with email: {args.email}")
            sys.exit(1)

        user.is_coach = True
        if not args.coach_only:
            user.is_admin = True

        session.add(user)
        session.commit()
        session.refresh(user)

    role = "coach" if args.coach_only else "admin + coach"
    print(f"✅ Promoted {user.email} ({user.name}) to {role}")
    print(f"   client_id: {user.client_id}")
    print(f"   is_admin:  {user.is_admin}")
    print(f"   is_coach:  {user.is_coach}")


if __name__ == "__main__":
    main()
