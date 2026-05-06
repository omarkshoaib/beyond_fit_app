from app.bot import _format_plan_summary
from app.models import WorkoutDay, WorkoutSlot, WorkoutWeek


def _slot(name: str, sets: int, reps: str, rpe: int) -> WorkoutSlot:
    return WorkoutSlot(
        slot_order=1, slot_type="main_compound",
        exercise_id=name.lower().replace(" ", "_"),
        exercise_name=name, sets=sets, reps=reps, rpe=rpe,
    )


def test_summary_shows_week_and_day_count():
    week = WorkoutWeek(
        week_number=3,
        days=[
            WorkoutDay(day_name="Push", slots=[_slot("Bench Press", 4, "5", 8)],
                       total_fatigue=4),
            WorkoutDay(day_name="Pull", slots=[_slot("Pendlay Row", 4, "5", 8)],
                       total_fatigue=4),
        ],
    )
    out = _format_plan_summary(week)
    assert "Week 3" in out
    assert "Push" in out and "Pull" in out
    assert "Bench Press" in out
    assert "4×5 @ RPE 8" in out


def test_summary_handles_empty_week():
    week = WorkoutWeek(week_number=1, days=[])
    out = _format_plan_summary(week)
    assert "Week 1" in out
