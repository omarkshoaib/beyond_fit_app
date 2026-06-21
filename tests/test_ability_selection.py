"""SP-B1 C5 headline guarantee: no exercise above the client's family ability."""
from app.generator import WorkoutGenerator
from app.exercise_db import get_exercise_db
from app.models import ClientProfile
from app.domain.workout.ability import LADDERS, client_ability

_DB = {e["exercise_id"]: e for e in get_exercise_db()}
_FAM_OF = {ex_id: fam for fam, rungs in LADDERS.items() for ex_id in rungs}

def _gen(**kw):
    base = dict(client_id="cl_t", avatar="gen_pop", training_days=4, limitations=[],
                available_equipment=["full_gym"])
    base.update(kw)
    return WorkoutGenerator().generate(ClientProfile(**base))

def test_beginner_never_gets_above_ability_in_anchor_families():
    client = ClientProfile(client_id="cl_b", avatar="gen_pop", training_days=4, limitations=[],
                           available_equipment=["full_gym"], experience_level="beginner",
                           exercise_ability={f: 2 for f in LADDERS})
    week = WorkoutGenerator().generate(client)
    for d in week.days:
        for s in d.slots:
            e = _DB.get(s.exercise_id)
            if e and e["movement_pattern"] in LADDERS:
                assert e["difficulty_tier"] <= 2, f"{s.exercise_id} t{e['difficulty_tier']} > 2"

def test_cant_pullup_client_gets_regression_not_strict_pullup():
    client = ClientProfile(client_id="cl_p", avatar="gen_pop", training_days=4, limitations=[],
                           available_equipment=["full_gym"], experience_level="beginner",
                           exercise_ability={f: 1 for f in LADDERS})
    week = WorkoutGenerator().generate(client)
    ids = [s.exercise_id for d in week.days for s in d.slots]
    assert "bw_pull_up_pronated" not in ids and "bw_weighted_pull_up" not in ids

def test_advanced_client_still_gets_barbell_mains():
    week = _gen(experience_level="advanced", exercise_ability={f: 4 for f in LADDERS})
    ids = {s.exercise_id for d in week.days for s in d.slots}
    # at least one tier-4 barbell main appears
    assert ids & {"bb_back_squat_highbar", "bb_bench_press", "bb_deadlift_conventional", "bb_overhead_press"}

def test_no_day_emptied_for_beginner():
    week = _gen(experience_level="beginner", exercise_ability={f: 2 for f in LADDERS})
    for d in week.days:
        assert len(d.slots) >= 1
