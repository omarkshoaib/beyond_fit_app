from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, col, select

from app.auth.deps import get_current_user, get_db
from app.models import ClientProfile, PendingApproval, WorkoutHistory

logger = logging.getLogger(__name__)
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


@router.post("/generate")
def generate_plan(
    user: ClientProfile = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """Generate a fresh deterministic plan for the authenticated user and persist it."""
    from app.generator import WorkoutGenerator, SafetyRefusalError

    # Mark prior active plans as superseded; bump week if regenerating
    prior = session.exec(
        select(WorkoutHistory)
        .where(WorkoutHistory.client_id == user.client_id)
        .where(WorkoutHistory.status == "active")
    ).all()
    for p in prior:
        p.status = "superseded"
        session.add(p)
    if prior:
        user.week_number = (user.week_number or 0) + 1
    elif not user.week_number:
        user.week_number = 1

    try:
        week = WorkoutGenerator().generate(client=user)
    except SafetyRefusalError as e:
        raise HTTPException(status_code=400, detail=f"Safety gate triggered: {e.reason}")
    except Exception as e:
        logger.exception("Plan generation failed for client %s", user.client_id)
        raise HTTPException(status_code=500, detail=f"Plan generation failed: {e}")

    # If client has a coach assigned, route to PendingApproval queue
    if user.coach_id:
        approval_uuid = str(uuid.uuid4())
        pending = PendingApproval(
            approval_uuid=approval_uuid,
            client_id=user.client_id,
            client_chat_id=0,  # Mobile users have no telegram chat
            client_name=user.name or "Client",
            client_email=user.email or "",
            workout_json=week.model_dump_json(),
            coaching_message="",
            created_at=datetime.now(timezone.utc),
        )
        session.add(pending)
        session.add(user)
        session.commit()
        return {
            "status": "pending_approval",
            "approval_uuid": approval_uuid,
            "message": "Your coach is reviewing your plan. You'll see it here once approved.",
        }

    # No coach — auto-activate
    row = WorkoutHistory(
        client_id=user.client_id,
        week_number=week.week_number,
        block_number=((week.week_number - 1) // 5) + 1,
        status="active",
        plan_started_at=datetime.now(timezone.utc),
        workout_json=week.model_dump_json(),
    )
    session.add(row)
    session.add(user)
    session.commit()
    session.refresh(row)
    return _parse_plan(row)


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
    row = session.exec(
        select(WorkoutHistory)
        .where(WorkoutHistory.client_id == user.client_id)
        .where(WorkoutHistory.status == "active")
        .order_by(col(WorkoutHistory.history_id).desc())
    ).first()
    if not row:
        # Check if a pending approval exists
        pending = session.exec(
            select(PendingApproval).where(PendingApproval.client_id == user.client_id)
        ).first()
        if pending:
            return {
                "day": None,
                "day_index": 0,
                "total_days": 0,
                "no_plan": True,
                "pending_review": True,
            }
        return {"day": None, "day_index": 0, "total_days": 0, "no_plan": True, "pending_review": False}

    plan = json.loads(row.workout_json)
    days = plan.get("days", [])

    if row.plan_started_at:
        offset = (datetime.now(timezone.utc) - row.plan_started_at.replace(tzinfo=timezone.utc)).days
        idx = offset % len(days) if days else 0
    else:
        idx = datetime.now(timezone.utc).weekday() % len(days) if days else 0

    today = days[idx] if idx < len(days) else None
    return {"day": today, "day_index": idx, "total_days": len(days), "no_plan": False}


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
