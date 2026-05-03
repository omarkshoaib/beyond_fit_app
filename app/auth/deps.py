from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session

from app.auth.jwt import decode_token
from app.database import engine
from app.models import ClientProfile

# auto_error=False so we can fall back to cookie auth for the web client.
bearer = HTTPBearer(auto_error=False)


def get_db():
    with Session(engine) as session:
        yield session


def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
    session: Session = Depends(get_db),
) -> ClientProfile:
    """Resolve user from either an `Authorization: Bearer <jwt>` header (native
    apps) or an `access_token` cookie (web). Header wins if both are present."""
    token: Optional[str] = None
    if credentials is not None:
        token = credentials.credentials
    if token is None:
        token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    client_id = decode_token(token)
    if client_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user = session.get(ClientProfile, client_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user
