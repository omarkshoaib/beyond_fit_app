from __future__ import annotations

import json
from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, col, select

from app.auth.deps import get_current_user, get_db
from app.models import ClientProfile, WorkoutHistory

router = APIRouter(prefix="/plans", tags=["plans"])


def _parse_plan(row: WorkoutHistory) -> Dict[str, Any]:
    data = json.loads(row.workout_json)
    return {
        "id": row.history_id,
        "week_number": row.week_number,
        "block_number": row.block_number,
        "status": row.status,
        "plan_started_at": row.plan_started_at.isoformat() if row.plan_started_at else None,
        "coaching_message": None,
        "workout": data,
    }


@router.get("/current")
def get_current_plan(
    user: ClientProfile = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    row = session.exec(
        select(WorkoutHistory)
        .where(WorkoutHistory.client_id == user.client_id)
        .where(WorkoutHistory.status == "active")
        .order_by(col(WorkoutHistory.history_id).desc())
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="No active plan")
    return _parse_plan(row)


@router.get("/today")
def get_today_session(
    user: ClientProfile = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    from datetime import datetime, timezone
    row = session.exec(
        select(WorkoutHistory)
        .where(WorkoutHistory.client_id == user.client_id)
        .where(WorkoutHistory.status == "active")
        .order_by(col(WorkoutHistory.history_id).desc())
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="No active plan")

    plan = json.loads(row.workout_json)
    days = plan.get("days", [])

    # Use plan_started_at offset to determine today's session
    if row.plan_started_at:
        offset = (datetime.now(timezone.utc) - row.plan_started_at.replace(tzinfo=timezone.utc)).days
        idx = offset % len(days) if days else 0
    else:
        idx = datetime.now(timezone.utc).weekday() % len(days) if days else 0

    today = days[idx] if idx < len(days) else None
    return {"day": today, "day_index": idx, "total_days": len(days)}


@router.get("/history")
def get_plan_history(
    user: ClientProfile = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    rows = session.exec(
        select(WorkoutHistory)
        .where(WorkoutHistory.client_id == user.client_id)
        .order_by(col(WorkoutHistory.history_id).desc())
    ).all()
    return [
        {
            "id": r.history_id,
            "week_number": r.week_number,
            "status": r.status,
            "created_at": r.plan_started_at.isoformat() if r.plan_started_at else None,
        }
        for r in rows
    ]
