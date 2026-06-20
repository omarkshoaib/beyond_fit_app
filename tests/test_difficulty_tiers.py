# tests/test_difficulty_tiers.py
"""Every exercise carries a safe difficulty_tier (SP-B1 C1)."""
from app.exercise_db import get_exercise_db

ANCHORS = {  # from spec Appendix A — fixed tiers
    "bw_air_squat": 2, "db_goblet_squat": 2, "smith_back_squat": 3,
    "bb_back_squat_highbar": 4, "bb_back_squat_lowbar": 5,
    "bw_glute_bridge": 1, "cable_pull_through": 2, "db_romanian_deadlift": 3,
    "bb_romanian_deadlift": 4, "bb_deadlift_conventional": 4, "bb_deficit_deadlift": 5,
    "bw_knee_push_up": 1, "machine_chest_press": 2, "bw_push_up": 3,
    "db_flat_bench_press": 3, "bb_bench_press": 4, "bw_weighted_dip": 5,
    "bw_incline_pike_push_up": 2, "smith_shoulder_press": 2, "bw_pike_push_up": 3,
    "db_seated_shoulder_press": 3, "bb_overhead_press": 4, "bb_push_press": 5,
    "bw_inverted_row_bar": 2, "db_single_arm_row": 3, "db_chest_supported_row": 3,
    "bb_bent_over_row_pronated": 4, "bb_pendlay_row": 4, "bw_inverted_row_feet_elevated": 5,
    "machine_assisted_pull_up": 1, "cable_wide_grip_lat_pulldown": 2,
    "cable_neutral_grip_lat_pulldown": 3, "bw_pull_up_pronated": 4, "bw_weighted_pull_up": 5,
}
ISOLATION_OVERRIDES = {"bw_nordic_curl": 5, "bw_sissy_squat": 4, "bw_l_sit": 4, "bw_toes_to_bar": 3}

def test_every_exercise_is_tiered_1_to_5():
    for e in get_exercise_db():
        assert e["difficulty_tier"] in (1, 2, 3, 4, 5), f"{e['exercise_id']} tier={e.get('difficulty_tier')}"

def test_anchor_tiers_match_appendix_a():
    db = {e["exercise_id"]: e for e in get_exercise_db()}
    for ex_id, tier in ANCHORS.items():
        assert ex_id in db, f"{ex_id} missing"
        assert db[ex_id]["difficulty_tier"] == tier, f"{ex_id} expected {tier}, got {db[ex_id]['difficulty_tier']}"

def test_every_barbell_compound_is_tier_4_or_5_safety():
    # SAFETY BACKSTOP: a beginner must never be handed a heavy barbell lift.
    for e in get_exercise_db():
        if "barbell" in e["equipment_required"] and e["movement_pattern"] != "isolation":
            assert e["difficulty_tier"] >= 4, f"{e['exercise_id']} barbell but tier {e['difficulty_tier']}"

def test_no_free_bar_compound_reaches_a_beginner():
    # Beginner ceiling is tier 2. NO loaded free-bar (barbell/trap_bar/ez_bar) compound may
    # sit at tier <=2 — trap_bar/ez_bar are not the literal "barbell" token and slipped the backstop.
    for e in get_exercise_db():
        if e["movement_pattern"] == "isolation":
            continue
        if any(b in e["equipment_required"] for b in ("barbell", "trap_bar", "ez_bar")):
            assert e["difficulty_tier"] >= 3, f"{e['exercise_id']} free-bar compound at tier {e['difficulty_tier']}"

def test_known_hard_bodyweight_moves_are_tier_4_plus():
    db = {e["exercise_id"]: e for e in get_exercise_db()}
    for ex_id in ("bw_pull_up_pronated", "bw_weighted_pull_up", "bw_weighted_dip", "bw_deficit_push_up"):
        if ex_id in db:
            assert db[ex_id]["difficulty_tier"] >= 4, f"{ex_id} tier {db[ex_id]['difficulty_tier']}"

def test_isolation_default_two_with_overrides():
    db = {e["exercise_id"]: e for e in get_exercise_db()}
    for e in get_exercise_db():
        if e["movement_pattern"] == "isolation":
            ov = ISOLATION_OVERRIDES.get(e["exercise_id"])
            assert e["difficulty_tier"] == (ov if ov else 2), f"{e['exercise_id']}"

def test_new_incline_pike_exists():
    db = {e["exercise_id"]: e for e in get_exercise_db()}
    assert "bw_incline_pike_push_up" in db
    e = db["bw_incline_pike_push_up"]
    assert e["movement_pattern"] == "vertical_push" and e["equipment_required"] == ["bodyweight"]
