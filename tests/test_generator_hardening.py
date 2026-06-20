"""Phase 3 hardening: capped progression, no thin/empty days, balanced repeated days."""
import itertools

import pytest

from app.generator import WorkoutGenerator, AutoRegulator
from app.models import ClientProfile


def _gen(avatar, days, exp, equipment):
    c = ClientProfile(client_id="t", avatar=avatar, training_days=days,
                      experience_level=exp, available_equipment=equipment)
    return WorkoutGenerator().generate(c)


# ── T12: AutoRegulator weekly load jump capped at ±10% ──────────────────────

def test_autoregulator_jump_capped_up():
    nxt = AutoRegulator.calculate_next_load(last_weight=100, last_target_rpe=8,
                                            last_actual_rpe=5, next_target_rpe=8)
    assert nxt <= 110.0 + 1e-6


def test_autoregulator_jump_capped_down():
    nxt = AutoRegulator.calculate_next_load(last_weight=100, last_target_rpe=8,
                                            last_actual_rpe=10, next_target_rpe=8)
    assert nxt >= 90.0 - 1e-6


# ── T10: powerlifter full_gym splits have no thin days ──────────────────────

@pytest.mark.parametrize("days", [3, 4, 5, 6])
def test_powerlifter_full_gym_no_thin_days(days):
    wk = _gen("powerlifter", days, "advanced", ["full_gym"])
    for day in wk.days:
        assert len(day.slots) >= 3, f"powerlifter {days}d: {day.day_name} has {len(day.slots)} slots"


# ── T11: repeated day-types get balanced volume (6-day full_gym) ────────────

def test_six_day_repeated_days_balanced():
    wk = _gen("gen_pop", 6, "beginner", ["full_gym"])
    by_name = {}
    for day in wk.days:
        base = day.day_name.rstrip(" 123456").split()[0]  # "Push 2" -> "Push"
        by_name.setdefault(base, []).append(sum(s.sets for s in day.slots))
    for base, sets in by_name.items():
        assert max(sets) - min(sets) <= 3, f"{base} days unbalanced: {sets}"
    for day in wk.days:
        assert len(day.slots) >= 3, f"{day.day_name} thin: {len(day.slots)} slots"


# ── T14: no EMPTY days for any combo; full_gym/dumbbells stay >= 2 ───────────

def test_no_empty_days_across_all_combos():
    avatars = ["gen_pop", "powerbuilder", "powerlifter"]
    gym_eqs = [["full_gym"], ["dumbbells", "bench"]]
    for a, d, e, eq in itertools.product(avatars, range(3, 7),
                                         ["beginner", "advanced"], gym_eqs):
        wk = _gen(a, d, e, eq)
        for day in wk.days:
            assert len(day.slots) >= 2, f"{a}/{d}d/{e}/{eq[0]} -> {day.day_name} = {len(day.slots)} slots"


def test_bodyweight_with_bar_has_no_zero_slot_days():
    """Realistic minimal setup (bodyweight + a pull-up bar — what SP-A's intake nudges
    toward) must have no EMPTY days, including pull-focused days."""
    for a, d in itertools.product(["gen_pop", "powerbuilder"], range(3, 7)):
        wk = _gen(a, d, "beginner", ["bodyweight", "pull_up_bar"])
        for day in wk.days:
            assert len(day.slots) >= 1, f"{a}/{d}d bw+bar -> {day.day_name} EMPTY"


def test_no_bar_bodyweight_pull_gap_is_the_known_sp_a_gap():
    """A PURE no-equipment client (no bar) genuinely cannot train pulling — a pull-focused
    day may collapse. This is the SP-A equipment gap, surfaced by the coach approval DM's
    equipment_gap_note; the real fix (not generating pure-Pull days for no-bar clients) is
    split-selection, deferred. We only assert non-pull days still fill, so the plan is not
    wholesale empty."""
    from app.domain.workout.equipment import equipment_gap_note
    assert equipment_gap_note(["bodyweight"]) is not None  # coach IS warned
    wk = _gen("gen_pop", 3, "beginner", ["bodyweight"])     # full-body split: no pure-pull day
    for day in wk.days:
        assert len(day.slots) >= 1, f"{day.day_name} EMPTY even on a full-body split"


# ── Task 4: week-1 load seeding from baseline e1RMs ─────────────────────────

from app.generator import WorkoutGenerator
from app.models import ClientProfile


def _mk_client(**kw):
    base = dict(client_id="t_seed", avatar="gen_pop", training_days=3,
                experience_level="intermediate", limitations=[],
                available_equipment=["full_gym"], week_number=1)
    base.update(kw)
    return ClientProfile(**base)


def test_week1_main_compound_gets_seeded_load_when_baseline_present():
    gen = WorkoutGenerator()
    client = _mk_client(squat_e1rm=140.0, bench_e1rm=100.0, deadlift_e1rm=180.0)
    week = gen.generate(client)
    seeded = [s for d in week.days for s in d.slots
              if s.slot_type == "main_compound" and s.target_weight is not None]
    assert seeded, "at least one main compound should have a seeded target_weight"
    for s in seeded:
        assert s.target_weight % 2.5 == 0


def test_week1_no_loads_when_baselines_skipped():
    gen = WorkoutGenerator()
    client = _mk_client()  # no baselines
    week = gen.generate(client)
    # Asserts target_weight (working-set load) specifically; warm-up sets may still
    # use a 60 kg bar fallback internally — that's expected and out of scope here.
    assert all(s.target_weight is None for d in week.days for s in d.slots)


def test_seed_does_not_override_prior_week_progression():
    gen = WorkoutGenerator()
    client = _mk_client(squat_e1rm=140.0, week_number=2)
    week1 = gen.generate(_mk_client(squat_e1rm=140.0))
    for d in week1.days:
        for s in d.slots:
            if s.slot_type == "main_compound":
                s.actual_weight = 120.0
                s.actual_rpe = s.rpe
    week2 = gen.generate(client, prior_week=week1)
    progressed = [s for d in week2.days for s in d.slots
                  if s.slot_type == "main_compound" and s.target_weight is not None]
    assert progressed, "week 2 should carry autoregulated loads"

    # Prove the autoregulator (not the seed) set the load.
    # Prior actual = 120.0 kg; seed from squat_e1rm=140 would be ~110.0 kg.
    # AutoRegulator.calculate_next_load(120, rpe_err=0, next_rpe_bump) -> 122.5 kg.
    # ±10% clamp around 120 gives [108, 132]; seed value 110.0 falls below 115.
    # At least one slot must be in the autoregulated band AND above the seed floor.
    seed_value = 110.0  # floor(140 * working_pct(5, 7.0) / 2.5) * 2.5
    assert any(
        115.0 <= s.target_weight <= 132.0 and s.target_weight != seed_value
        for s in progressed
    ), (
        f"Expected an autoregulated load in [115, 132] != seed ({seed_value}); "
        f"got {[s.target_weight for s in progressed]}"
    )
