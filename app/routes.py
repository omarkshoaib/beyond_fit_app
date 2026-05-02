from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Request
from sqlmodel import Session

from app.models import (
    ClientProfile,
    CoachedWorkoutResponse,
    ProfileSnapshot,
    WorkoutWeek,
)
from app.exercise_db import get_exercise_db
from app.generator import WorkoutGenerator
from app.services.llm_service import FlashCommunicationService

router = APIRouter()


@router.get("/exercises")
def list_exercises() -> List[Dict[str, Any]]:
    return get_exercise_db()


@router.post("/generate", response_model=WorkoutWeek)
def generate_workout(client: ClientProfile, request: Request) -> WorkoutWeek:
    container = request.app.state.container
    generator = WorkoutGenerator(config=container.settings.workout_constants)
    return generator.generate(client)


@router.post("/generate_and_coach", response_model=CoachedWorkoutResponse)
def generate_and_coach(client: ClientProfile, request: Request) -> CoachedWorkoutResponse:
    container = request.app.state.container
    generator = WorkoutGenerator(config=container.settings.workout_constants)
    workout = generator.generate(client)

    # Persist a ProfileSnapshot so this plan is always reproducible
    with container.session_factory() as session:
        snapshot = ProfileSnapshot(
            client_id=client.client_id,
            snapshot_json=client.model_dump_json(),
            reason="api_generate",
            created_at=datetime.now(timezone.utc),
        )
        session.add(snapshot)
        session.commit()

    llm_svc = FlashCommunicationService(llm_client=container.llm_client)
    message = llm_svc.generate_coaching_message(client, workout)

    return CoachedWorkoutResponse(workout=workout, coaching_message=message)
