import pytest
from app.bot import _checkin_slot_dicts
from app.models import WorkoutWeek, WorkoutDay, WorkoutSlot

def _week():
    loaded = WorkoutSlot(slot_order=0, slot_type="main_compound", exercise_id="bb_bench_press",
                         exercise_name="Barbell Bench Press", sets=3, reps="5", rpe=8, target_weight=100.0)
    bw = WorkoutSlot(slot_order=1, slot_type="main_compound", exercise_id="bw_air_squat",
                     exercise_name="Bodyweight Air Squat", sets=3, reps="12", rpe=7, target_weight=None)
    return WorkoutWeek(week_number=1, days=[WorkoutDay(day_name="A", slots=[loaded, bw], total_fatigue=7)])

def test_slot_dicts_flag_bodyweight():
    dicts = _checkin_slot_dicts([("A", s) for s in _week().days[0].slots])
    assert dicts[0]["bodyweight"] is False     # loaded bench
    assert dicts[1]["bodyweight"] is True       # air squat (target_weight None)
