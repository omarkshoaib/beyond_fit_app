from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from app.auth.deps import get_db, get_current_user
from app.auth.jwt import (
    create_access_token,
    create_refresh_token,
    create_reset_token,
    decode_refresh_token,
    decode_reset_token,
    hash_password,
    verify_password,
)
from app.auth.schemas import (
    ForgotPasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
)
from app.models import ClientProfile
from app.services.email_service import EmailService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(body: RegisterRequest, session: Session = Depends(get_db)):
    existing = session.exec(select(ClientProfile).where(ClientProfile.email == body.email)).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    client_id = str(uuid.uuid4())
    user = ClientProfile(
        client_id=client_id,
        email=body.email,
        password_hash=hash_password(body.password),
        name=body.name,
    )
    session.add(user)
    session.commit()

    return TokenResponse(
        access_token=create_access_token(client_id),
        refresh_token=create_refresh_token(client_id),
    )


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, session: Session = Depends(get_db)):
    user = session.exec(select(ClientProfile).where(ClientProfile.email == body.email)).first()
    if not user or not user.password_hash or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    return TokenResponse(
        access_token=create_access_token(user.client_id),
        refresh_token=create_refresh_token(user.client_id),
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh(body: RefreshRequest, session: Session = Depends(get_db)):
    """Trade a valid refresh token for a fresh access + refresh pair (rotation)."""
    client_id = decode_refresh_token(body.refresh_token)
    if client_id is None:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    user = session.get(ClientProfile, client_id)
    if user is None:
        raise HTTPException(status_code=401, detail="User no longer exists")
    return TokenResponse(
        access_token=create_access_token(client_id),
        refresh_token=create_refresh_token(client_id),
    )


@router.post("/forgot")
def forgot_password(body: ForgotPasswordRequest, session: Session = Depends(get_db)):
    """Send a password-reset email if the address exists. Always returns 200
    so callers can't enumerate accounts."""
    user = session.exec(select(ClientProfile).where(ClientProfile.email == body.email)).first()
    if user and user.client_id:
        token = create_reset_token(user.client_id)
        EmailService.send_password_reset(
            recipient_email=body.email,
            reset_token=token,
            client_name=user.name or "Athlete",
        )
    # Don't leak whether email is registered
    return {"ok": True, "message": "If that email is registered, a reset link is on the way."}


@router.post("/reset", response_model=TokenResponse)
def reset_password(body: ResetPasswordRequest, session: Session = Depends(get_db)):
    """Consume a reset token and set a new password. Returns fresh tokens so
    user is signed in immediately."""
    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    client_id = decode_reset_token(body.token)
    if client_id is None:
        raise HTTPException(status_code=400, detail="Reset link is invalid or expired")
    user = session.get(ClientProfile, client_id)
    if user is None:
        raise HTTPException(status_code=400, detail="Reset link is invalid or expired")
    user.password_hash = hash_password(body.new_password)
    session.add(user)
    session.commit()
    return TokenResponse(
        access_token=create_access_token(client_id),
        refresh_token=create_refresh_token(client_id),
    )


@router.get("/me")
def me(user: ClientProfile = Depends(get_current_user)):
    return {
        "client_id": user.client_id,
        "email": user.email,
        "name": getattr(user, "name", None),
        "avatar": user.avatar,
        "experience_level": user.experience_level,
        "training_days": user.training_days,
        "is_coach": user.is_coach,
        "is_admin": user.is_admin,
        "coach_id": user.coach_id,
        "week_number": user.week_number,
    }
