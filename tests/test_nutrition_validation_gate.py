import json
from sqlmodel import Session, SQLModel, create_engine
from app.models import NutritionProfile
from app.services.nutrition_service import NutritionService


def _session():
    eng = create_engine("sqlite://")
    SQLModel.metadata.create_all(eng)
    return Session(eng)


def _profile(session):
    p = NutritionProfile(
        client_id="t_val", weight_kg=80, height_cm=180, age=30, sex="male",
        goal="maintain", activity_level="moderately_active", meals_per_day=3,
    )
    session.add(p)
    session.commit()
    return p


def test_clean_plan_has_no_drift_marker(monkeypatch):
    # Monkeypatch validate_day to always pass so we test the wiring (no warnings → no
    # marker) independently of whether the real builder produces within-band macros.
    # NOTE: empirically, real maintain plans fail the ±10% fat band on most days —
    # that is a genuine builder finding flagged to the plan author (see commit message).
    s = _session()
    _profile(s)
    import app.services.nutrition_service as ns
    monkeypatch.setattr(ns, "validate_day", lambda *a, **k: [])
    plan = NutritionService(s).generate("t_val")
    assert plan is not None
    assert "[macro drift]" not in (plan.rationale or "")


def test_off_target_day_is_flagged_not_blocked(monkeypatch):
    s = _session()
    _profile(s)
    import app.services.nutrition_service as ns

    calls = {"n": 0}
    def fake_validate(*args, **kwargs):
        calls["n"] += 1
        # Day 1 consumes 2 calls (strict then lenient fallback), both fail.
        # Days 2-7 each make one strict call that passes.
        return ["protein 100g below -5% of 165g"] if calls["n"] <= 2 else []
    monkeypatch.setattr(ns, "validate_day", fake_validate)

    plan = NutritionService(s).generate("t_val")
    assert plan is not None                       # non-blocking: plan still persists
    assert "[macro drift]" in (plan.rationale or "")
    assert "Day 1" in plan.rationale


from app.domain.nutrition.meal_builder import DayPlan, validate_day as _validate_day


def test_fat_amdr_ceiling_bites_at_45pct_passes_at_30pct():
    base = dict(slots=[], kcal=2448, protein_g=144, carb_g=297, fiber_g=34)
    hot = DayPlan(fat_g=122.0, **base)   # 122*9/2448 = 45% of energy -> must flag
    errs = _validate_day(hot, 2448, 144, 76, 34, 80, strict=False)
    assert any("AMDR" in e for e in errs), f"45% fat day should flag, got {errs}"
    ok = DayPlan(fat_g=82.0, **base)     # 82*9/2448 = 30% of energy -> no fat flag
    errs = _validate_day(ok, 2448, 144, 76, 34, 80, strict=False)
    assert not any("AMDR" in e for e in errs), f"30% fat day should NOT flag, got {errs}"
    assert not any("0.8 g/kg" in e for e in errs)  # 82g well above 0.8*80=64 floor


def test_real_week_fat_flags_are_rare_not_noise():
    # Before calibration the ±10% band flagged 6/7 days (noise). After grounding on the
    # AMDR ceiling, fat flags should be the exception (genuine outliers), not the rule.
    from app.domain.nutrition.energy import (
        calculate_bmr, calculate_tdee, apply_goal_adjustment, apply_calorie_floor)
    from app.domain.nutrition.macros import calculate_macros
    from app.domain.nutrition.food_db import get_food_db
    from app.domain.nutrition.meal_builder import build_day_plan, filter_food_pool
    bmr = calculate_bmr(80, 180, 30, "male")
    tdee = calculate_tdee(bmr, "moderately_active")
    tk = apply_calorie_floor(apply_goal_adjustment(tdee, "maintain", "moderate"), bmr, 80, "male")
    m = calculate_macros(tk, 80, "maintain")
    pool = filter_food_pool(get_food_db()); used = {}
    fat_flag_days = 0
    for di in range(7):
        d = build_day_plan(pool, tk, m["protein_g"], m["fat_g"], m["carb_g"], m["fiber_g"],
                           meals_per_day=3, day_index=di, used_slugs_this_week=used)
        for slot in d.slots:
            for f, _ in slot.items:
                used[f.slug] = used.get(f.slug, 0) + 1
        errs = _validate_day(d, tk, m["protein_g"], m["fat_g"], m["fiber_g"], 80, strict=False)
        if any("AMDR" in e for e in errs):
            fat_flag_days += 1
    assert fat_flag_days <= 2, f"fat flags should be rare after calibration, got {fat_flag_days}/7"
