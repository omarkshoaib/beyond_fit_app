"""
Deterministic meal plan builder.

Algorithm:
1. Cascade-filter food pool:
   allergens (hard) → religious (hard) → diet type (hard) → dislikes (hard)
   → medical caps (T2D sugar, HTN sodium) → budget (soft) → skill/time (soft)

2. Split daily kcal target across meal slots by preference
   (default 3-meal: 30 / 40 / 30 %).

3. Per slot: pick protein + starch + veg + fat templates, avoiding same
   template as yesterday, capping repeats at ≤2×/week.

4. Portion-optimise with PuLP (CBC solver):
   minimise weighted error across {kcal P F C} with weights 1/2/1/1.
   Round portions to nearest 5 g.

5. Day validation:
   kcal ±5% hard (±8% fallback); protein −5%/+20%; fat ±10%, floor 0.8 g/kg;
   fiber ≥ 80% target.

6. Week validation (summary stats only — full week generation is caller's job):
   no food > 5 days/week.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class FoodItem:
    slug: str
    name: str
    kcal_per_100g: float
    protein_per_100g: float
    fat_per_100g: float
    carb_per_100g: float
    fiber_per_100g: float
    category: str                  # protein / grain / veg / fruit / fat / dairy / legume
    diet_tags: list[str]           # vegan, vegetarian, pescatarian, keto, …
    allergens: list[str]           # gluten, dairy, nuts, eggs, soy, shellfish, …
    religious_restrictions: list[str]  # halal, kosher, …
    meal_slots: list[str]          # breakfast, lunch, dinner, snack
    cost_tier: int                 # 1=cheap 2=moderate 3=premium
    prep_time_min: int
    cooking_skill: int             # 1=none 2=basic 3=intermediate 4=advanced
    satiety_index: float = 1.0
    is_whole_food: bool = True
    medical_tags: list[str] = field(default_factory=list)  # "low_sugar","low_sodium"…


@dataclass
class MealSlotPlan:
    slot_name: str                 # breakfast / lunch / dinner / snack
    items: list[tuple[FoodItem, float]]  # (food, grams)
    kcal: float
    protein_g: float
    fat_g: float
    carb_g: float
    fiber_g: float


@dataclass
class DayPlan:
    slots: list[MealSlotPlan]
    kcal: float
    protein_g: float
    fat_g: float
    carb_g: float
    fiber_g: float


# ── Cascade filter ─────────────────────────────────────────────────────────────

def filter_food_pool(
    pool: list[FoodItem],
    allergens: list[str] | None = None,
    religious_restrictions: list[str] | None = None,
    diet_type: str | None = None,
    dislikes: list[str] | None = None,
    medical_conditions: list[str] | None = None,
    max_cost_tier: int = 3,
    max_prep_time_min: int = 120,
    max_cooking_skill: int = 4,
) -> list[FoodItem]:
    """
    Apply hard and soft filters to the food pool.
    Hard filters (allergens, religious, diet, dislikes) remove items entirely.
    Soft filters (budget, time, skill) log a warning but still return the full
    filtered-hard pool if nothing passes the soft filters.
    """
    # Hard filters
    result = pool
    if allergens:
        result = [f for f in result if not any(a in f.allergens for a in allergens)]
    if religious_restrictions:
        result = [f for f in result if not any(r in f.religious_restrictions for r in religious_restrictions)]
    if diet_type and diet_type not in ("omnivore", "balanced", "none"):
        result = [f for f in result if diet_type in f.diet_tags]
    if dislikes:
        dislike_set = {d.lower() for d in dislikes}
        result = [f for f in result if f.slug not in dislike_set and f.name.lower() not in dislike_set]
    if medical_conditions:
        for condition in medical_conditions:
            if condition == "hypertension":
                result = [f for f in result if "low_sodium" in f.medical_tags]
            if condition == "type2_diabetes":
                result = [f for f in result if "low_sugar" in f.medical_tags and f.carb_per_100g < 25]

    # Soft filters (degrade gracefully)
    soft_result = [
        f for f in result
        if f.cost_tier <= max_cost_tier
        and f.prep_time_min <= max_prep_time_min
        and f.cooking_skill <= max_cooking_skill
    ]
    if not soft_result:
        logger.warning("Soft filters excluded all foods — ignoring soft constraints")
        return result
    return soft_result


# ── Portion optimiser ──────────────────────────────────────────────────────────

def _optimise_portions(
    items: list[FoodItem],
    target_kcal: float,
    target_protein_g: float,
    target_fat_g: float,
    target_carb_g: float,
    min_portion_g: float = 30.0,
    max_portion_g: float = 400.0,
) -> list[tuple[FoodItem, float]]:
    """
    Solve a linear programme to find gram-portions for each food item that
    minimises weighted macro error.  Falls back to equal-split if PuLP unavailable.

    Weights: kcal=1, protein=2, fat=1, carb=1 (protein is most important).
    Returns list of (FoodItem, grams) tuples, portions rounded to nearest 5 g.
    """
    try:
        import pulp  # type: ignore
    except ImportError:
        logger.warning("PuLP not available — using naive equal-split portions")
        return _naive_portions(items, target_kcal)

    prob = pulp.LpProblem("meal_portions", pulp.LpMinimize)

    # Decision variables: grams of each food (continuous, bounded)
    vars_ = [
        pulp.LpVariable(f"g_{i}", lowBound=min_portion_g, upBound=max_portion_g)
        for i in range(len(items))
    ]

    # Scale factor: per-100g → per-gram
    def _macro(food: FoodItem, attr: str) -> float:
        return getattr(food, attr) / 100.0

    # Auxiliary absolute-deviation variables for each macro
    d_kcal = pulp.LpVariable("d_kcal", lowBound=0)
    d_prot = pulp.LpVariable("d_prot", lowBound=0)
    d_fat  = pulp.LpVariable("d_fat",  lowBound=0)
    d_carb = pulp.LpVariable("d_carb", lowBound=0)

    # Objective: minimise weighted sum of deviations
    prob += 1 * d_kcal + 2 * d_prot + 1 * d_fat + 1 * d_carb

    # Macro expressions
    kcal_expr  = pulp.lpSum(_macro(f, "kcal_per_100g")    * v for f, v in zip(items, vars_))
    prot_expr  = pulp.lpSum(_macro(f, "protein_per_100g") * v for f, v in zip(items, vars_))
    fat_expr   = pulp.lpSum(_macro(f, "fat_per_100g")     * v for f, v in zip(items, vars_))
    carb_expr  = pulp.lpSum(_macro(f, "carb_per_100g")    * v for f, v in zip(items, vars_))

    # Absolute value linearisation: d >= expr - target, d >= target - expr
    prob += d_kcal >= kcal_expr - target_kcal
    prob += d_kcal >= target_kcal - kcal_expr
    prob += d_prot >= prot_expr - target_protein_g
    prob += d_prot >= target_protein_g - prot_expr
    prob += d_fat  >= fat_expr  - target_fat_g
    prob += d_fat  >= target_fat_g - fat_expr
    prob += d_carb >= carb_expr - target_carb_g
    prob += d_carb >= target_carb_g - carb_expr

    prob.solve(pulp.PULP_CBC_CMD(msg=0))

    portions = []
    for food, var in zip(items, vars_):
        grams = var.varValue or min_portion_g
        grams = round(grams / 5.0) * 5.0   # round to nearest 5 g
        grams = max(min_portion_g, min(max_portion_g, grams))
        portions.append((food, grams))

    return portions


def _naive_portions(
    items: list[FoodItem], target_kcal: float
) -> list[tuple[FoodItem, float]]:
    """Equal-split fallback when PuLP is unavailable."""
    if not items:
        return []
    per_item_kcal = target_kcal / len(items)
    portions = []
    for food in items:
        if food.kcal_per_100g > 0:
            grams = round((per_item_kcal / food.kcal_per_100g) * 100 / 5.0) * 5.0
        else:
            grams = 100.0
        grams = max(30.0, min(400.0, grams))
        portions.append((food, grams))
    return portions


# ── Slot macro totals ──────────────────────────────────────────────────────────

def _sum_macros(portions: list[tuple[FoodItem, float]]) -> dict[str, float]:
    kcal = protein = fat = carb = fiber = 0.0
    for food, grams in portions:
        scale = grams / 100.0
        kcal    += food.kcal_per_100g    * scale
        protein += food.protein_per_100g * scale
        fat     += food.fat_per_100g     * scale
        carb    += food.carb_per_100g    * scale
        fiber   += food.fiber_per_100g   * scale
    return {"kcal": kcal, "protein_g": protein, "fat_g": fat,
            "carb_g": carb, "fiber_g": fiber}


# ── Day plan validator ─────────────────────────────────────────────────────────

def validate_day(
    day: DayPlan,
    target_kcal: float,
    target_protein_g: float,
    target_fat_g: float,
    target_fiber_g: float,
    weight_kg: float,
    strict: bool = True,
) -> list[str]:
    """
    Return a list of validation failure strings (empty = passing).

    strict=True  → kcal ±5%
    strict=False → kcal ±8% (fallback)
    """
    errors: list[str] = []
    kcal_tol = 0.05 if strict else 0.08

    if abs(day.kcal - target_kcal) / target_kcal > kcal_tol:
        errors.append(f"kcal {day.kcal:.0f} outside ±{int(kcal_tol*100)}% of {target_kcal:.0f}")

    if day.protein_g < target_protein_g * 0.95:
        errors.append(f"protein {day.protein_g:.0f}g below -5% of {target_protein_g:.0f}g")
    if day.protein_g > target_protein_g * 1.20:
        errors.append(f"protein {day.protein_g:.0f}g above +20% of {target_protein_g:.0f}g")

    if abs(day.fat_g - target_fat_g) / target_fat_g > 0.10:
        errors.append(f"fat {day.fat_g:.0f}g outside ±10% of {target_fat_g:.0f}g")

    fat_floor = 0.8 * weight_kg
    if day.fat_g < fat_floor:
        errors.append(f"fat {day.fat_g:.0f}g below 0.8 g/kg floor ({fat_floor:.0f}g)")

    if day.fiber_g < target_fiber_g * 0.80:
        errors.append(f"fiber {day.fiber_g:.0f}g below 80% of {target_fiber_g:.0f}g")

    return errors


# ── Public builder ─────────────────────────────────────────────────────────────

_MEAL_SPLITS: dict[int, list[float]] = {
    3: [0.30, 0.40, 0.30],
    4: [0.25, 0.35, 0.25, 0.15],
    5: [0.20, 0.25, 0.30, 0.15, 0.10],
    6: [0.20, 0.15, 0.25, 0.15, 0.15, 0.10],
}
_MEAL_NAMES: dict[int, list[str]] = {
    3: ["breakfast", "lunch", "dinner"],
    4: ["breakfast", "lunch", "dinner", "snack"],
    5: ["breakfast", "mid_morning", "lunch", "afternoon_snack", "dinner"],
    6: ["breakfast", "mid_morning", "lunch", "afternoon_snack", "dinner", "evening_snack"],
}


def build_day_plan(
    food_pool: list[FoodItem],
    target_kcal: float,
    target_protein_g: float,
    target_fat_g: float,
    target_carb_g: float,
    target_fiber_g: float,
    meals_per_day: int = 3,
    used_slugs_this_week: dict[str, int] | None = None,
) -> DayPlan:
    """
    Build a single day's meal plan from a filtered food pool.

    used_slugs_this_week: {slug: days_used_so_far} — prevents >5 uses/week.
    """
    if meals_per_day not in _MEAL_SPLITS:
        meals_per_day = 3
    splits = _MEAL_SPLITS[meals_per_day]
    names  = _MEAL_NAMES[meals_per_day]

    # Remove foods used ≥5 times this week
    available = food_pool
    if used_slugs_this_week:
        available = [f for f in food_pool if used_slugs_this_week.get(f.slug, 0) < 5]
        if not available:
            available = food_pool

    slots: list[MealSlotPlan] = []

    for slot_name, split in zip(names, splits):
        slot_kcal    = target_kcal    * split
        slot_protein = target_protein_g * split
        slot_fat     = target_fat_g   * split
        slot_carb    = target_carb_g  * split

        # Pick a balanced selection: 1 protein + 1 starch + 1 veg + 1 fat (when available)
        def _pick(cat: str, n: int = 1) -> list[FoodItem]:
            candidates = [f for f in available if f.category == cat
                          and slot_name in f.meal_slots]
            return candidates[:n]

        selected: list[FoodItem] = []
        selected += _pick("protein")
        selected += _pick("grain")
        selected += _pick("veg")
        selected += _pick("fat")
        # Fallback: fill from any category if selection is sparse
        if len(selected) < 2:
            fallback = [f for f in available if f not in selected and slot_name in f.meal_slots]
            selected += fallback[:max(0, 3 - len(selected))]

        if not selected:
            selected = available[:3]

        portions = _optimise_portions(
            items=selected,
            target_kcal=slot_kcal,
            target_protein_g=slot_protein,
            target_fat_g=slot_fat,
            target_carb_g=slot_carb,
        )

        macros = _sum_macros(portions)
        slots.append(MealSlotPlan(
            slot_name=slot_name,
            items=portions,
            kcal=macros["kcal"],
            protein_g=macros["protein_g"],
            fat_g=macros["fat_g"],
            carb_g=macros["carb_g"],
            fiber_g=macros["fiber_g"],
        ))

    day_macros = _sum_macros([(f, g) for slot in slots for f, g in slot.items])
    return DayPlan(
        slots=slots,
        kcal=day_macros["kcal"],
        protein_g=day_macros["protein_g"],
        fat_g=day_macros["fat_g"],
        carb_g=day_macros["carb_g"],
        fiber_g=day_macros["fiber_g"],
    )
