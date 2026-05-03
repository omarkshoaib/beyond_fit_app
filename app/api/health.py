"""Health-check endpoint — readiness probe for ops + uptime monitors."""
from __future__ import annotations

import os
from typing import Any, Dict
from fastapi import APIRouter
from sqlalchemy import text

from app.database import engine

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> Dict[str, Any]:
    db_ok = False
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    return {
        "status": "ok" if db_ok else "degraded",
        "version": "1.1.0",
        "db": "ok" if db_ok else "fail",
        "smtp": "configured" if (os.getenv("SMTP_USER") or os.getenv("SMTP_EMAIL")) else "missing",
        "llm": "configured" if os.getenv("OPENROUTER_API_KEY") else "missing",
        "telegram_bot": "configured" if os.getenv("TELEGRAM_BOT_TOKEN") else "missing",
        "sentry": "configured" if os.getenv("SENTRY_DSN") else "off",
    }
