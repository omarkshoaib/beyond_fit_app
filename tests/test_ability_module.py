# tests/test_ability_module.py
from app.domain.workout import ability as ab

def test_families_and_ladders_present():
    assert set(ab.FAMILIES) == {"squat", "hinge", "horizontal_push", "vertical_push",
                                 "horizontal_pull", "vertical_pull"}
    for fam in ab.FAMILIES:
        assert ab.LADDERS[fam], f"{fam} ladder empty"

def test_ladders_are_nondecreasing_in_tier_and_ids_exist():
    from app.exercise_db import get_exercise_db
    db = {e["exercise_id"]: e for e in get_exercise_db()}
    for fam, rungs in ab.LADDERS.items():
        tiers = []
        for ex_id in rungs:
            assert ex_id in db, f"{fam}: {ex_id} not in DB"
            tiers.append(db[ex_id]["difficulty_tier"])
        assert tiers == sorted(tiers), f"{fam} ladder not ascending: {tiers}"

def test_global_ability_from_experience():
    assert ab.global_ability("beginner") == 2
    assert ab.global_ability("intermediate") == 3
    assert ab.global_ability("advanced") == 4

def test_client_ability_coerces_none_to_experience_default():
    # NULL exercise_ability -> experience default; present value overrides per family
    assert ab.client_ability("beginner", None, "squat") == 2
    assert ab.client_ability("advanced", {}, "squat") == 4
    assert ab.client_ability("beginner", {"squat": 4}, "squat") == 4
    assert ab.client_ability("beginner", {"squat": 4}, "hinge") == 2  # other family falls back

def test_ladder_rung_picks_highest_at_or_below_ability_equipment_valid():
    # ability 3, full equipment -> highest squat rung tier<=3 = smith_back_squat(3)
    assert ab.ladder_rung("squat", 3, ["full_gym"]) == "smith_back_squat"
    # ability 5, full -> top rung
    assert ab.ladder_rung("squat", 5, ["full_gym"]) == "bb_back_squat_lowbar"
    # bodyweight only, ability 3 -> only bw_air_squat(2) is equipment-valid
    assert ab.ladder_rung("squat", 3, ["bodyweight"]) == "bw_air_squat"

def test_ladder_rung_floor_when_ability_below_lowest():
    # vertical_pull lowest rung is machine_assisted_pull_up(1); ability 1 picks it
    assert ab.ladder_rung("vertical_pull", 1, ["full_gym"]) == "machine_assisted_pull_up"
    # ability below lowest equipment-valid rung -> floor to the lowest equipment-valid rung,
    # never None when SOME rung is valid
    assert ab.ladder_rung("squat", 1, ["bodyweight"]) == "bw_air_squat"  # air squat is t2 > 1 -> floor

def test_ladder_rung_none_when_no_equipment_valid_rung():
    # vertical_pull rungs all need pull_up_bar/cable; a no-equipment client -> None (slot skips)
    assert ab.ladder_rung("vertical_pull", 5, ["bodyweight"]) is None


def test_hinge_tier4_default_is_conventional_deadlift():
    # cross-family invariant: tier-4 hinge main = the conventional deadlift, not the RDL
    assert ab.ladder_rung("hinge", 4, ["full_gym"]) == "bb_deadlift_conventional"


def test_clientprofile_has_exercise_ability_field():
    from app.models import ClientProfile
    p = ClientProfile(client_id="cl_x", exercise_ability={"squat": 3})
    assert p.exercise_ability == {"squat": 3}
    p2 = ClientProfile(client_id="cl_y")
    assert p2.exercise_ability is None  # NULL-safe default
