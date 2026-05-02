"""
Deterministic macro calculation from target kcal + client metrics.

Returns a dict: {kcal, protein_g, fat_g, carb_g, fiber_g, water_ml}

Protein targets (g/kg bodyweight, or g/kg LBM when BF% known):
  fat_loss / recomp → 2.2
  strength          → 2.0
  maintain/lean_bulk→ 1.8
  bulk              → 1.6

Fat: percentage of target kcal with 0.8 g/kg hard floor:
  fat_loss    → 25%
  strength/lean_bulk → 28%
  bulk        → 30%

Carbs: remainder after protein + fat kcal.
  If carbs < 2 g/kg (non-keto), reduce fat to the 0.8 g/kg floor first.

Fiber: round(14 × kcal / 1000), floor 25 g.
Water: 35 ml/kg bodyweight.
"""
from __future__ import annotations

import math
from typing import Optional


_PROTEIN_G_PER_KG: dict[str, float] = {
    "fat_loss":  2.2,
    "recomp":    2.2,
    "strength":  2.0,
    "maintain":  1.8,
    "lean_bulk": 1.8,
    "bulk":      1.6,
}

_FAT_PCT_OF_KCAL: dict[str, float] = {
    "fat_loss":  0.25,
    "recomp":    0.25,
    "strength":  0.28,
    "maintain":  0.28,
    "lean_bulk": 0.28,
    "bulk":      0.30,
}

KCAL_PER_G_PROTEIN = 4.0
KCAL_PER_G_CARB    = 4.0
KCAL_PER_G_FAT     = 9.0
MIN_FAT_G_PER_KG   = 0.8
MIN_CARB_G_PER_KG  = 2.0    # below this we warn (non-keto clients)


def calculate_macros(
    target_kcal: float,
    weight_kg: float,
    goal: str,
    lbm_kg: Optional[float] = None,
) -> dict[str, float]:
    """
    Compute macro targets.  Returns rounded integer values for g fields.

    Parameters
    ----------
    target_kcal : Final calorie target (after goal adjustment + floor).
    weight_kg   : Total bodyweight.
    goal        : One of fat_loss / recomp / strength / maintain / lean_bulk / bulk.
    lbm_kg      : Lean body mass (used for protein when BF% is known).
    """
    ref_kg = lbm_kg if lbm_kg is not None else weight_kg

    # ── Protein ────────────────────────────────────────────────────
    protein_g_per_kg = _PROTEIN_G_PER_KG.get(goal, 1.8)
    protein_g = protein_g_per_kg * ref_kg
    protein_kcal = protein_g * KCAL_PER_G_PROTEIN

    # ── Fat ────────────────────────────────────────────────────────
    fat_pct = _FAT_PCT_OF_KCAL.get(goal, 0.28)
    fat_g = (target_kcal * fat_pct) / KCAL_PER_G_FAT
    fat_floor_g = MIN_FAT_G_PER_KG * weight_kg
    fat_g = max(fat_g, fat_floor_g)

    # ── Carbs ──────────────────────────────────────────────────────
    remaining_kcal = target_kcal - protein_kcal - fat_g * KCAL_PER_G_FAT
    carb_g = remaining_kcal / KCAL_PER_G_CARB

    # If carbs fall below 2 g/kg (non-keto), rescue by reducing fat to floor
    if carb_g < MIN_CARB_G_PER_KG * weight_kg and fat_g > fat_floor_g:
        fat_g = fat_floor_g
        remaining_kcal = target_kcal - protein_kcal - fat_g * KCAL_PER_G_FAT
        carb_g = remaining_kcal / KCAL_PER_G_CARB

    carb_g = max(0.0, carb_g)

    # ── Fiber & water ──────────────────────────────────────────────
    fiber_g = max(25.0, round(14.0 * target_kcal / 1000.0))
    water_ml = 35.0 * (weight_kg or 70.0)

    return {
        "kcal":      round(target_kcal),
        "protein_g": round(protein_g),
        "fat_g":     round(fat_g),
        "carb_g":    round(carb_g),
        "fiber_g":   round(fiber_g),
        "water_ml":  round(water_ml),
    }
