from __future__ import annotations

import os
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlmodel import Session, select


def _set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    """Set httpOnly cookies for the web client. Skipped for native apps (they
    just read the JSON body). Cookies are cross-site-strict + Secure in prod."""
    cookie_secure = os.getenv("COOKIE_SECURE", "false").lower() == "true"
    samesite = "strict" if cookie_secure else "lax"
    response.set_cookie(
        "access_token", access_token,
        max_age=60 * 60 * 24,
        httponly=True, secure=cookie_secure, samesite=samesite, path="/",
    )
    response.set_cookie(
        "refresh_token", refresh_token,
        max_age=60 * 60 * 24 * 30,
        httponly=True, secure=cookie_secure, samesite=samesite, path="/",
    )

from app.auth.deps import get_db, get_current_user
from datetime import datetime, timezone

from app.auth.jwt import (
    create_access_token,
    create_refresh_token,
    create_reset_token,
    create_verify_token,
    decode_refresh_token,
    decode_reset_token,
    decode_verify_token,
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
    VerifyEmailRequest,
)
from app.models import ClientProfile, CoachInvite
from app.services.email_service import EmailService
from app.settings import get_settings as get_settings_dep

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(body: RegisterRequest, response: Response, session: Session = Depends(get_db)):
    existing = session.exec(select(ClientProfile).where(ClientProfile.email == body.email)).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    # Honour any pending coach invite for this email
    invite = session.exec(
        select(CoachInvite)
        .where(CoachInvite.email == body.email)
        .where(CoachInvite.accepted_at.is_(None))  # type: ignore[union-attr]
    ).first()

    client_id = str(uuid.uuid4())
    settings = get_settings_dep()
    is_super = body.email.lower() == settings.super_admin_email.lower()
    user = ClientProfile(
        client_id=client_id,
        email=body.email,
        password_hash=hash_password(body.password),
        name=body.name,
        # Auto-promote: invited coaches get coach flag, super-admin email
        # gets both. No need to wait for lifespan to self-heal.
        is_coach=(invite is not None) or is_super,
        is_admin=is_super,
    )
    session.add(user)
    if invite is not None:
        invite.accepted_at = datetime.now(timezone.utc)
        session.add(invite)
    session.commit()

    # Fire-and-forget verify email; ignore failures so signup never blocks
    EmailService.send_verification(
        recipient_email=body.email,
        verify_token=create_verify_token(client_id),
        client_name=body.name,
    )

    access = create_access_token(client_id)
    refresh = create_refresh_token(client_id)
    _set_auth_cookies(response, access, refresh)
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, response: Response, session: Session = Depends(get_db)):
    user = session.exec(select(ClientProfile).where(ClientProfile.email == body.email)).first()
    if not user or not user.password_hash or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    access = create_access_token(user.client_id)
    refresh = create_refresh_token(user.client_id)
    _set_auth_cookies(response, access, refresh)
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/refresh", response_model=TokenResponse)
def refresh(
    body: RefreshRequest,
    response: Response,
    request: Request,
    session: Session = Depends(get_db),
):
    """Trade a valid refresh token for a fresh access + refresh pair (rotation).
    Accepts the token from the JSON body OR the `refresh_token` cookie."""
    token = body.refresh_token or request.cookies.get("refresh_token") or ""
    client_id = decode_refresh_token(token)
    if client_id is None:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    user = session.get(ClientProfile, client_id)
    if user is None:
        raise HTTPException(status_code=401, detail="User no longer exists")
    access = create_access_token(client_id)
    new_refresh = create_refresh_token(client_id)
    _set_auth_cookies(response, access, new_refresh)
    return TokenResponse(access_token=access, refresh_token=new_refresh)


@router.post("/logout")
def logout(response: Response):
    """Clear auth cookies. Idempotent — safe to call when already signed out."""
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    return {"ok": True}


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


@router.post("/verify")
def verify_email(body: VerifyEmailRequest, session: Session = Depends(get_db)):
    """Consume an email_verify token and stamp verified_at on the user."""
    client_id = decode_verify_token(body.token)
    if client_id is None:
        raise HTTPException(status_code=400, detail="Verification link is invalid or expired")
    user = session.get(ClientProfile, client_id)
    if user is None:
        raise HTTPException(status_code=400, detail="User no longer exists")
    if user.verified_at is None:
        user.verified_at = datetime.now(timezone.utc)
        session.add(user)
        session.commit()
    return {"ok": True, "verified_at": user.verified_at.isoformat() if user.verified_at else None}


@router.post("/resend-verification")
def resend_verification(user: ClientProfile = Depends(get_current_user)):
    """Send a fresh verification email to the current user. No-op if already verified."""
    if user.verified_at is not None:
        return {"ok": True, "already_verified": True}
    if user.email and user.client_id:
        EmailService.send_verification(
            recipient_email=user.email,
            verify_token=create_verify_token(user.client_id),
            client_name=user.name or "Athlete",
        )
    return {"ok": True, "already_verified": False}


@router.get("/me")
def me(user: ClientProfile = Depends(get_current_user)):
    settings = get_settings_dep()
    is_super = bool(user.email and user.email == settings.super_admin_email)
    return {
        "client_id": user.client_id,
        "email": user.email,
        "name": getattr(user, "name", None),
        "avatar": user.avatar,
        "experience_level": user.experience_level,
        "training_days": user.training_days,
        "is_coach": user.is_coach,
        "is_admin": user.is_admin,
        "is_super_admin": is_super,
        "coach_id": user.coach_id,
        "week_number": user.week_number,
        "verified_at": user.verified_at.isoformat() if user.verified_at else None,
    }


@router.get("/whoami")
def whoami(request: Request, user: ClientProfile = Depends(get_current_user)):
    """Diagnostic endpoint: shows exactly what the server resolved + how it
    found the token. Useful for debugging 403s after role changes."""
    settings = get_settings_dep()
    return {
        "client_id": user.client_id,
        "email": user.email,
        "is_coach": user.is_coach,
        "is_admin": user.is_admin,
        "is_super_admin": user.email == settings.super_admin_email,
        "coach_id": user.coach_id,
        "verified_at": user.verified_at.isoformat() if user.verified_at else None,
        "auth_source": {
            "has_bearer_header": "authorization" in {k.lower() for k in request.headers.keys()},
            "has_access_token_cookie": "access_token" in request.cookies,
        },
    }
