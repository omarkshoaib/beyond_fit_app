"""Check-in extraction matches on exercise_id, so the lift catalog must carry ids."""
from app.bot import _build_lift_catalog
from app.generator import WorkoutGenerator
from app.models import ClientProfile


def test_lift_catalog_entries_lead_with_real_exercise_ids():
    wk = WorkoutGenerator().generate(ClientProfile(
        client_id="t", avatar="gen_pop", training_days=4,
        experience_level="intermediate", available_equipment=["full_gym"],
    ))
    catalog = _build_lift_catalog(wk)
    assert catalog, "catalog should not be empty"
    valid_ids = {s.exercise_id for d in wk.days for s in d.slots}
    for entry in catalog:
        head = entry.split(" ", 1)[0]
        assert head in valid_ids, f"catalog entry {entry!r} must lead with a real exercise_id"
