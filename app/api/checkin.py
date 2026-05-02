from __future__ import annotations

from typing import Any, Dict, List
from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.auth.deps import get_current_user, get_db
from app.models import CheckIn, ClientProfile

router = APIRouter(prefix="/checkin", tags=["checkin"])


@router.get("/history")
def get_checkin_history(
    user: ClientProfile = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    rows = session.exec(
        select(CheckIn)
        .where(CheckIn.client_id == user.client_id)
        .order_by(CheckIn.created_at.desc())
    ).all()
    return [
        {
            "id": r.id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "digest": r.digest_markdown,
            "needs_review": r.needs_coach_review,
        }
        for r in rows
    ]


@router.post("")
def submit_checkin(
    body: Dict[str, Any],
    user: ClientProfile = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    # Accepts raw check-in JSON from mobile app structured check-in flow
    # Body: {"exercises": [...], "general": {...}}
    checkin = CheckIn(
        client_id=user.client_id,
        raw_text=str(body),
        extraction_json=None,
        structured_progress=body,
    )
    session.add(checkin)
    session.commit()
    session.refresh(checkin)
    return {"id": checkin.id, "status": "received"}
