"""
Deterministic week-1 working-load seeding from client baseline lifts.

Inputs: a ClientProfile carrying optional squat_e1rm / bench_e1rm / deadlift_e1rm
(estimated 1RMs computed at intake via Brzycki). Output: a conservative working
load for a slot, or None when the slot's pattern can't be seeded (guidance string
handled downstream).

Source of truth: docs/superpowers/specs/2026-06-13-usability-safety-cluster-design.md
Appendix A (Brzycki, Tuchscherer RPE->%1RM grid, derived-lift ratios). Mandate: err
light — round DOWN; the autoregulator corrects an under-seed in one week.
"""
from __future__ import annotations

import math
from typing import Optional

from app.models import ClientProfile


def brzycki_e1rm(weight_kg: float, reps: int) -> float:
    """Estimated 1RM via Brzycki: w * 36 / (37 - r). Reps clamped to 1..10."""
    r = max(1, min(10, int(reps)))
    return weight_kg * 36.0 / (37.0 - r)


# Tuchscherer / RTS RIR-based %1RM grid. Rows = reps 1..10, cols = RPE 6..10.
# Values are percentages; working_pct() divides by 100.
_PCT_ROWS: dict[int, list[float]] = {
    1:  [86.3, 89.2, 92.2, 95.5, 100.0],
    2:  [83.7, 86.3, 89.2, 92.2, 95.5],
    3:  [81.1, 83.7, 86.3, 89.2, 92.2],
    4:  [78.6, 81.1, 83.7, 86.3, 89.2],
    5:  [76.2, 78.6, 81.1, 83.7, 86.3],
    6:  [73.9, 76.2, 78.6, 81.1, 83.7],
    7:  [71.7, 73.9, 76.2, 78.6, 81.1],
    8:  [69.6, 71.7, 73.9, 76.2, 78.6],
    9:  [67.6, 69.6, 71.7, 73.9, 76.2],
    10: [65.6, 67.6, 69.6, 71.7, 73.9],
}


def working_pct(reps: int, rpe: float) -> float:
    """Fraction of 1RM for `reps` at `rpe`. Reps clamped 1..10, RPE clamped 6..10."""
    r = max(1, min(10, int(reps)))
    e = max(6, min(10, int(round(rpe))))
    return _PCT_ROWS[r][e - 6] / 100.0


# pattern -> (ClientProfile baseline field, ratio). Patterns absent here are
# guidance-only (vertical_pull/lunge/isolation): they return None.
_PATTERN_BASELINE: dict[str, tuple[str, float]] = {
    "squat":            ("squat_e1rm", 1.0),
    "hinge":            ("deadlift_e1rm", 1.0),
    "horizontal_push":  ("bench_e1rm", 1.0),
    "horizontal_pull":  ("bench_e1rm", 0.70),   # barbell row ~0.70 x bench 1RM
    "vertical_push":    ("bench_e1rm", 0.60),   # overhead press ~0.60 x bench 1RM
}


def pattern_e1rm(client: ClientProfile, pattern: str) -> Optional[float]:
    """Derived 1RM for a movement pattern, or None if unseedable/baseline missing."""
    spec = _PATTERN_BASELINE.get(pattern)
    if spec is None:
        return None
    field, ratio = spec
    base = getattr(client, field, None)
    if base is None:
        return None
    return base * ratio


def _first_rep(reps_str: str) -> int:
    """Lower bound of a rep range like '5-8' -> 5. Defaults to 5 on bad input."""
    try:
        return int(str(reps_str).split("-")[0])
    except (ValueError, IndexError, AttributeError):
        return 5


def seed_working_load(
    client: ClientProfile, pattern: str, reps_str: str, rpe: float
) -> Optional[float]:
    """Conservative working load (kg) for a slot, rounded DOWN to 2.5 kg.

    Returns None when the pattern is guidance-only or the needed baseline is absent.
    """
    e1rm = pattern_e1rm(client, pattern)
    if e1rm is None:
        return None
    raw = e1rm * working_pct(_first_rep(reps_str), rpe)
    return math.floor(raw / 2.5) * 2.5
