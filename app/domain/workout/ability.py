# app/domain/workout/ability.py
"""Ability tiers, the 6 difficulty ladders, and rung selection (SP-B1).

Pure logic. difficulty_tier lives on the exercise dicts (see exercise_db.get_exercise_db);
this module orders the anchor variants per family and picks the client's rung.
"""
from __future__ import annotations

FAMILIES = ["squat", "hinge", "horizontal_push", "vertical_push",
            "horizontal_pull", "vertical_pull"]

# Ordered ascending by difficulty_tier (spec Appendix A). Keyed lookups use the exercise's
# own difficulty_tier, so list order only breaks within-tier ties (lowest index = canonical).
LADDERS: dict[str, list[str]] = {
    "squat": ["bw_air_squat", "db_goblet_squat", "smith_back_squat",
              "bb_back_squat_highbar", "bb_back_squat_lowbar"],
    # bb_deadlift_conventional before bb_romanian_deadlift (both tier 4) so the within-tier
    # tie-break makes the CONVENTIONAL DEADLIFT the tier-4 hinge main (cross-family invariant).
    "hinge": ["bw_glute_bridge", "cable_pull_through", "db_romanian_deadlift",
              "bb_deadlift_conventional", "bb_romanian_deadlift", "bb_deficit_deadlift"],
    "horizontal_push": ["bw_knee_push_up", "machine_chest_press", "bw_push_up",
                        "db_flat_bench_press", "bb_bench_press", "bw_weighted_dip"],
    "vertical_push": ["bw_incline_pike_push_up", "smith_shoulder_press", "bw_pike_push_up",
                      "db_seated_shoulder_press", "bb_overhead_press", "bb_push_press"],
    "horizontal_pull": ["bw_inverted_row_bar", "db_single_arm_row", "db_chest_supported_row",
                        "bb_bent_over_row_pronated", "bb_pendlay_row", "bw_inverted_row_feet_elevated"],
    "vertical_pull": ["machine_assisted_pull_up", "cable_wide_grip_lat_pulldown",
                      "cable_neutral_grip_lat_pulldown", "bw_pull_up_pronated", "bw_weighted_pull_up"],
}

_EXPERIENCE_DEFAULT = {"beginner": 2, "intermediate": 4, "advanced": 4}


def global_ability(experience_level: str) -> int:
    """Coarse ability for non-anchor (isolation/lunge) gating."""
    return _EXPERIENCE_DEFAULT.get(experience_level, 2)


def client_ability(experience_level: str, exercise_ability: "dict | None", family: str) -> int:
    """Per-family ability. NULL/missing family value -> experience default (never throws)."""
    if exercise_ability and family in exercise_ability and exercise_ability[family] is not None:
        return int(exercise_ability[family])
    return global_ability(experience_level)


def _equipment_ok(required: "list[str]", available: "list[str] | None") -> bool:
    avail = set(available or ["full_gym"])
    return "full_gym" in avail or all(tok in avail for tok in required)


def ladder_rung(family: str, ability: int, available_equipment: "list[str] | None"):
    """The exercise_id for the client's rung in `family`:
    highest difficulty_tier <= ability that is equipment-valid; tie-break by ladder index.
    FLOOR: if none <= ability is valid, the LOWEST equipment-valid rung (never above-ability
    unless forced). None only if NO rung is equipment-valid (caller skips the slot)."""
    from app.exercise_db import get_exercise_db
    db = {e["exercise_id"]: e for e in get_exercise_db()}
    rungs = LADDERS.get(family, [])
    valid = [(i, rid, db[rid]["difficulty_tier"]) for i, rid in enumerate(rungs)
             if rid in db and _equipment_ok(db[rid]["equipment_required"], available_equipment)]
    if not valid:
        return None
    at_or_below = [(i, rid, t) for (i, rid, t) in valid if t <= ability]
    if at_or_below:
        # highest tier, then lowest ladder index within that tier
        best_tier = max(t for (_, _, t) in at_or_below)
        return min((x for x in at_or_below if x[2] == best_tier), key=lambda x: x[0])[1]
    # floor: lowest tier available, then lowest index
    min_tier = min(t for (_, _, t) in valid)
    return min((x for x in valid if x[2] == min_tier), key=lambda x: x[0])[1]
