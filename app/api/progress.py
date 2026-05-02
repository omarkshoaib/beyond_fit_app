from __future__ import annotations

import json
from typing import Any, Dict, List
from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.auth.deps import get_current_user, get_db
from app.models import CheckIn, ClientProfile, WorkoutHistory

router = APIRouter(prefix="/progress", tags=["progress"])


@router.get("")
def get_progress(
    user: ClientProfile = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    plans = session.exec(
        select(WorkoutHistory)
        .where(WorkoutHistory.client_id == user.client_id)
        .where(WorkoutHistory.status.in_(["active", "approved", "superseded"]))
        .order_by(WorkoutHistory.history_id.asc())
    ).all()

    weight_trend = []
    rpe_trend = []

    for plan in plans:
        try:
            data = json.loads(plan.workout_json)
            week_num = plan.week_number
            for day in data.get("days", []):
                for slot in day.get("slots", []):
                    if slot.get("actual_rpe") and slot.get("slot_type") in ("main_compound", None):
                        rpe_trend.append({
                            "week": week_num,
                            "exercise": slot.get("exercise_name"),
                            "target_rpe": slot.get("rpe"),
                            "actual_rpe": slot.get("actual_rpe"),
                            "target_weight": slot.get("target_weight"),
                            "actual_weight": slot.get("actual_weight"),
                        })
        except (json.JSONDecodeError, KeyError):
            continue

    return {"rpe_trend": rpe_trend, "weight_trend": weight_trend, "weeks_completed": len(plans)}
