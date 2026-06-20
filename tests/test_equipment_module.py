from app.domain.workout import equipment as eq


def test_presets_map_to_tokens():
    assert eq.EQUIPMENT_PRESETS["commercial"] == ["full_gym"]
    assert eq.EQUIPMENT_PRESETS["minimal"] == ["bodyweight", "pull_up_bar"]
    assert eq.EQUIPMENT_PRESETS["bodyweight"] == ["bodyweight"]
    assert set(eq.EQUIPMENT_PRESETS["home"]) == {"dumbbells", "bench", "pull_up_bar"}


def test_checklist_excludes_bodyweight_and_full_gym():
    assert "bodyweight" not in eq.CHECKLIST_TOKENS
    assert "full_gym" not in eq.CHECKLIST_TOKENS
    from app.exercise_db import get_exercise_db
    real = {t for e in get_exercise_db() for t in e["equipment_required"]}
    assert set(eq.CHECKLIST_TOKENS) <= real


def test_floor_never_empty():
    assert eq.floor_equipment([]) == ["bodyweight"]
    assert eq.floor_equipment(None) == ["bodyweight"]
    assert eq.floor_equipment(["dumbbells"]) == ["dumbbells"]
