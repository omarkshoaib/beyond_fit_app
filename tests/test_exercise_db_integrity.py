"""Data quality: exercise DB must have unique names + ids and valid fields."""
import collections

from app.exercise_db import EXPANDED_EXERCISES_DATA as E

_VALID_AVATARS = {"powerlifter", "powerbuilder", "gen_pop"}
_VALID_FOCUS = {"lengthened_position", "shortened_position", "mid_range"}


def test_no_duplicate_names():
    dups = [n for n, c in collections.Counter(e["name"] for e in E).items() if c > 1]
    assert not dups, f"duplicate exercise names: {dups}"


def test_unique_ids():
    ids = [e["exercise_id"] for e in E]
    assert len(ids) == len(set(ids)), "duplicate exercise_ids"


def test_schema_fields_valid():
    for e in E:
        assert 1 <= e["fatigue_cost"] <= 5, f"{e['exercise_id']} bad fatigue_cost {e['fatigue_cost']}"
        assert set(e["avatar_tags"]) <= _VALID_AVATARS, f"{e['exercise_id']} bad avatar_tags"
        assert e["biomechanical_focus"] in _VALID_FOCUS, f"{e['exercise_id']} bad bio focus"
        assert e["primary_muscle"], f"{e['exercise_id']} missing primary_muscle"
