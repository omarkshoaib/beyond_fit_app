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
