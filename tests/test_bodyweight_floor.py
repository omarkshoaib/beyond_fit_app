"""A bodyweight-only client must get a complete, non-collapsed plan (SP-A C4)."""
from app.exercise_db import get_exercise_db
from app.generator import WorkoutGenerator
from app.models import ClientProfile

NEW_IDS = {
    "bw_air_squat", "bw_reverse_lunge", "bw_single_leg_rdl",
    "bw_knee_push_up", "bw_inverted_row_bar",
}

def test_new_bodyweight_exercises_exist_and_validate():
    db = {e["exercise_id"]: e for e in get_exercise_db()}
    for ex_id in NEW_IDS:
        assert ex_id in db, f"{ex_id} missing from exercise DB"
    air = db["bw_air_squat"]
    assert air["movement_pattern"] == "squat"
    assert air["equipment_required"] == ["bodyweight"]
    assert db["bw_inverted_row_bar"]["equipment_required"] == ["pull_up_bar", "bodyweight"]

def test_bodyweight_with_bar_covers_squat_and_pull():
    client = ClientProfile(
        client_id="cl_bw_bar", avatar="gen_pop", training_days=4,
        experience_level="beginner", limitations=[],
        available_equipment=["bodyweight", "pull_up_bar"],
    )
    week = WorkoutGenerator().generate(client)
    patterns = {
        s.exercise_id: e["movement_pattern"]
        for e in get_exercise_db()
        for d in week.days for s in d.slots
        if s.exercise_id == e["exercise_id"]
    }
    present = set(patterns.values())
    assert "squat" in present, "no squat pattern for a bodyweight+bar client"
    assert "horizontal_pull" in present or "vertical_pull" in present, "no pulling"

def test_bodyweight_only_has_no_empty_day():
    client = ClientProfile(
        client_id="cl_bw_only", avatar="gen_pop", training_days=4,
        experience_level="beginner", limitations=[],
        available_equipment=["bodyweight"],
    )
    week = WorkoutGenerator().generate(client)
    for d in week.days:
        assert len(d.slots) >= 1, f"day {d.day_name} collapsed to zero slots"
