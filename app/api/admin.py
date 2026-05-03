"""Admin endpoints — manage coaches, admins, invites, and client assignments."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.auth.deps import get_current_user, get_db
from app.models import ClientProfile, CoachInvite
from app.services.email_service import EmailService
from app.settings import get_settings

router = APIRouter(prefix="/admin", tags=["admin"])


def _require_admin(user: ClientProfile) -> ClientProfile:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def _require_super_admin(user: ClientProfile) -> ClientProfile:
    settings = get_settings()
    if user.email != settings.super_admin_email:
        raise HTTPException(status_code=403, detail="Super-admin access required")
    return user


def _is_super_admin_email(email: Optional[str]) -> bool:
    if not email:
        return False
    return email == get_settings().super_admin_email


class PromoteRequest(BaseModel):
    email: str
    is_coach: bool = True
    is_admin: Optional[bool] = None


class AssignRequest(BaseModel):
    client_email: str
    coach_email: str


class InviteRequest(BaseModel):
    email: str


class AdminEmailRequest(BaseModel):
    email: str


# ─── Clients ──────────────────────────────────────────────────────────────────

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
            "is_super_admin": _is_super_admin_email(c.email),
            "coach_id": c.coach_id,
            "avatar": c.avatar,
        }
        for c in rows
    ]


# ─── Coaches ──────────────────────────────────────────────────────────────────

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
            "is_super_admin": _is_super_admin_email(c.email),
        }
        for c in rows
    ]


@router.get("/coaches/invites")
def list_coach_invites(
    user: ClientProfile = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Pending (unaccepted) coach invites."""
    _require_admin(user)
    rows = session.exec(
        select(CoachInvite).where(CoachInvite.accepted_at.is_(None))  # type: ignore[union-attr]
    ).all()
    return [
        {
            "id": r.id,
            "email": r.email,
            "invited_by": r.invited_by,
            "invited_at": r.invited_at.isoformat() if r.invited_at else None,
        }
        for r in rows
    ]


@router.post("/coaches/invite")
def invite_coach(
    body: InviteRequest,
    user: ClientProfile = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    _require_admin(user)
    email = body.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Invalid email")

    # If they're already registered as a coach, no-op.
    existing_user = session.exec(select(ClientProfile).where(ClientProfile.email == email)).first()
    if existing_user and existing_user.is_coach:
        return {"ok": True, "already_coach": True, "email": email}

    # Idempotent: refresh invite if it exists
    existing_invite = session.exec(select(CoachInvite).where(CoachInvite.email == email)).first()
    if existing_invite:
        existing_invite.invited_at = datetime.now(timezone.utc)
        existing_invite.invited_by = user.client_id
        session.add(existing_invite)
        session.commit()
    else:
        invite = CoachInvite(
            email=email,
            invited_by=user.client_id,
            invited_at=datetime.now(timezone.utc),
        )
        session.add(invite)
        session.commit()

    EmailService.send_coach_invite(recipient_email=email, invited_by_name=user.name or "an admin")
    return {"ok": True, "email": email}


@router.delete("/coaches/invite/{email}")
def withdraw_coach_invite(
    email: str,
    user: ClientProfile = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    _require_admin(user)
    email = email.strip().lower()
    invite = session.exec(select(CoachInvite).where(CoachInvite.email == email)).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.accepted_at is not None:
        raise HTTPException(status_code=400, detail="Invite already accepted")
    session.delete(invite)
    session.commit()
    return {"ok": True}


# ─── Admins (super-admin only) ────────────────────────────────────────────────

@router.get("/admins")
def list_admins(
    user: ClientProfile = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    _require_super_admin(user)
    rows = session.exec(select(ClientProfile).where(ClientProfile.is_admin == True)).all()  # noqa: E712
    return [
        {
            "client_id": c.client_id,
            "name": c.name,
            "email": c.email,
            "is_super_admin": _is_super_admin_email(c.email),
        }
        for c in rows
    ]


@router.post("/admins/promote")
def promote_admin(
    body: AdminEmailRequest,
    user: ClientProfile = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    _require_super_admin(user)
    target = session.exec(select(ClientProfile).where(ClientProfile.email == body.email)).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found — they must register first")
    target.is_admin = True
    target.is_coach = True  # admins are also coaches by default
    session.add(target)
    session.commit()
    return {"ok": True, "client_id": target.client_id, "email": target.email}


@router.post("/admins/demote")
def demote_admin(
    body: AdminEmailRequest,
    user: ClientProfile = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    _require_super_admin(user)
    if _is_super_admin_email(body.email):
        raise HTTPException(status_code=400, detail="Cannot demote the super-admin")
    target = session.exec(select(ClientProfile).where(ClientProfile.email == body.email)).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    target.is_admin = False
    session.add(target)
    session.commit()
    return {"ok": True, "client_id": target.client_id, "email": target.email}


# ─── Legacy promote (kept for backwards compat with bootstrap script) ────────

@router.post("/promote")
def promote_user(
    body: PromoteRequest,
    user: ClientProfile = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """Legacy endpoint. Prefer /admins/promote (super-admin) or /coaches/invite (admin)."""
    _require_admin(user)
    if body.is_admin and not _is_super_admin_email(user.email):
        raise HTTPException(status_code=403, detail="Only the super-admin can promote admins")
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


# ─── Assignments ──────────────────────────────────────────────────────────────

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
        raise HTTPException(status_code=400, detail="Coach not found or not a coach yet")
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    client.coach_id = coach.client_id
    session.add(client)
    session.commit()
    return {"ok": True, "client_id": client.client_id, "coach_id": coach.client_id}
