"""
Evidence-based volume landmarks and prescription constants.

Sources: Israetel et al. (2019) "Scientific Principles of Hypertrophy Training",
         RP Strength volume landmark research.

MEV  = Minimum Effective Volume (sets/week below which no adaptation)
MAV  = Maximum Adaptive Volume (range where most growth occurs)
MRV  = Maximum Recoverable Volume (hard ceiling — exceeding causes net fatigue)
"""
from __future__ import annotations

from typing import Dict

# Budget keys match MUSCLE_TO_BUDGET_KEY in generator.py
VOLUME_LANDMARKS: Dict[str, Dict[str, int]] = {
    "chest":       {"mev": 8,  "mav_low": 12, "mav_high": 20, "mrv": 22},
    "back":        {"mev": 10, "mav_low": 14, "mav_high": 22, "mrv": 25},
    "shoulders":   {"mev": 8,  "mav_low": 12, "mav_high": 20, "mrv": 26},
    "arms":        {"mev": 4,  "mav_low": 10, "mav_high": 18, "mrv": 26},
    "quadriceps":  {"mev": 8,  "mav_low": 12, "mav_high": 18, "mrv": 20},
    "hamstrings":  {"mev": 6,  "mav_low": 10, "mav_high": 16, "mrv": 20},
    "glutes":      {"mev": 6,  "mav_low": 10, "mav_high": 18, "mrv": 22},
    "calves":      {"mev": 8,  "mav_low": 12, "mav_high": 16, "mrv": 20},
}

# Rest periods in seconds by fatigue tier
# fatigue_cost 4-5 = compound (strength/heavy)
# fatigue_cost 2-3 = compound (hypertrophy / moderate)
# fatigue_cost 1   = isolation
REST_BY_FATIGUE: Dict[int, int] = {
    5: 240,
    4: 180,
    3: 150,
    2: 120,
    1: 90,
}

# Default tempo by movement pattern  (eccentric-pause-concentric-pause)
# "X" = explosive concentric; blank = no strict tempo
TEMPO_BY_PATTERN: Dict[str, str] = {
    "squat":            "2-0-X-0",
    "hinge":            "2-1-X-0",
    "horizontal_push":  "2-0-X-0",
    "horizontal_pull":  "2-1-X-0",
    "vertical_push":    "2-0-X-0",
    "vertical_pull":    "2-1-X-0",
    "lunge":            "2-0-X-0",
    "isolation":        "3-0-1-0",
}

# Generic per-pattern coaching cues (1-2 phrases, ≤200 chars each)
# ── Safety: hard-refuse conditions ────────────────────────────────────────────
# Maps a condition key to a human-readable reason shown to the coach.
# Generator raises SafetyRefusalError when any of these conditions are True.
HARD_REFUSE_CONDITIONS: Dict[str, str] = {
    "systolic_bp_high":         "Systolic BP > 160 mmHg — route to physician before exercise",
    "recent_cardiac_event":     "Cardiac event within 24 weeks — requires medical clearance",
    "pregnancy_1st_trimester":  "1st trimester — avoid supine, valsalva, and high-impact; route to specialist",
    "pregnancy_3rd_trimester":  "3rd trimester — high-risk; route to obstetric physiotherapist",
    "unexplained_weight_loss":  "Unexplained weight loss — rule out medical cause before training",
    "progressive_neuro_deficits": "Progressive neurological deficits — medical evaluation required",
}

# ── Substitution map: pattern/condition → safe movement alternatives ───────────
# Maps (limitation, movement_pattern) to replacement patterns safe for that client.
SUBSTITUTION_MAP: Dict[str, Dict[str, list[str]]] = {
    "lower_back_pain": {
        "hinge":  ["horizontal_pull"],          # no conventional deadlift
        "squat":  ["lunge", "horizontal_push"], # avoid back-loaded squats
    },
    "shoulder_impingement": {
        "vertical_push":   ["horizontal_push"],  # no overhead press
        "horizontal_pull": ["vertical_pull"],    # no upright row
    },
    "knee_pain": {
        "squat":  ["horizontal_pull"],           # avoid deep knee flexion
        "lunge":  ["hinge"],
    },
}

# ── Caveat-only limitations (no clean pattern substitution) ──────────────────
# These are not excluded; affected slots get an appended coaching cue instead.
INJURY_CAVEATS: Dict[str, Dict[str, object]] = {
    "wrist_pain": {
        "patterns": {"horizontal_push", "vertical_push", "horizontal_pull", "vertical_pull"},
        "cue": "Wrist caution: neutral grip / wrist wraps; stop on sharp wrist pain.",
    },
    "hip_flexor_tightness": {
        "patterns": {"hinge", "lunge", "squat"},
        "cue": "Hip caution: warm up hip flexors; reduce depth if you feel pinching.",
    },
}

CUES_BY_PATTERN: Dict[str, list[str]] = {
    "squat":           ["Brace core, knees track toes", "Sit into hips, drive through full foot"],
    "hinge":           ["Push floor away, hinge don't squat", "Neutral spine throughout — no rounding"],
    "horizontal_push": ["Retract scapula before unracking", "Elbows at 45° to torso on descent"],
    "horizontal_pull": ["Lead with elbows, not biceps", "Full stretch at arm extension"],
    "vertical_push":   ["Stack shoulder over elbow over wrist", "Avoid excessive lumbar arch"],
    "vertical_pull":   ["Depress scapula before pulling", "Squeeze lat at bottom position"],
    "lunge":           ["Front shin vertical, knee tracks toes", "Push through heel on the drive up"],
    "isolation":       ["Controlled eccentric — resist gravity", "Full ROM; feel the target muscle"],
}
