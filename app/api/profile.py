from __future__ import annotations

from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.auth.deps import get_current_user, get_db
from app.models import ClientProfile

router = APIRouter(prefix="/profile", tags=["profile"])


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
    allowed = {"limitations", "limitations_notes", "available_equipment", "training_days", "experience_level"}
    for key, val in updates.items():
        if key in allowed:
            setattr(user, key, val)
    session.add(user)
    session.commit()
    session.refresh(user)
    return {"updated": list(updates.keys())}
