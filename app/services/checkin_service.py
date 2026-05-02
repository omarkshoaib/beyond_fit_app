"""
CheckInService: orchestrates free-form check-in ingestion.

Flow:
  1. ingest()           — persist raw text, run extraction, derive digest
  2. apply_autoregulation() — run derive_plan_delta + apply_delta, store resulting plan
  3. request_clarifications() — return the clarifying questions from the extraction
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, select

from app.adapters.llm.extractors import extract_checkin, render_digest
from app.adapters.llm.openrouter import LLMClient
from app.domain.checkin.schema import CheckInExtraction
from app.domain.workout.autoregulation import derive_plan_delta, apply_delta
from app.exercise_db import get_exercise_db
from app.models import CheckIn, ClientProfile, WorkoutHistory, WorkoutWeek

logger = logging.getLogger(__name__)


class CheckInService:
    def __init__(self, session: Session, llm: LLMClient) -> None:
        self._session = session
        self._llm = llm
        self._lift_catalog = [ex["exercise_id"] for ex in get_exercise_db()]

    def ingest(self, client_id: str, raw_text: str) -> CheckIn:
        """
        Persist the raw check-in text, run LLM extraction, render coach digest.
        Returns the saved CheckIn row (with extraction_json populated).
        """
        session = self._session

        # Find the client's current active workout plan
        active_plan_row = session.exec(
            select(WorkoutHistory)
            .where(WorkoutHistory.client_id == client_id)
            .where(WorkoutHistory.status == "active")
        ).first()

        # Build prior profile JSON for context
        client = session.get(ClientProfile, client_id)
        prior_profile = client.model_dump_json() if client else "{}"

        extraction = extract_checkin(
            llm=self._llm,
            raw_text=raw_text,
            lift_catalog=self._lift_catalog,
            prior_profile=prior_profile,
        )

        # Render coach digest (second LLM call)
        week_num = client.week_number if client else 1
        client_name = client_id  # will be replaced by real name when Telegram passes it
        digest = render_digest(
            llm=self._llm,
            raw_text=raw_text,
            extraction=extraction,
            client_name=client_name,
            week_number=week_num,
        )

        checkin = CheckIn(
            client_id=client_id,
            raw_text=raw_text,
            extraction_json=extraction.model_dump_json(),
            digest_markdown=digest,
            active_workout_plan_id=active_plan_row.history_id if active_plan_row else None,
            needs_coach_review=extraction.needs_coach_review,
            created_at=datetime.now(timezone.utc),
        )
        session.add(checkin)
        session.commit()
        session.refresh(checkin)
        return checkin

    def apply_autoregulation(self, checkin_id: int) -> Optional[WorkoutWeek]:
        """
        Derive and apply a PlanDelta from the stored extraction.
        Returns the adjusted WorkoutWeek (not persisted — caller decides).
        """
        session = self._session
        checkin = session.get(CheckIn, checkin_id)
        if not checkin or not checkin.extraction_json:
            logger.warning("apply_autoregulation: checkin %d not found or no extraction", checkin_id)
            return None

        if not checkin.active_workout_plan_id:
            return None

        plan_row = session.get(WorkoutHistory, checkin.active_workout_plan_id)
        if not plan_row:
            return None

        current_plan = WorkoutWeek.model_validate_json(plan_row.workout_json)
        extraction = CheckInExtraction.model_validate_json(checkin.extraction_json)

        delta = derive_plan_delta(extraction, current_plan)
        if delta.notes:
            logger.info("CheckIn %d auto-reg notes:\n%s", checkin_id, "\n".join(delta.notes))

        adjusted = apply_delta(current_plan, delta)
        return adjusted

    def request_clarifications(self, checkin_id: int) -> list[str]:
        """Return the list of clarifying questions from the stored extraction (max 3)."""
        session = self._session
        checkin = session.get(CheckIn, checkin_id)
        if not checkin or not checkin.extraction_json:
            return []
        extraction = CheckInExtraction.model_validate_json(checkin.extraction_json)
        return extraction.clarifying_questions_for_client[:3]
