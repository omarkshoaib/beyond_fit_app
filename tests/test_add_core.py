"""Coach 'add core at verification': deterministic helpers + handler authz."""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlmodel import Session

from app.bot import (
    _core_choices_for_client, _add_core_to_day,
    handle_add_core_exercise,
)
from app.generator import WorkoutGenerator
from app.models import ClientProfile, CoachProfile, PendingApproval, WorkoutWeek


def _client(equipment):
    return ClientProfile(client_id="t", avatar="gen_pop", training_days=3,
                         experience_level="beginner", available_equipment=equipment)


SUPER_ADMIN_ID = 4242
COACH_ID = 5555
RANDOM_ID = 99999


def _patch_roles(monkeypatch, engine):
    import app.auth.roles as roles_mod
    monkeypatch.setattr(roles_mod, "engine", engine)
    fake = type("S", (), {"super_admin_telegram_user_id": SUPER_ADMIN_ID, "admin_chat_id": None})()
    monkeypatch.setattr(roles_mod, "get_settings", lambda: fake)
    roles_mod.invalidate_coach_cache()


def _seed(engine) -> str:
    aid = str(uuid.uuid4())
    week = WorkoutGenerator().generate(ClientProfile(
        client_id="cl_a", avatar="gen_pop", training_days=3,
        experience_level="beginner", available_equipment=["full_gym"]))
    with Session(engine) as s:
        s.add(CoachProfile(telegram_user_id=COACH_ID, name="Coach", email="c@x", mobile="1",
                           specialty="x", years_experience=3, certifications="-", status="approved"))
        s.add(ClientProfile(client_id="cl_a", avatar="gen_pop", training_days=3,
                            experience_level="beginner", available_equipment=["full_gym"],
                            assigned_coach_id=COACH_ID, name="Alice"))
        s.add(PendingApproval(approval_uuid=aid, client_id="cl_a", client_chat_id=11,
                              client_name="Alice", client_email="a@x.com",
                              workout_json=week.model_dump_json(), coaching_message="m"))
        s.commit()
    return aid


def _cb(user_id, data):
    q = MagicMock()
    q.answer = AsyncMock()
    q.edit_message_text = AsyncMock()
    q.edit_message_reply_markup = AsyncMock()
    q.data = data
    upd = type("U", (), {"callback_query": q, "effective_user": type("UU", (), {"id": user_id})()})()
    return upd, q


@pytest.mark.asyncio
async def test_authorized_coach_adds_core_slot(monkeypatch, test_engine):
    _patch_roles(monkeypatch, test_engine)
    aid = _seed(test_engine)
    with Session(test_engine) as s:
        before = len(WorkoutWeek.model_validate_json(
            s.get(PendingApproval, aid).workout_json).days[0].slots)
    upd, q = _cb(COACH_ID, f"addcore_x:{aid}:0:0")
    await handle_add_core_exercise(upd, MagicMock())
    with Session(test_engine) as s:
        after_week = WorkoutWeek.model_validate_json(s.get(PendingApproval, aid).workout_json)
    assert len(after_week.days[0].slots) == before + 1
    assert after_week.days[0].slots[-1].slot_type == "isolation"


@pytest.mark.asyncio
async def test_random_user_cannot_add_core(monkeypatch, test_engine):
    _patch_roles(monkeypatch, test_engine)
    aid = _seed(test_engine)
    with Session(test_engine) as s:
        before = len(WorkoutWeek.model_validate_json(
            s.get(PendingApproval, aid).workout_json).days[0].slots)
    upd, q = _cb(RANDOM_ID, f"addcore_x:{aid}:0:0")
    await handle_add_core_exercise(upd, MagicMock())
    with Session(test_engine) as s:
        after = len(WorkoutWeek.model_validate_json(
            s.get(PendingApproval, aid).workout_json).days[0].slots)
    assert after == before, "unauthorized user must not mutate the plan"


def test_core_choices_full_gym_returns_many_sorted():
    choices = _core_choices_for_client(_client(["full_gym"]))
    assert len(choices) >= 8
    ids = [c["exercise_id"] for c in choices]
    assert ids == sorted(ids), "choices must be deterministically sorted"
    assert all(c["primary_muscle"] == "core" for c in choices)


def test_core_choices_bodyweight_only_excludes_cable():
    choices = _core_choices_for_client(_client(["bodyweight"]))
    assert choices, "bodyweight client must still get core options"
    for c in choices:
        assert all(eq in ("bodyweight",) for eq in c["equipment_required"]) or \
            "bodyweight" in c["equipment_required"], f"{c['exercise_id']} not bodyweight-doable"
    assert not any("cable_machine" in c["equipment_required"] for c in choices)


def test_core_choices_falls_back_to_bodyweight_when_equipment_sparse():
    # dumbbells-only: no core exercise needs exactly dumbbells -> fallback to bodyweight core
    choices = _core_choices_for_client(_client(["dumbbells"]))
    assert choices, "must fall back to bodyweight core, not empty"


def test_add_core_to_day_appends_slot():
    wk = WorkoutGenerator().generate(_client(["full_gym"]))
    day_idx = 0
    before = len(wk.days[day_idx].slots)
    before_fatigue = wk.days[day_idx].total_fatigue
    core = _core_choices_for_client(_client(["full_gym"]))[0]
    _add_core_to_day(wk, day_idx, core)
    day = wk.days[day_idx]
    assert len(day.slots) == before + 1
    assert day.slots[-1].exercise_id == core["exercise_id"]
    assert day.slots[-1].slot_type == "isolation"
    assert day.total_fatigue == before_fatigue + core["fatigue_cost"]
    assert day.slots[-1].slot_order == max(s.slot_order for s in day.slots[:-1]) + 1
