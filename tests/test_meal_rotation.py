from app.domain.nutrition.food_db import get_food_db
from app.domain.nutrition.meal_builder import build_day_plan, filter_food_pool


def _pool():
    return filter_food_pool(get_food_db())


def _build_week(meals=3):
    pool = _pool()
    days = []
    used = {}
    for day_index in range(7):
        d = build_day_plan(pool, 2200, 165, 70, 230, 30,
                           meals_per_day=meals, used_slugs_this_week=used,
                           day_index=day_index)
        for slot in d.slots:
            for food, _ in slot.items:
                used[food.slug] = used.get(food.slug, 0) + 1
        days.append(d)
    return days


def test_week_uses_varied_proteins():
    days = _build_week()
    proteins = set()
    for d in days:
        for slot in d.slots:
            for food, _ in slot.items:
                if food.category == "protein":
                    proteins.add(food.slug)
    assert len(proteins) >= 3, f"only {len(proteins)} distinct proteins across the week"


def test_no_food_exceeds_five_days():
    days = _build_week()
    counts = {}
    for d in days:
        seen_today = {food.slug for slot in d.slots for food, _ in slot.items}
        for slug in seen_today:
            counts[slug] = counts.get(slug, 0) + 1
    assert all(c <= 5 for c in counts.values()), f"a food exceeded 5 days: {counts}"


def test_consecutive_days_differ():
    days = _build_week()
    def primary_protein(d):
        for slot in d.slots:
            for food, _ in slot.items:
                if food.category == "protein":
                    return food.slug
        return None
    diffs = sum(1 for i in range(1, 7) if primary_protein(days[i]) != primary_protein(days[i-1]))
    assert diffs >= 3, "meal plan barely varies day to day"


def test_determinism():
    assert [s.slug for d in _build_week() for slot in d.slots for s, _ in slot.items] == \
           [s.slug for d in _build_week() for slot in d.slots for s, _ in slot.items]
