from app.domain.workout import equipment as eq


def test_equipment_gap_note_for_no_bar_bodyweight():
    note = eq.equipment_gap_note(["bodyweight"])
    assert note and "pull" in note.lower()


def test_no_gap_note_with_bar():
    assert eq.equipment_gap_note(["bodyweight", "pull_up_bar"]) is None
    assert eq.equipment_gap_note(["full_gym"]) is None


import pytest
from unittest.mock import AsyncMock
from sqlmodel import Session
from app.models import ClientProfile, WorkoutWeek, WorkoutDay, WorkoutSlot
from tests.conftest import make_text_update, make_context


@pytest.mark.asyncio
async def test_override_to_unavailable_equipment_is_rejected(monkeypatch):
    from app import bot
    monkeypatch.setattr(bot.auth_roles, "is_coach", lambda uid: True)
    monkeypatch.setattr(bot.auth_roles, "is_super_admin", lambda uid: False)
    cid = "cl_guard_override"
    with Session(bot.engine) as s:
        s.merge(ClientProfile(client_id=cid, avatar="gen_pop", training_days=3,
                              experience_level="beginner", limitations=[],
                              available_equipment=["bodyweight"], assigned_coach_id=999))
        s.commit()
    mock_bot = AsyncMock()
    ctx = make_context(mock_bot)
    ctx.args = [cid, "bw_air_squat", "bb_back_squat_highbar"]  # target needs barbell+rack
    upd = make_text_update(mock_bot, user_id=999, text="/override")
    await bot.handle_override(upd, ctx)
    with Session(bot.engine) as s:
        p = s.get(ClientProfile, cid)
    assert not (p.coach_overrides or {}).get("bw_air_squat")  # NOT stored
    sent = " ".join(str(c.kwargs.get("text", "")) + str(c.args)
                    for c in mock_bot.send_message.call_args_list)
    assert "barbell" in sent or "squat_rack" in sent


def test_validate_then_persist_blocks_bad_week():
    from app.domain.workout import equipment as eq
    slot = WorkoutSlot(slot_order=0, slot_type="main_compound",
                       exercise_id="bb_back_squat_highbar", exercise_name="Squat",
                       sets=3, reps="5", rpe=7)
    week = WorkoutWeek(week_number=1, days=[WorkoutDay(day_name="A", slots=[slot], total_fatigue=5)])
    violations = eq.validate_equipment(week, ["bodyweight"])
    assert violations and violations[0].exercise_id == "bb_back_squat_highbar"
