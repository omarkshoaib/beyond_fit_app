"""Per-set logger — clients log actual reps + weight as they finish each set."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, col, select

from app.auth.deps import get_current_user, get_db
from app.models import ClientProfile, SetLog

router = APIRouter(prefix="/sets", tags=["sets"])


class SetLogRequest(BaseModel):
    history_id: int
    day_index: int
    slot_index: int
    set_index: int
    actual_reps: int
    actual_weight: float
    rpe: Optional[int] = None


@router.post("")
def log_set(
    body: SetLogRequest,
    user: ClientProfile = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    row = SetLog(
        client_id=user.client_id,
        history_id=body.history_id,
        day_index=body.day_index,
        slot_index=body.slot_index,
        set_index=body.set_index,
        actual_reps=body.actual_reps,
        actual_weight=body.actual_weight,
        rpe=body.rpe,
        logged_at=datetime.now(timezone.utc),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return {"ok": True, "id": row.id}


@router.get("/by-history/{history_id}")
def list_sets_for_history(
    history_id: int,
    user: ClientProfile = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    rows = session.exec(
        select(SetLog)
        .where(SetLog.client_id == user.client_id)
        .where(SetLog.history_id == history_id)
        .order_by(col(SetLog.id))
    ).all()
    return [
        {
            "id": r.id,
            "day_index": r.day_index,
            "slot_index": r.slot_index,
            "set_index": r.set_index,
            "actual_reps": r.actual_reps,
            "actual_weight": r.actual_weight,
            "rpe": r.rpe,
            "logged_at": r.logged_at.isoformat() if r.logged_at else None,
        }
        for r in rows
    ]
