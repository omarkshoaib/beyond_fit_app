from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from app.auth.deps import get_db, get_current_user
from app.auth.jwt import create_access_token, create_refresh_token, hash_password, verify_password
from app.auth.schemas import LoginRequest, RegisterRequest, TokenResponse
from app.models import ClientProfile

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
