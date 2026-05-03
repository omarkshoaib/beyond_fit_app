from __future__ import annotations

import json
from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.auth.deps import get_current_user, get_db
from app.models import (
    ClientProfile, WorkoutHistory, PendingApproval, RejectionFeedback,
    SetLog, Feedback, CoachInvite, AuditEvent, ProfileSnapshot,
)

router = APIRouter(prefix="/profile", tags=["profile"])


# Allowed fields a client can update on themselves. Avatar is locked after
# onboarding; training prefs + injuries can change anytime.
_UPDATABLE = {
    "avatar", "limitations", "limitations_notes", "available_equipment",
    "training_days", "experience_level",
}


@router.get("")
def get_profile(user: ClientProfile = Depends(get_current_user)):
    return {
        "client_id": user.client_id,
        "email": user.email,
        "name": getattr(user, "name", None),
        "avatar": user.avatar,
        "training_days": user.training_days,
        "experience_level": user.experience_level,
        "limitations": user.limitations,
        "limitations_notes": getattr(user, "limitations_notes", None),
        "available_equipment": user.available_equipment,
        "coach_overrides": user.coach_overrides,
        "week_number": user.week_number,
    }


@router.put("")
def update_profile(
    updates: Dict[str, Any],
    user: ClientProfile = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    for key, val in updates.items():
        if key in _UPDATABLE:
            setattr(user, key, val)
    session.add(user)
    session.commit()
    session.refresh(user)
    return {"updated": [k for k in updates.keys() if k in _UPDATABLE]}


@router.get("/export")
def export_my_data(
    user: ClientProfile = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    """GDPR / right-of-access export. Returns every row associated with this
    user as plain JSON the client can save."""
    cid = user.client_id

    def _dump(rows):
        return [r.model_dump(mode="json") for r in rows]

    history = session.exec(select(WorkoutHistory).where(WorkoutHistory.client_id == cid)).all()
    pending = session.exec(select(PendingApproval).where(PendingApproval.client_id == cid)).all()
    rejections = session.exec(select(RejectionFeedback).where(RejectionFeedback.client_id == cid)).all()
    sets = session.exec(select(SetLog).where(SetLog.client_id == cid)).all()
    feedback = session.exec(select(Feedback).where(Feedback.client_id == cid)).all()
    snapshots = session.exec(select(ProfileSnapshot).where(ProfileSnapshot.client_id == cid)).all()
    invite = None
    if user.email:
        invite = session.exec(select(CoachInvite).where(CoachInvite.email == user.email)).first()
    audit = session.exec(select(AuditEvent).where(AuditEvent.actor_id == cid)).all()

    return {
        "profile": user.model_dump(mode="json"),
        "workout_history": _dump(history),
        "pending_approvals": _dump(pending),
        "rejection_feedback": _dump(rejections),
        "set_logs": _dump(sets),
        "feedback": _dump(feedback),
        "profile_snapshots": _dump(snapshots),
        "coach_invite": invite.model_dump(mode="json") if invite else None,
        "audit_events": _dump(audit),
    }


@router.delete("")
def delete_my_account(
    user: ClientProfile = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """Soft-delete: anonymises the profile (clears name + email, scrambles
    client_id linkage) so historical training rows can stay for aggregate
    analytics without identifying the user. Refuses to delete the super-admin."""
    from app.settings import get_settings as _gs
    if user.email == _gs().super_admin_email:
        raise HTTPException(status_code=400, detail="Super-admin cannot delete their account")

    # Anonymise
    user.name = None
    user.email = None
    user.password_hash = None
    user.is_admin = False
    user.is_coach = False
    user.coach_id = None
    user.verified_at = None
    user.limitations_notes = None
    user.safety_override_note = None
    session.add(user)

    # Drop pending approvals (no point keeping)
    pendings = session.exec(
        select(PendingApproval).where(PendingApproval.client_id == user.client_id)
    ).all()
    for p in pendings:
        session.delete(p)

    session.commit()
    return {"ok": True, "anonymised": True}
