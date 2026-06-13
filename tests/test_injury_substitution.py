import pytest
from app.generator import WorkoutGenerator
from app.models import ClientProfile

_BANNED = {
    "lower_back_pain": {"hinge"},
    "knee_pain": {"squat", "lunge"},
    "shoulder_impingement": {"vertical_push", "horizontal_pull"},
}


def _client(limitations):
    return ClientProfile(client_id="t_inj", avatar="gen_pop", training_days=6,
                         experience_level="intermediate", limitations=limitations,
                         available_equipment=["full_gym"], week_number=1)


def _patterns_in_week(week, gen):
    ex_map = {e.exercise_id: e for e in gen.exercise_db}
    return {ex_map[s.exercise_id].movement_pattern
            for d in week.days for s in d.slots if s.exercise_id in ex_map}


@pytest.mark.parametrize("limitation", list(_BANNED))
def test_banned_patterns_absent_from_week(limitation):
    gen = WorkoutGenerator()
    week = gen.generate(_client([limitation]))
    used = _patterns_in_week(week, gen)
    assert not (used & _BANNED[limitation]), \
        f"{limitation}: found banned patterns {used & _BANNED[limitation]}"


def test_lower_back_pain_excludes_lower_back_secondary():
    gen = WorkoutGenerator()
    week = gen.generate(_client(["lower_back_pain"]))
    ex_map = {e.exercise_id: e for e in gen.exercise_db}
    for d in week.days:
        for s in d.slots:
            ex = ex_map.get(s.exercise_id)
            if ex:
                assert "lower_back" not in ex.secondary_muscles


def test_days_not_collapsed_by_injury():
    gen = WorkoutGenerator()
    week = gen.generate(_client(["knee_pain"]))
    for d in week.days:
        assert len(d.slots) >= 1, f"{d.day_name} collapsed to empty under knee_pain"


def test_wrist_pain_adds_cue_but_does_not_exclude():
    gen = WorkoutGenerator()
    base = gen.generate(_client([]))
    wrist = gen.generate(_client(["wrist_pain"]))
    base_n = sum(len(d.slots) for d in base.days)
    wrist_n = sum(len(d.slots) for d in wrist.days)
    assert wrist_n == base_n
    cues = [c for d in wrist.days for s in d.slots for c in s.coaching_cues]
    assert any("Wrist" in c for c in cues)
