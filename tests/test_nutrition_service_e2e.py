"""End-to-end: NutritionService produces a full, non-degenerate 7-day plan."""
from sqlmodel import Session

from app.models import NutritionProfile
from app.services.nutrition_service import NutritionService


def _profile(client_id="cl_nut", **over):
    base = dict(
        client_id=client_id, weight_kg=80.0, height_cm=178.0, age=30, sex="male",
        goal="fat_loss", activity_level="moderately_active", meals_per_day=4,
    )
    base.update(over)
    return NutritionProfile(**base)


def test_generate_produces_full_nonzero_plan(test_engine):
    with Session(test_engine) as s:
        s.add(_profile())
        s.commit()
        plan = NutritionService(s).generate("cl_nut")

    assert plan is not None
    days = __import__("json").loads(plan.plan_json)
    assert len(days) == 7, f"expected 7 days, got {len(days)}"
    target = plan.kcal_target
    for d in days:
        assert d["kcal"] > 0, "no day may be 0 kcal"
        # Each day should land within a generous band of the target.
        assert 0.5 * target <= d["kcal"] <= 1.5 * target, f"day {d['day']} kcal {d['kcal']} off target {target}"


def test_generate_for_diabetic_still_returns_nonzero_plan(test_engine):
    """Medical condition must not collapse the pool to a 0-kcal plan."""
    with Session(test_engine) as s:
        s.add(_profile(client_id="cl_dia", medical_conditions=["type2_diabetes"]))
        s.commit()
        plan = NutritionService(s).generate("cl_dia")

    assert plan is not None
    days = __import__("json").loads(plan.plan_json)
    assert len(days) == 7
    assert all(d["kcal"] > 0 for d in days), "diabetic plan must not contain 0-kcal days"
