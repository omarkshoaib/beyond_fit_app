"""Safety: medical filtering must never empty the food pool (→ 0-kcal plans)."""
from app.domain.nutrition.meal_builder import filter_food_pool
from app.domain.nutrition.food_db import get_food_db


def test_medical_filter_never_empties_pool():
    for cond in (["hypertension"], ["type2_diabetes"], ["hypertension", "type2_diabetes"]):
        pool = filter_food_pool(pool=get_food_db(), medical_conditions=cond)
        assert len(pool) >= 10, f"{cond} produced a {len(pool)}-food pool"


def test_no_medical_condition_returns_full_pool():
    full = filter_food_pool(pool=get_food_db())
    assert len(full) == len(get_food_db())
