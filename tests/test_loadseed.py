import math
import pytest
from app.models import ClientProfile
from app.domain.workout import loadseed


def _client(**e1rm):
    return ClientProfile(client_id="t_load", **e1rm)


def test_brzycki_single_returns_lifted_weight():
    assert loadseed.brzycki_e1rm(100.0, 1) == pytest.approx(100.0)


def test_brzycki_five_reps():
    assert loadseed.brzycki_e1rm(100.0, 5) == pytest.approx(112.5)


def test_brzycki_clamps_reps_above_ten():
    assert loadseed.brzycki_e1rm(100.0, 15) == loadseed.brzycki_e1rm(100.0, 10)


def test_working_pct_grid_spotchecks():
    assert loadseed.working_pct(5, 8) == pytest.approx(0.811)
    assert loadseed.working_pct(1, 10) == pytest.approx(1.000)
    assert loadseed.working_pct(10, 6) == pytest.approx(0.656)


def test_working_pct_clamps_out_of_range():
    assert loadseed.working_pct(0, 8) == loadseed.working_pct(1, 8)
    assert loadseed.working_pct(99, 5) == loadseed.working_pct(10, 6)


def test_pattern_e1rm_direct_baselines():
    c = _client(squat_e1rm=140.0, bench_e1rm=100.0, deadlift_e1rm=180.0)
    assert loadseed.pattern_e1rm(c, "squat") == pytest.approx(140.0)
    assert loadseed.pattern_e1rm(c, "hinge") == pytest.approx(180.0)
    assert loadseed.pattern_e1rm(c, "horizontal_push") == pytest.approx(100.0)


def test_pattern_e1rm_ratio_derivations():
    c = _client(bench_e1rm=100.0)
    assert loadseed.pattern_e1rm(c, "horizontal_pull") == pytest.approx(70.0)
    assert loadseed.pattern_e1rm(c, "vertical_push") == pytest.approx(60.0)


def test_pattern_e1rm_guidance_patterns_return_none():
    c = _client(squat_e1rm=140.0, bench_e1rm=100.0, deadlift_e1rm=180.0)
    assert loadseed.pattern_e1rm(c, "vertical_pull") is None
    assert loadseed.pattern_e1rm(c, "lunge") is None
    assert loadseed.pattern_e1rm(c, "isolation") is None


def test_pattern_e1rm_missing_baseline_returns_none():
    c = _client(bench_e1rm=100.0)
    assert loadseed.pattern_e1rm(c, "squat") is None


def test_seed_working_load_rounds_down_to_2_5kg_and_never_exceeds_e1rm():
    c = _client(squat_e1rm=140.0)
    load = loadseed.seed_working_load(c, "squat", "5-8", 7.0)
    assert load == pytest.approx(110.0)
    assert load % 2.5 == 0
    assert load <= 140.0


def test_seed_working_load_none_when_unseedable():
    c = _client(bench_e1rm=100.0)
    assert loadseed.seed_working_load(c, "vertical_pull", "5-8", 7.0) is None
    assert loadseed.seed_working_load(c, "squat", "5-8", 7.0) is None
