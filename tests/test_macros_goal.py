"""Product: low-carb is goal-integrated (fat-loss leans lower-carb), never a separate style."""
from app.domain.nutrition.macros import calculate_macros


def test_fat_loss_is_lower_carb_than_bulk():
    cut = calculate_macros(1800, 80, "fat_loss")
    bulk = calculate_macros(1800, 80, "bulk")
    assert cut["carb_g"] < bulk["carb_g"]


def test_carbs_never_negative_on_aggressive_cut():
    # Very low kcal, heavy bodyweight → carbs must floor at 0, never negative.
    m = calculate_macros(1000, 110, "fat_loss")
    assert m["carb_g"] >= 0


def test_macros_are_deterministic():
    a = calculate_macros(2200, 75, "maintain")
    b = calculate_macros(2200, 75, "maintain")
    assert a == b
