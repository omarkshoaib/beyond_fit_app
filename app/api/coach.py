"""Coach endpoints — list assigned clients, approve/reject pending plans."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, col, select

from app.auth.deps import get_current_user, get_db
from app.models import ClientProfile, PendingApproval, WorkoutHistory

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/coach", tags=["coach"])


def _require_coach(user: ClientProfile) -> ClientProfile:
    if not user.is_coach:
        raise HTTPException(status_code=403, detail="Coach access required")
    return user


class RejectionRequest(BaseModel):
    feedback: str


@router.get("/clients")
def list_clients(
    user: ClientProfile = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """List all clients assigned to this coach."""
    _require_coach(user)
    rows = session.exec(
        select(ClientProfile).where(ClientProfile.coach_id == user.client_id)
    ).all()

    result = []
    for c in rows:
        # Count pending approvals
        pending_count = len(session.exec(
            select(PendingApproval).where(PendingApproval.client_id == c.client_id)
        ).all())
        result.append({
            "client_id": c.client_id,
            "name": c.name,
            "email": c.email,
            "avatar": c.avatar,
            "training_days": c.training_days,
            "experience_level": c.experience_level,
            "week_number": c.week_number,
            "pending_count": pending_count,
        })
    return result


@router.get("/pending")
def list_pending(
    user: ClientProfile = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """List all pending approvals across this coach's clients."""
    _require_coach(user)

    # Get all client IDs assigned to me
    client_rows = session.exec(
        select(ClientProfile.client_id).where(ClientProfile.coach_id == user.client_id)
    ).all()
    client_ids = [r for r in client_rows]
    if not client_ids:
        return []

    pending = session.exec(
        select(PendingApproval).where(col(PendingApproval.client_id).in_(client_ids))
    ).all()

    return [
        {
            "approval_uuid": p.approval_uuid,
            "client_id": p.client_id,
            "client_name": p.client_name,
            "client_email": p.client_email,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "coaching_message": p.coaching_message,
            "workout": json.loads(p.workout_json),
        }
        for p in pending
    ]


@router.get("/pending/{approval_uuid}")
def get_pending_detail(
    approval_uuid: str,
    user: ClientProfile = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    _require_coach(user)
    pending = session.get(PendingApproval, approval_uuid)
    if not pending:
        raise HTTPException(status_code=404, detail="Approval not found")

    client = session.get(ClientProfile, pending.client_id)
    if not client or client.coach_id != user.client_id:
        raise HTTPException(status_code=403, detail="Not your client")

    return {
        "approval_uuid": pending.approval_uuid,
        "client_id": pending.client_id,
        "client_name": pending.client_name,
        "client_email": pending.client_email,
        "created_at": pending.created_at.isoformat() if pending.created_at else None,
        "coaching_message": pending.coaching_message,
        "workout": json.loads(pending.workout_json),
        "edit_log": pending.edit_log or [],
    }


@router.post("/approve/{approval_uuid}")
def approve_plan(
    approval_uuid: str,
    user: ClientProfile = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """Approve a pending plan — moves to active WorkoutHistory and deletes the pending row."""
    _require_coach(user)
    pending = session.get(PendingApproval, approval_uuid)
    if not pending:
        raise HTTPException(status_code=404, detail="Approval not found")

    client = session.get(ClientProfile, pending.client_id)
    if not client or client.coach_id != user.client_id:
        raise HTTPException(status_code=403, detail="Not your client")

    # Mark prior active plans as superseded
    prior_active = session.exec(
        select(WorkoutHistory)
        .where(WorkoutHistory.client_id == client.client_id)
        .where(WorkoutHistory.status == "active")
    ).all()
    for p in prior_active:
        p.status = "superseded"
        session.add(p)

    workout = json.loads(pending.workout_json)
    week_num = workout.get("week_number") or client.week_number or 1

    history = WorkoutHistory(
        client_id=client.client_id,
        week_number=week_num,
        block_number=((week_num - 1) // 5) + 1,
        status="active",
        plan_started_at=datetime.now(timezone.utc),
        workout_json=pending.workout_json,
    )
    session.add(history)
    client.week_number = week_num
    session.add(client)
    session.delete(pending)
    session.commit()
    session.refresh(history)

    return {
        "ok": True,
        "history_id": history.history_id,
        "client_id": client.client_id,
        "week_number": history.week_number,
    }


@router.post("/reject/{approval_uuid}")
def reject_plan(
    approval_uuid: str,
    body: RejectionRequest,
    user: ClientProfile = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """Reject a pending plan with feedback. Plan stays pending; coach can then edit + re-approve via Telegram, or client must regenerate."""
    _require_coach(user)
    pending = session.get(PendingApproval, approval_uuid)
    if not pending:
        raise HTTPException(status_code=404, detail="Approval not found")

    client = session.get(ClientProfile, pending.client_id)
    if not client or client.coach_id != user.client_id:
        raise HTTPException(status_code=403, detail="Not your client")

    edits: list = list(pending.edit_log or [])
    edits.append({
        "at": datetime.now(timezone.utc).isoformat(),
        "by": user.client_id,
        "action": "reject",
        "feedback": body.feedback,
    })
    pending.edit_log = edits
    session.add(pending)
    session.commit()

    return {"ok": True, "feedback_logged": True}
