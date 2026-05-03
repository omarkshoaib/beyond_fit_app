"""Admin endpoints — manage coaches and client assignments."""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.auth.deps import get_current_user, get_db
from app.models import ClientProfile

router = APIRouter(prefix="/admin", tags=["admin"])


def _require_admin(user: ClientProfile) -> ClientProfile:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


class PromoteRequest(BaseModel):
    email: str
    is_coach: bool = True
    is_admin: Optional[bool] = None


class AssignRequest(BaseModel):
    client_email: str
    coach_email: str


@router.get("/clients")
def list_all_clients(
    user: ClientProfile = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    _require_admin(user)
    rows = session.exec(select(ClientProfile)).all()
    return [
        {
            "client_id": c.client_id,
            "name": c.name,
            "email": c.email,
            "is_coach": c.is_coach,
            "is_admin": c.is_admin,
            "coach_id": c.coach_id,
            "avatar": c.avatar,
        }
        for c in rows
    ]


@router.get("/coaches")
def list_coaches(
    user: ClientProfile = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    _require_admin(user)
    rows = session.exec(select(ClientProfile).where(ClientProfile.is_coach == True)).all()  # noqa: E712
    return [
        {
            "client_id": c.client_id,
            "name": c.name,
            "email": c.email,
            "is_admin": c.is_admin,
        }
        for c in rows
    ]


@router.post("/promote")
def promote_user(
    body: PromoteRequest,
    user: ClientProfile = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    _require_admin(user)
    target = session.exec(select(ClientProfile).where(ClientProfile.email == body.email)).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    target.is_coach = body.is_coach
    if body.is_admin is not None:
        target.is_admin = body.is_admin
    session.add(target)
    session.commit()
    return {
        "ok": True,
        "client_id": target.client_id,
        "is_coach": target.is_coach,
        "is_admin": target.is_admin,
    }


@router.post("/assign")
def assign_client_to_coach(
    body: AssignRequest,
    user: ClientProfile = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    _require_admin(user)
    coach = session.exec(select(ClientProfile).where(ClientProfile.email == body.coach_email)).first()
    client = session.exec(select(ClientProfile).where(ClientProfile.email == body.client_email)).first()
    if not coach or not coach.is_coach:
        raise HTTPException(status_code=400, detail="Coach not found or not promoted")
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    client.coach_id = coach.client_id
    session.add(client)
    session.commit()
    return {
        "ok": True,
        "client_id": client.client_id,
        "coach_id": coach.client_id,
    }
