from app.domain.workout import equipment as eq
from app.exercise_db import get_exercise_db
from app.models import ClientProfile, WorkoutWeek, WorkoutDay, WorkoutSlot
from app.generator import WorkoutGenerator


def test_presets_map_to_tokens():
    assert eq.EQUIPMENT_PRESETS["commercial"] == ["full_gym"]
    assert eq.EQUIPMENT_PRESETS["minimal"] == ["bodyweight", "pull_up_bar"]
    assert eq.EQUIPMENT_PRESETS["bodyweight"] == ["bodyweight"]
    assert set(eq.EQUIPMENT_PRESETS["home"]) == {"dumbbells", "bench", "pull_up_bar"}


def test_checklist_excludes_bodyweight_and_full_gym():
    assert "bodyweight" not in eq.CHECKLIST_TOKENS
    assert "full_gym" not in eq.CHECKLIST_TOKENS
    real = {t for e in get_exercise_db() for t in e["equipment_required"]}
    assert set(eq.CHECKLIST_TOKENS) <= real


def test_floor_never_empty():
    assert eq.floor_equipment([]) == ["bodyweight"]
    assert eq.floor_equipment(None) == ["bodyweight"]
    assert eq.floor_equipment(["dumbbells"]) == ["dumbbells"]


def _week_with(ex_id: str) -> WorkoutWeek:
    slot = WorkoutSlot(slot_order=0, slot_type="main_compound", exercise_id=ex_id,
                       exercise_name=ex_id, sets=3, reps="5", rpe=7)
    return WorkoutWeek(week_number=1, days=[WorkoutDay(day_name="A", slots=[slot], total_fatigue=3)])

def test_validate_flags_absent_equipment():
    week = _week_with("bb_back_squat_highbar")
    violations = eq.validate_equipment(week, ["dumbbells"])
    assert len(violations) == 1
    assert violations[0].exercise_id == "bb_back_squat_highbar"
    assert "barbell" in violations[0].missing

def test_validate_passes_full_gym_and_valid():
    week = _week_with("bb_back_squat_highbar")
    assert eq.validate_equipment(week, ["full_gym"]) == []
    assert eq.validate_equipment(_week_with("bw_air_squat"), ["bodyweight"]) == []

def test_validate_flags_unknown_exercise():
    violations = eq.validate_equipment(_week_with("not_a_real_id"), ["full_gym"])
    assert len(violations) == 1 and violations[0].missing == ["<unknown exercise>"]

def test_alternatives_are_same_muscle_and_equipment_valid():
    alts = eq.equipment_alternatives("bb_back_squat_highbar", ["bodyweight"])
    assert any(a["exercise_id"] == "bw_air_squat" for a in alts)
    for a in alts:
        assert all(t in {"bodyweight"} for t in a["equipment_required"])

def test_reachable_patterns_no_bar_has_no_pull():
    reach = eq.reachable_patterns(["bodyweight"])
    assert "squat" in reach
    assert "horizontal_pull" not in reach and "vertical_pull" not in reach
    reach_bar = eq.reachable_patterns(["bodyweight", "pull_up_bar"])
    assert "horizontal_pull" in reach_bar or "vertical_pull" in reach_bar

def test_generator_treats_empty_equipment_as_full_gym():
    client = ClientProfile(client_id="cl_empty", avatar="gen_pop", training_days=3,
                           experience_level="beginner", limitations=[], available_equipment=[])
    week = WorkoutGenerator().generate(client)
    assert sum(len(d.slots) for d in week.days) > 0
