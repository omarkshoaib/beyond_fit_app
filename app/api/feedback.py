"""In-app feedback — clients send a message + optional app version."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.auth.deps import get_current_user, get_db
from app.models import ClientProfile, Feedback

router = APIRouter(prefix="/feedback", tags=["feedback"])


class FeedbackRequest(BaseModel):
    message: str
    app_version: Optional[str] = None


@router.post("")
def submit_feedback(
    body: FeedbackRequest,
    user: ClientProfile = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    row = Feedback(
        client_id=user.client_id,
        email=user.email,
        message=body.message.strip()[:5000],
        app_version=body.app_version,
        created_at=datetime.now(timezone.utc),
    )
    session.add(row)
    session.commit()
    return {"ok": True}
