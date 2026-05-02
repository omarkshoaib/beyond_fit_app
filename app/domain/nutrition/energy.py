"""
Deterministic energy (BMR + TDEE) calculations.

Formulas:
- Mifflin-St Jeor (default): weight, height, age, sex
- Katch-McArdle (if body_fat_pct provided): lean body mass based

Activity multipliers (5 levels):
  sedentary=1.2, lightly_active=1.375, moderately_active=1.55,
  very_active=1.725, extra_active=1.9

Design rule: bias one level LOWER than the user selects (users overestimate).
Never double-count workouts on top of an activity multiplier that already
includes them.

Hard calorie floor:
  max(1200 female / 1500 male, BMR × 1.1, 22 kcal/kg bodyweight)
"""
from __future__ import annotations

from typing import Literal

Sex = Literal["male", "female"]
ActivityLevel = Literal[
    "sedentary", "lightly_active", "moderately_active", "very_active", "extra_active"
]

_ACTIVITY_MULTIPLIERS: dict[ActivityLevel, float] = {
    "sedentary":         1.2,
    "lightly_active":    1.375,
    "moderately_active": 1.55,
    "very_active":       1.725,
    "extra_active":      1.9,
}

_ACTIVITY_ORDER: list[ActivityLevel] = [
    "sedentary", "lightly_active", "moderately_active", "very_active", "extra_active"
]


def calculate_bmr(
    weight_kg: float,
    height_cm: float,
    age: int,
    sex: Sex,
    body_fat_pct: float | None = None,
) -> float:
    """
    Return Basal Metabolic Rate in kcal/day.

    Uses Katch-McArdle when body_fat_pct is provided (range 3–60%).
    Falls back to Mifflin-St Jeor otherwise.
    """
    if body_fat_pct is not None and 3.0 <= body_fat_pct <= 60.0:
        lbm_kg = weight_kg * (1.0 - body_fat_pct / 100.0)
        return 370.0 + 21.6 * lbm_kg          # Katch-McArdle

    # Mifflin-St Jeor
    bmr = 10.0 * weight_kg + 6.25 * height_cm - 5.0 * age
    return bmr + 5.0 if sex == "male" else bmr - 161.0


def calculate_tdee(
    bmr: float,
    activity_level: ActivityLevel,
    bias_down: bool = True,
) -> float:
    """
    Return Total Daily Energy Expenditure in kcal/day.

    bias_down=True (default): uses one activity tier lower than supplied.
    """
    if bias_down:
        idx = _ACTIVITY_ORDER.index(activity_level)
        biased_level = _ACTIVITY_ORDER[max(0, idx - 1)]
    else:
        biased_level = activity_level
    return bmr * _ACTIVITY_MULTIPLIERS[biased_level]


def apply_goal_adjustment(
    tdee: float,
    goal: str,           # "fat_loss" | "lean_bulk" | "bulk" | "recomp" | "maintain"
    aggressiveness: str, # "conservative" | "moderate" | "aggressive"
) -> float:
    """Return target kcal after applying goal surplus/deficit."""
    _deltas: dict[str, dict[str, float]] = {
        "fat_loss":  {"conservative": -0.10, "moderate": -0.20, "aggressive": -0.25},
        "lean_bulk": {"conservative": +0.05, "moderate": +0.10, "aggressive": +0.15},
        "bulk":      {"conservative": +0.10, "moderate": +0.15, "aggressive": +0.20},
        "recomp":    {"conservative": -0.05, "moderate":  0.00, "aggressive": +0.05},
        "maintain":  {"conservative":  0.00, "moderate":  0.00, "aggressive":  0.00},
    }
    delta_pct = _deltas.get(goal, {}).get(aggressiveness, 0.0)
    return tdee * (1.0 + delta_pct)


def apply_calorie_floor(
    target_kcal: float,
    bmr: float,
    weight_kg: float,
    sex: Sex,
) -> float:
    """Clamp target_kcal to the safety floor."""
    absolute_floor = 1500.0 if sex == "male" else 1200.0
    bmr_floor = bmr * 1.1
    weight_floor = 22.0 * weight_kg
    return max(target_kcal, absolute_floor, bmr_floor, weight_floor)
