"""Product: the catalog is halal-only; no garbage diet tags."""
from app.domain.nutrition.food_db import get_food_db

_VALID_DIET_TAGS = {
    "omnivore", "vegetarian", "vegan", "pescatarian", "keto", "gluten_free", "balanced",
}


def test_catalog_contains_no_pork_or_other_haram():
    names = [f.name.lower() for f in get_food_db()]
    joined = " ".join(names)
    for bad in ("pork", "bacon", "ham ", "lard", "gelatin"):
        assert bad not in joined, f"non-halal item present: {bad!r}"


def test_no_garbage_diet_tags():
    for f in get_food_db():
        for t in f.diet_tags:
            assert t in _VALID_DIET_TAGS, f"{f.slug} has junk diet tag {t!r}"
