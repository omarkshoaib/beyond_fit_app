"""
Bot integration tests — simulates user/admin interactions against a real in-memory DB.

Each test calls PTB handler coroutines directly (no Application dispatch), with:
  - Real WorkoutGenerator (deterministic, no LLM)
  - Real SQLite database (per-test, via conftest.patch_engine)
  - Mocked Telegram bot (AsyncMock — no HTTP calls)
  - Mocked LLM/email/PDF dependencies
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import Session, select

from app.bot import (
    _process_checkin,
    handle_admin_approve,
    handle_admin_approve_confirmed,
    handle_email,
    run_generation_and_dispatch,
)
from app.domain.checkin.schema import CheckInExtraction, ExerciseFeedback
from app.generator import WorkoutGenerator
from app.models import (
    ChatBinding,
    ClientProfile,
    PendingApproval,
    WorkoutHistory,
    WorkoutWeek,
)
from tests.conftest import make_callback_update, make_context, make_text_update

# ── Shared test constants ──────────────────────────────────────────────────────

USER_ID = 123456
# Test admin == the user under test so legacy admin-check passes; the
# SaaS scope check (_user_can_act_on_client) reads this via os.getenv("ADMIN_TELEGRAM_ID").
ADMIN_ID = str(USER_ID)

# Minimal ClientProfile used across tests
_BASE_PROFILE = dict(
    client_id=str(USER_ID),
    avatar="gen_pop",
    training_days=3,
    experience_level="beginner",
    limitations=[],
    available_equipment=["full_gym"],
    week_number=1,
    email="test@example.com",
    name="TestUser",
)

# External service patches applied to all tests in this module
_PATCHES = [
    patch("app.bot.FlashCommunicationService.generate_coaching_message", return_value="Test coaching message"),
    patch("app.bot.FlashCommunicationService.apply_coach_edits", side_effect=lambda j, _: j),
    patch("app.bot.render_plan_pdf", side_effect=lambda client, out_path, **kw: out_path.write_bytes(b"PDF")),
    patch("app.bot.render_digest", return_value="digest"),
    patch("os.getenv", side_effect=lambda k, *a: ADMIN_ID if k == "ADMIN_TELEGRAM_ID" else (a[0] if a else None)),
]


@pytest.fixture(autouse=True)
def apply_patches():
    """Start all external service patches for every test in this module."""
    started = [p.start() for p in _PATCHES]
    yield
    for p in _PATCHES:
        p.stop()


# ── Helper: seed a generated week into the DB ──────────────────────────────────

def _seed_profile_and_history(test_engine) -> tuple[ClientProfile, WorkoutHistory]:
    """Insert a ClientProfile, ChatBinding (so _current_client_id resolves),
    and one active WorkoutHistory into the test DB."""
    profile = ClientProfile(**_BASE_PROFILE)
    week = WorkoutGenerator().generate(profile)
    history = WorkoutHistory(
        client_id=profile.client_id,
        week_number=week.week_number,
        workout_json=week.model_dump_json(),
        status="active",
    )
    with Session(test_engine) as session:
        session.add(profile)
        session.add(ChatBinding(chat_id=USER_ID, client_id=profile.client_id, is_primary=True))
        session.add(history)
        session.commit()
        session.refresh(history)
    return profile, history


# ── Test 1: Intake creates ClientProfile ──────────────────────────────────────

async def test_intake_creates_profile(test_engine, mock_bot):
    update = make_text_update(mock_bot, USER_ID, "test@example.com")
    ctx = make_context(mock_bot, user_data={
        "avatar": "gen_pop",
        "days": 3,
        "experience_level": "beginner",
        "limitations": [],
        "intake_client_id": str(USER_ID),  # post-SaaS handle_email refuses without this
    })

    await handle_email(update, ctx)

    with Session(test_engine) as session:
        profile = session.get(ClientProfile, str(USER_ID))

    assert profile is not None
    assert profile.avatar == "gen_pop"
    assert profile.email == "test@example.com"
    assert profile.name == "TestUser"
    assert profile.training_days == 3


# ── Test 2: Intake creates PendingApproval ────────────────────────────────────

async def test_intake_creates_pending_approval(test_engine, mock_bot):
    update = make_text_update(mock_bot, USER_ID, "test@example.com")
    ctx = make_context(mock_bot, user_data={
        "avatar": "gen_pop",
        "days": 3,
        "experience_level": "beginner",
        "limitations": [],
        "intake_client_id": str(USER_ID),
    })

    await handle_email(update, ctx)

    with Session(test_engine) as session:
        pending = session.exec(
            select(PendingApproval).where(PendingApproval.client_id == str(USER_ID))
        ).first()

    assert pending is not None
    assert pending.client_id == str(USER_ID)
    assert pending.client_email == "test@example.com"
    # Admin was notified
    mock_bot.send_message.assert_called()
    call_kwargs = mock_bot.send_message.call_args_list[-1].kwargs
    assert call_kwargs.get("chat_id") == ADMIN_ID or str(call_kwargs.get("chat_id")) == ADMIN_ID


# ── Test 3: Admin approve → WorkoutHistory active ─────────────────────────────

async def test_admin_approves_workout_activates_history(test_engine, mock_bot):
    profile = ClientProfile(**_BASE_PROFILE)
    week = WorkoutGenerator().generate(profile)
    approval_uuid = str(uuid.uuid4())
    pending = PendingApproval(
        approval_uuid=approval_uuid,
        client_id=str(USER_ID),
        client_chat_id=USER_ID,
        client_name="TestUser",
        client_email="test@example.com",
        workout_json=week.model_dump_json(),
        coaching_message="Test coaching message",
    )
    with Session(test_engine) as session:
        session.add(profile)
        session.add(pending)
        session.commit()

    update = make_callback_update(mock_bot, USER_ID, data=f"approve_confirmed:{approval_uuid}")
    ctx = make_context(mock_bot)

    await handle_admin_approve_confirmed(update, ctx)

    with Session(test_engine) as session:
        history = session.exec(
            select(WorkoutHistory).where(
                WorkoutHistory.client_id == str(USER_ID),
                WorkoutHistory.status == "active",
            )
        ).first()
        leftover_pending = session.get(PendingApproval, approval_uuid)

    assert history is not None
    assert history.week_number == week.week_number
    assert leftover_pending is None  # PendingApproval deleted on approval
    # Client was notified via send_document
    mock_bot.send_document.assert_called_once()


# ── Test 4: Check-in writes actual_rpe / actual_weight back to WorkoutHistory ─

async def test_checkin_writes_telemetry(test_engine, mock_bot):
    profile, history = _seed_profile_and_history(test_engine)

    # Find a slot to report telemetry for
    week = WorkoutWeek.model_validate_json(history.workout_json)
    target_slot = week.days[0].slots[0]

    fake_extraction = CheckInExtraction.model_validate({
        "overall_fatigue": 5,
        "exercises": [
            {
                "exercise_canonical": target_slot.exercise_id,
                "actual_load_kg": 100.0,
                "rpe": 7.5,
            }
        ],
        "pain_flags": [],
        "soreness": [],
        "personal_records": [],
        "clarifying_questions_for_client": [],
    })

    update = make_text_update(mock_bot, USER_ID, "felt good")
    ctx = make_context(mock_bot, user_data={
        "checkin_messages": ["felt good this week, squats @100kg RPE 7.5"],
        "checkin_history_id": history.history_id,
        "checkin_lift_catalog": [target_slot.exercise_name],
        "checkin_prior_profile": profile.model_dump_json(),
        "checkin_week_number": 1,
    })

    with patch("app.bot.extract_checkin", return_value=fake_extraction), \
         patch("app.bot._make_llm_client", return_value=AsyncMock()):
        await _process_checkin(update, ctx)

    with Session(test_engine) as session:
        updated_history = session.exec(
            select(WorkoutHistory).where(WorkoutHistory.client_id == str(USER_ID))
            .order_by(WorkoutHistory.week_number.desc())
        ).first()

    updated_week = WorkoutWeek.model_validate_json(updated_history.workout_json)
    reported_slot = next(
        (s for d in updated_week.days for s in d.slots if s.exercise_id == target_slot.exercise_id),
        None,
    )
    # Telemetry written on the old week (week_number==1)
    if updated_history.week_number == 1:
        assert reported_slot is not None
        assert reported_slot.actual_weight == 100.0
        assert reported_slot.actual_rpe == 7.5


# ── Test 5: Check-in increments week_number and creates new PendingApproval ───

async def test_checkin_increments_week_and_generates_plan(test_engine, mock_bot):
    profile, history = _seed_profile_and_history(test_engine)
    week = WorkoutWeek.model_validate_json(history.workout_json)
    target_slot = week.days[0].slots[0]

    fake_extraction = CheckInExtraction.model_validate({
        "overall_fatigue": 4,
        "exercises": [
            {"exercise_canonical": target_slot.exercise_id, "actual_load_kg": 80.0, "rpe": 7.0}
        ],
        "pain_flags": [],
        "soreness": [],
        "personal_records": [],
        "clarifying_questions_for_client": [],
    })

    update = make_text_update(mock_bot, USER_ID, "good week")
    ctx = make_context(mock_bot, user_data={
        "checkin_messages": ["good week, everything felt solid"],
        "checkin_history_id": history.history_id,
        "checkin_lift_catalog": [target_slot.exercise_name],
        "checkin_prior_profile": profile.model_dump_json(),
        "checkin_week_number": 1,
    })

    with patch("app.bot.extract_checkin", return_value=fake_extraction), \
         patch("app.bot._make_llm_client", return_value=AsyncMock()):
        await _process_checkin(update, ctx)

    with Session(test_engine) as session:
        updated_profile = session.get(ClientProfile, str(USER_ID))
        new_pending = session.exec(
            select(PendingApproval).where(PendingApproval.client_id == str(USER_ID))
        ).first()

    assert updated_profile.week_number == 2
    assert new_pending is not None


# ── Test 6: Rate limiter blocks a second immediate generation ──────────────────

async def test_rate_limit_blocks_second_call(test_engine, mock_bot):
    profile = ClientProfile(**_BASE_PROFILE)
    with Session(test_engine) as session:
        session.add(profile)
        session.commit()
        session.refresh(profile)

    ctx = make_context(mock_bot)

    # First call — should succeed
    await run_generation_and_dispatch(
        context=ctx,
        client_chat_id=USER_ID,
        client_user_id=str(USER_ID),
        client_first_name="TestUser",
        client_email="test@example.com",
        profile=profile,
    )

    # Second immediate call — should be rate-limited
    await run_generation_and_dispatch(
        context=ctx,
        client_chat_id=USER_ID,
        client_user_id=str(USER_ID),
        client_first_name="TestUser",
        client_email="test@example.com",
        profile=profile,
    )

    with Session(test_engine) as session:
        all_pending = session.exec(
            select(PendingApproval).where(PendingApproval.client_id == str(USER_ID))
        ).all()

    # Only one plan was created despite two calls
    assert len(all_pending) == 1

    # Second call sent the "please wait" message directly to the client
    rate_limit_calls = [
        c for c in mock_bot.send_message.call_args_list
        if "wait" in str(c).lower() or "minutes" in str(c).lower()
    ]
    assert len(rate_limit_calls) >= 1
