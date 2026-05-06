from app.bot import _select_checkin_slots
from app.models import WorkoutDay, WorkoutSlot, WorkoutWeek


def _mk(slot_type: str, name: str) -> WorkoutSlot:
    return WorkoutSlot(
        slot_order=1, slot_type=slot_type,
        exercise_id=name, exercise_name=name,
        sets=3, reps="5", rpe=8,
    )


def test_only_main_compound_slots_are_collected():
    week = WorkoutWeek(
        week_number=1,
        days=[WorkoutDay(
            day_name="Push",
            slots=[
                _mk("main_compound", "Bench"),
                _mk("secondary_compound", "OHP"),
                _mk("isolation", "Lateral Raise"),
            ],
            total_fatigue=10,
        )],
    )
    chosen = _select_checkin_slots(week)
    assert [s.exercise_name for _, s in chosen] == ["Bench"]
