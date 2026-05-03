"""Lightweight audit logging — append-only AuditEvent rows."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional
import logging

from sqlmodel import Session

from app.models import AuditEvent, ClientProfile

logger = logging.getLogger(__name__)


def log_audit(
    session: Session,
    actor: ClientProfile,
    action: str,
    target: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    """Insert an AuditEvent. Failures are logged but never raised — auditing
    must not break the request that triggered it."""
    try:
        row = AuditEvent(
            actor_id=actor.client_id,
            actor_email=actor.email,
            action=action,
            target=target,
            payload=payload,
            created_at=datetime.now(timezone.utc),
        )
        session.add(row)
        session.commit()
    except Exception as e:
        logger.warning(f"Audit log failed for action={action}: {e}")
