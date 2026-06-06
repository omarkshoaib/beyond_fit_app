"""5/6-meal plans must produce balanced slots, not protein-only snacks."""
import pytest

from app.domain.nutrition.meal_builder import build_day_plan
from app.domain.nutrition.food_db import get_food_db


@pytest.mark.parametrize("meals_per_day", [3, 4, 5, 6])
def test_no_carb_empty_slots(meals_per_day):
    day = build_day_plan(
        food_pool=get_food_db(), target_kcal=2400, target_protein_g=180,
        target_fat_g=80, target_carb_g=240, target_fiber_g=28,
        meals_per_day=meals_per_day, used_slugs_this_week={},
    )
    assert len(day.slots) == meals_per_day
    carb_empty = [s.slot_name for s in day.slots if s.kcal > 0 and s.carb_g == 0]
    assert not carb_empty, f"{meals_per_day}-meal plan has carb-empty (protein-only) slots: {carb_empty}"


def test_snack_slots_draw_from_multiple_categories():
    day = build_day_plan(
        food_pool=get_food_db(), target_kcal=2400, target_protein_g=180,
        target_fat_g=80, target_carb_g=240, target_fiber_g=28,
        meals_per_day=6, used_slugs_this_week={},
    )
    for s in day.slots:
        cats = {f.category for f, _ in s.items}
        assert len(cats) >= 2, f"slot {s.slot_name} is single-category {cats}"
