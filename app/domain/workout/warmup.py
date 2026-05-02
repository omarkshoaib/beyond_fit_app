"""
Warm-up set builder for compound and isolation exercises.

Rules:
- Heavy compounds (main lift): bar×8 → 50%×5 → 70%×3 → 85%×1 (if reps ≤ 5)
  → 90%×1 primer if working load > 1.25× last top set.
  Cap at 6 warm-up sets total.
- Only the FIRST heavy compound in a session gets the full ramp.
  Subsequent compounds get a shortened ramp (50%×5 → 70%×3 only).
- Isolations: single feeder set at ~50% for 8-10 reps, 60 s rest.
- Warm-up sets are NOT counted in weekly volume.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class WarmupSet:
    pct_of_working: float       # e.g. 0.50, 0.70, 0.85, 1.00
    reps: int
    rest_seconds: int
    is_primer: bool = False     # True for the high-% near-max primer set


def build_warmup(
    working_load_kg: float,
    bar_kg: float = 20.0,
    working_reps: int = 5,
    is_compound: bool = True,
    is_main_lift: bool = True,
    last_top_set_kg: Optional[float] = None,
) -> list[WarmupSet]:
    """
    Return a list of WarmupSet objects appropriate for the given exercise.

    Parameters
    ----------
    working_load_kg:  The target load for the working sets.
    bar_kg:           Weight of the empty bar (default 20 kg Olympic).
    working_reps:     Number of reps in the working set (used to decide 85% primer).
    is_compound:      True for multi-joint movements; False for isolations.
    is_main_lift:     True for the first heavy compound per session (full ramp).
                      False for subsequent compounds (shortened ramp).
    last_top_set_kg:  Previous session's top-set load — triggers 90% primer if
                      working_load_kg > 1.25 × last_top_set_kg.
    """
    if not is_compound:
        # Single feeder set at ~50%
        return [WarmupSet(pct_of_working=0.50, reps=10, rest_seconds=60)]

    sets: list[WarmupSet] = []

    if is_main_lift:
        # Bar-only ramp (always first)
        bar_pct = bar_kg / working_load_kg if working_load_kg > 0 else 0.0
        sets.append(WarmupSet(pct_of_working=min(bar_pct, 0.40), reps=8, rest_seconds=60))

    # 50% × 5
    sets.append(WarmupSet(pct_of_working=0.50, reps=5, rest_seconds=60))
    # 70% × 3
    sets.append(WarmupSet(pct_of_working=0.70, reps=3, rest_seconds=90))

    # 85% × 1 primer for strength-range work
    if working_reps <= 5:
        sets.append(WarmupSet(pct_of_working=0.85, reps=1, rest_seconds=120, is_primer=True))

    # 90% × 1 if jumping significantly from last session
    if last_top_set_kg is not None and working_load_kg > 1.25 * last_top_set_kg:
        sets.append(WarmupSet(pct_of_working=0.90, reps=1, rest_seconds=120, is_primer=True))

    # Hard cap: 6 warm-up sets
    return sets[:6]
