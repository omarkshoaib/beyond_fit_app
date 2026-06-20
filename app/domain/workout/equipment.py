"""Equipment vocabulary, intake presets, and the equipment floor (SP-A C1).

Pure helpers — no I/O. The 16 real equipment tokens are whatever the exercise DB
uses; ``bodyweight`` is always implicit (never a checkbox) and ``full_gym`` is the
wildcard meaning "has everything". The checklist is the remaining real tokens.
"""
from __future__ import annotations

# The 15 client-facing checklist tokens (bodyweight is implicit; full_gym is the
# wildcard preset). Grouped roughly free-weights -> machines -> calisthenics stations;
# the niche barbell attachments (ez_bar, trap_bar, landmine) are included so a Custom
# build can express them, but presets fold them under "Commercial gym".
CHECKLIST_TOKENS: list[str] = [
    "barbell", "squat_rack", "bench", "dumbbells", "kettlebell",
    "smith_machine", "cable_machine", "leg_press_machine",
    "leg_extension_machine", "leg_curl_machine",
    "pull_up_bar", "dip_station", "ez_bar", "trap_bar", "landmine",
]

# Preset key -> the equipment list it resolves to. "home" opens the checklist
# pre-checked with this set; "custom" opens it empty (handled in the bot layer).
EQUIPMENT_PRESETS: dict[str, list[str]] = {
    "commercial": ["full_gym"],
    "home": ["dumbbells", "bench", "pull_up_bar"],
    "minimal": ["bodyweight", "pull_up_bar"],
    "bodyweight": ["bodyweight"],
}


def floor_equipment(tokens: "list[str] | None") -> list[str]:
    """Never return an empty equipment list — an empty list makes the generator
    reject every exercise and produce a zero-exercise plan. Empty/None -> bodyweight."""
    return list(tokens) if tokens else ["bodyweight"]


from dataclasses import dataclass


@dataclass
class Violation:
    exercise_id: str
    exercise_name: str
    missing: list[str]  # missing equipment tokens, or ["<unknown exercise>"]


def _has_all(required: "list[str]", available: "set[str]") -> bool:
    return "full_gym" in available or all(tok in available for tok in required)


def validate_equipment(week, available_equipment: "list[str] | None") -> list[Violation]:
    """Every slot's exercise must be satisfiable by the client's equipment.
    An exercise id not in the DB is also a violation (cannot verify it)."""
    from app.exercise_db import get_exercise_db
    db = {e["exercise_id"]: e for e in get_exercise_db()}
    avail = set(available_equipment or ["full_gym"])  # empty -> wildcard (legacy-safe)
    out: list[Violation] = []
    seen: set[str] = set()
    for day in week.days:
        for slot in day.slots:
            if slot.exercise_id in seen:
                continue
            seen.add(slot.exercise_id)
            ex = db.get(slot.exercise_id)
            if ex is None:
                out.append(Violation(slot.exercise_id, slot.exercise_name, ["<unknown exercise>"]))
                continue
            if not _has_all(ex["equipment_required"], avail):
                missing = [t for t in ex["equipment_required"] if t not in avail]
                out.append(Violation(slot.exercise_id, slot.exercise_name, missing))
    return out


def equipment_alternatives(exercise_id: str, available_equipment: "list[str] | None",
                           limit: int = 5) -> list[dict]:
    """Equipment-valid exercises sharing the target's primary muscle (and pattern when
    possible), deterministically sorted. Empty if the target id is unknown."""
    from app.exercise_db import get_exercise_db
    db = get_exercise_db()
    target = next((e for e in db if e["exercise_id"] == exercise_id), None)
    if target is None:
        return []
    avail = set(available_equipment or ["full_gym"])
    same_muscle = [
        e for e in db
        if e["exercise_id"] != exercise_id
        and e["primary_muscle"] == target["primary_muscle"]
        and _has_all(e["equipment_required"], avail)
    ]
    same_pat = sorted((e for e in same_muscle if e["movement_pattern"] == target["movement_pattern"]),
                      key=lambda e: e["exercise_id"])
    other = sorted((e for e in same_muscle if e["movement_pattern"] != target["movement_pattern"]),
                   key=lambda e: e["exercise_id"])
    return (same_pat + other)[:limit]


def reachable_patterns(available_equipment: "list[str] | None") -> set[str]:
    """Movement patterns for which at least one exercise is equipment-valid."""
    from app.exercise_db import get_exercise_db
    avail = set(available_equipment or ["full_gym"])
    return {e["movement_pattern"] for e in get_exercise_db()
            if _has_all(e["equipment_required"], avail)}
