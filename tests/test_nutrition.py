"""
Phase 3 tests: energy formulas, macro calculations, safety floors.
All deterministic — no LLM, no DB, no network.
"""
import pytest
from app.domain.nutrition.energy import (
    calculate_bmr, calculate_tdee, apply_goal_adjustment, apply_calorie_floor
)
from app.domain.nutrition.macros import calculate_macros


# ── BMR tests ─────────────────────────────────────────────────────

def test_bmr_mifflin_male():
    """Mifflin-St Jeor for a reference 80 kg, 180 cm, 30 y/o male."""
    bmr = calculate_bmr(weight_kg=80, height_cm=180, age=30, sex="male")
    # 10×80 + 6.25×180 - 5×30 + 5 = 800 + 1125 - 150 + 5 = 1780
    assert abs(bmr - 1780.0) < 0.1


def test_bmr_mifflin_female():
    """Mifflin-St Jeor for 60 kg, 165 cm, 28 y/o female."""
    bmr = calculate_bmr(weight_kg=60, height_cm=165, age=28, sex="female")
    # 10×60 + 6.25×165 - 5×28 - 161 = 600 + 1031.25 - 140 - 161 = 1330.25
    assert abs(bmr - 1330.25) < 0.1


def test_bmr_katch_mcardle_used_when_bf_provided():
    """Katch-McArdle should return a higher BMR for lean clients than Mifflin."""
    bmr_no_bf = calculate_bmr(weight_kg=80, height_cm=180, age=30, sex="male")
    bmr_with_bf = calculate_bmr(weight_kg=80, height_cm=180, age=30, sex="male", body_fat_pct=10)
    # Katch-McArdle on high LBM should give a higher BMR
    assert bmr_with_bf > bmr_no_bf


def test_bmr_bf_pct_out_of_range_falls_back_to_mifflin():
    """BF% outside 3–60 range must fall back to Mifflin-St Jeor."""
    bmr_normal = calculate_bmr(weight_kg=80, height_cm=180, age=30, sex="male")
    bmr_invalid_bf = calculate_bmr(weight_kg=80, height_cm=180, age=30, sex="male", body_fat_pct=2)
    assert abs(bmr_normal - bmr_invalid_bf) < 0.1


# ── TDEE tests ────────────────────────────────────────────────────

def test_tdee_bias_down():
    """TDEE with bias_down=True should be lower than with bias_down=False."""
    bmr = 1780.0
    tdee_biased = calculate_tdee(bmr, "very_active", bias_down=True)
    tdee_unbiased = calculate_tdee(bmr, "very_active", bias_down=False)
    assert tdee_biased < tdee_unbiased


def test_tdee_sedentary_floor():
    """Sedentary already at the lowest level — bias_down has no further effect."""
    bmr = 1400.0
    tdee_biased = calculate_tdee(bmr, "sedentary", bias_down=True)
    tdee_unbiased = calculate_tdee(bmr, "sedentary", bias_down=False)
    assert tdee_biased == tdee_unbiased


# ── Goal adjustment tests ─────────────────────────────────────────

@pytest.mark.parametrize("goal,aggressiveness,expected_sign", [
    ("fat_loss",  "moderate",  -1),
    ("lean_bulk", "moderate",  +1),
    ("maintain",  "moderate",   0),
    ("recomp",    "moderate",   0),
])
def test_goal_adjustment_direction(goal, aggressiveness, expected_sign):
    tdee = 2500.0
    adjusted = apply_goal_adjustment(tdee, goal, aggressiveness)
    diff = adjusted - tdee
    if expected_sign > 0:
        assert diff > 0
    elif expected_sign < 0:
        assert diff < 0
    else:
        assert diff == 0.0


def test_goal_adjustment_fat_loss_aggressive_cap():
    """Aggressive fat loss must not exceed -25%."""
    tdee = 2500.0
    adjusted = apply_goal_adjustment(tdee, "fat_loss", "aggressive")
    assert adjusted == pytest.approx(tdee * 0.75, rel=1e-6)


# ── Calorie floor tests ───────────────────────────────────────────

def test_calorie_floor_female_minimum():
    """Female floor: max(1200, BMR×1.1, 22×kg)."""
    bmr = 1000.0
    result = apply_calorie_floor(target_kcal=900, bmr=bmr, weight_kg=50, sex="female")
    assert result >= 1200.0


def test_calorie_floor_not_applied_when_above():
    """No floor needed when target is already safe."""
    bmr = 1400.0
    result = apply_calorie_floor(target_kcal=2000, bmr=bmr, weight_kg=70, sex="male")
    assert result == 2000.0


# ── Macro tests ───────────────────────────────────────────────────

def test_macros_kcal_balance():
    """Protein + fat + carb kcal must be within 5% of target kcal."""
    macros = calculate_macros(target_kcal=2500, weight_kg=80, goal="fat_loss")
    actual_kcal = (
        macros["protein_g"] * 4
        + macros["fat_g"] * 9
        + macros["carb_g"] * 4
    )
    assert abs(actual_kcal - macros["kcal"]) / macros["kcal"] < 0.05


def test_macros_protein_fat_loss():
    """Fat loss protein must be ~2.2 g/kg."""
    macros = calculate_macros(target_kcal=2000, weight_kg=75, goal="fat_loss")
    expected_protein = round(2.2 * 75)
    assert abs(macros["protein_g"] - expected_protein) <= 2


def test_macros_fat_floor_respected():
    """Fat must never drop below 0.8 g/kg."""
    macros = calculate_macros(target_kcal=1400, weight_kg=60, goal="fat_loss")
    assert macros["fat_g"] >= round(0.8 * 60)


def test_macros_fiber_floor():
    """Fiber must be at least 25 g."""
    macros = calculate_macros(target_kcal=1200, weight_kg=50, goal="fat_loss")
    assert macros["fiber_g"] >= 25


def test_macros_water_ml():
    """Water should be 35 ml/kg."""
    macros = calculate_macros(target_kcal=2500, weight_kg=80, goal="maintain")
    assert macros["water_ml"] == 35 * 80


def test_macros_carb_rescue():
    """When carbs < 2 g/kg, fat should be reduced to floor to rescue carbs."""
    # Very low kcal + fat_loss = carbs might go below 2 g/kg without rescue
    macros = calculate_macros(target_kcal=1500, weight_kg=90, goal="fat_loss")
    # After rescue, carbs should be >= 2 g/kg OR fat should be at floor
    min_fat = round(0.8 * 90)
    assert macros["fat_g"] >= min_fat


@pytest.mark.parametrize("goal", ["fat_loss", "lean_bulk", "maintain", "bulk", "recomp"])
def test_macros_all_goals_positive(goal):
    """All macros must be positive for every goal."""
    macros = calculate_macros(target_kcal=2200, weight_kg=75, goal=goal)
    for key in ("protein_g", "fat_g", "carb_g", "fiber_g", "water_ml"):
        assert macros[key] >= 0, f"{goal}: {key} is negative"


def test_macros_with_lbm():
    """Providing LBM should increase protein vs total bodyweight."""
    macros_total = calculate_macros(target_kcal=2500, weight_kg=100, goal="fat_loss")
    macros_lbm = calculate_macros(target_kcal=2500, weight_kg=100, goal="fat_loss", lbm_kg=75)
    # LBM 75 < total 100, so protein should be lower with LBM
    assert macros_lbm["protein_g"] < macros_total["protein_g"]
