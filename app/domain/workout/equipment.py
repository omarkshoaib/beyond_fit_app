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
