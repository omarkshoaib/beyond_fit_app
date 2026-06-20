# SP-B1 — Ability-Appropriate Exercise Selection — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give each client the difficulty-appropriate exercise variant from week 1 — a beginner who can't do a pull-up gets the assisted pull-up / pulldown, an advanced client gets the barbell mains — driven by a `difficulty_tier` on every exercise, 6 progression ladders, and a per-family intake ability survey.

**Architecture:** A pure `app/domain/workout/ability.py` module holds the ladders + the ability/rung logic, unit-tested in isolation. `difficulty_tier` is attached to every exercise at load time from a central `DIFFICULTY_TIERS` map + a `_default_tier` rule (barbell→4 safety backstop). `ClientProfile.exercise_ability` (new Alembic 0021 column, NULL-safe) is set by a 6-question intake survey. `_select_for_slot` gains a ladder-pick for anchor-family slots (ability governs; never above ability; floor = lowest rung) and a difficulty ceiling for the rest that is **never** dropped in fallback. Check-in guards bodyweight mains.

**Tech Stack:** Python 3.12, SQLModel/SQLite, Alembic, python-telegram-bot, pytest. Tests use `tests/conftest.py` (`make_callback_update`, `make_text_update`, `make_context`).

**Spec:** `docs/superpowers/specs/2026-06-20-spb1-ability-regressions-design.md`

---

## File structure

- **Modify** `app/models.py` — `Exercise.difficulty_tier: int = 2`; `ClientProfile.exercise_ability` JSON column.
- **Modify** `app/exercise_db.py` — add `bw_incline_pike_push_up`; add `DIFFICULTY_TIERS` map + `_default_tier`; attach `difficulty_tier` in `get_exercise_db`.
- **Create** `app/domain/workout/ability.py` — `FAMILIES`, `LADDERS`, `client_ability()`, `ladder_rung()`, `global_ability()`.
- **Create** `alembic/versions/0021_client_exercise_ability.py`.
- **Modify** `app/generator.py` — `_filter_exercises` gains `max_difficulty`; `_select_for_slot` ladder-pick + ceiling-never-dropped.
- **Modify** `app/bot.py` — `ASK_ABILITY` survey + back-nav wiring + persistence; bodyweight-main check-in guard.
- **Create** tests: `test_ability_module.py`, `test_difficulty_tiers.py`, `test_ability_intake.py`, `test_ability_selection.py`, `test_bodyweight_main_checkin.py`.
- **Modify** `CLAUDE.md`, `CHANGELOG.md`.

**Task order:** 1 (data: tiers + ladders + new exercise) → 2 (ability module) → 3 (column+migration) → 4 (survey intake) → 5 (selection reshape) → 6 (check-in guard) → 7 (docs).

---

## Task 1: `difficulty_tier` on all 179 + the new bodyweight rung (C1, C6)

**Files:** Modify `app/models.py`, `app/exercise_db.py`; Test `tests/test_difficulty_tiers.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_difficulty_tiers.py
"""Every exercise carries a safe difficulty_tier (SP-B1 C1)."""
from app.exercise_db import get_exercise_db

ANCHORS = {  # from spec Appendix A — fixed tiers
    "bw_air_squat": 2, "db_goblet_squat": 2, "smith_back_squat": 3,
    "bb_back_squat_highbar": 4, "bb_back_squat_lowbar": 5,
    "bw_glute_bridge": 1, "cable_pull_through": 2, "db_romanian_deadlift": 3,
    "bb_romanian_deadlift": 4, "bb_deadlift_conventional": 4, "bb_deficit_deadlift": 5,
    "bw_knee_push_up": 1, "machine_chest_press": 2, "bw_push_up": 3,
    "db_flat_bench_press": 3, "bb_bench_press": 4, "bw_weighted_dip": 5,
    "bw_incline_pike_push_up": 2, "smith_shoulder_press": 2, "bw_pike_push_up": 3,
    "db_seated_shoulder_press": 3, "bb_overhead_press": 4, "bb_push_press": 5,
    "bw_inverted_row_bar": 2, "db_single_arm_row": 3, "db_chest_supported_row": 3,
    "bb_bent_over_row_pronated": 4, "bb_pendlay_row": 4, "bw_inverted_row_feet_elevated": 5,
    "machine_assisted_pull_up": 1, "cable_wide_grip_lat_pulldown": 2,
    "cable_neutral_grip_lat_pulldown": 3, "bw_pull_up_pronated": 4, "bw_weighted_pull_up": 5,
}
ISOLATION_OVERRIDES = {"bw_nordic_curl": 5, "bw_sissy_squat": 4, "bw_l_sit": 4, "bw_toes_to_bar": 3}

def test_every_exercise_is_tiered_1_to_5():
    for e in get_exercise_db():
        assert e["difficulty_tier"] in (1, 2, 3, 4, 5), f"{e['exercise_id']} tier={e.get('difficulty_tier')}"

def test_anchor_tiers_match_appendix_a():
    db = {e["exercise_id"]: e for e in get_exercise_db()}
    for ex_id, tier in ANCHORS.items():
        assert ex_id in db, f"{ex_id} missing"
        assert db[ex_id]["difficulty_tier"] == tier, f"{ex_id} expected {tier}, got {db[ex_id]['difficulty_tier']}"

def test_every_barbell_compound_is_tier_4_or_5_safety():
    # SAFETY BACKSTOP: a beginner must never be handed a heavy barbell lift.
    for e in get_exercise_db():
        if "barbell" in e["equipment_required"] and e["movement_pattern"] != "isolation":
            assert e["difficulty_tier"] >= 4, f"{e['exercise_id']} barbell but tier {e['difficulty_tier']}"

def test_known_hard_bodyweight_moves_are_tier_4_plus():
    db = {e["exercise_id"]: e for e in get_exercise_db()}
    for ex_id in ("bw_pull_up_pronated", "bw_weighted_pull_up", "bw_weighted_dip", "bw_deficit_push_up"):
        if ex_id in db:
            assert db[ex_id]["difficulty_tier"] >= 4, f"{ex_id} tier {db[ex_id]['difficulty_tier']}"

def test_isolation_default_two_with_overrides():
    db = {e["exercise_id"]: e for e in get_exercise_db()}
    for e in get_exercise_db():
        if e["movement_pattern"] == "isolation":
            ov = ISOLATION_OVERRIDES.get(e["exercise_id"])
            assert e["difficulty_tier"] == (ov if ov else 2), f"{e['exercise_id']}"

def test_new_incline_pike_exists():
    db = {e["exercise_id"]: e for e in get_exercise_db()}
    assert "bw_incline_pike_push_up" in db
    e = db["bw_incline_pike_push_up"]
    assert e["movement_pattern"] == "vertical_push" and e["equipment_required"] == ["bodyweight"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_difficulty_tiers.py -v`
Expected: FAIL — `KeyError: 'difficulty_tier'` / `bw_incline_pike_push_up missing`.

- [ ] **Step 3: Add the new exercise + the model field**

In `app/exercise_db.py`, append to `EXPANDED_EXERCISES_DATA` (before the closing `]`):

```python
    {"exercise_id": "bw_incline_pike_push_up", "name": "Incline (Hands-Elevated) Pike Push-Up",
     "movement_pattern": "vertical_push", "primary_muscle": "front_delts",
     "secondary_muscles": ["triceps", "chest", "core"], "fatigue_cost": 1,
     "equipment_required": ["bodyweight"], "avatar_tags": ["gen_pop"],
     "biomechanical_focus": "mid_range"},
```

In `app/models.py`, add to the `Exercise` model a defaulted field (default keeps partial states valid; the loader fills the real value):

```python
    difficulty_tier: int = 2
```

- [ ] **Step 4: Add `DIFFICULTY_TIERS` + `_default_tier` + attach in `get_exercise_db`**

In `app/exercise_db.py`, ABOVE `def get_exercise_db`, add the explicit map (anchors from
Appendix A + isolation/lunge overrides + the bodyweight-skill exceptions) and the rule. You
must **enumerate every lunge id and every bodyweight compound id** by reading the file and
assign per the rubric — the tests (`barbell>=4`, `isolation rule`, `known-hard bodyweight`)
will fail if you miss a dangerous one.

```python
# SP-B1: skill+strength difficulty (NOT fatigue). Explicit tiers for the 6 ladder anchors,
# the isolation/lunge overrides, and the bodyweight-skill exceptions. Everything else falls
# to _default_tier (whose barbell->4 rule is the beginner-safety backstop).
DIFFICULTY_TIERS: dict[str, int] = {
    # squat ladder
    "bw_air_squat": 2, "db_goblet_squat": 2, "smith_back_squat": 3,
    "bb_back_squat_highbar": 4, "bb_back_squat_lowbar": 5,
    # hinge ladder
    "bw_glute_bridge": 1, "cable_pull_through": 2, "db_romanian_deadlift": 3,
    "bb_romanian_deadlift": 4, "bb_deadlift_conventional": 4, "bb_deficit_deadlift": 5,
    # horizontal_push ladder
    "bw_knee_push_up": 1, "machine_chest_press": 2, "bw_push_up": 3,
    "db_flat_bench_press": 3, "bb_bench_press": 4, "bw_weighted_dip": 5,
    # vertical_push ladder
    "bw_incline_pike_push_up": 2, "smith_shoulder_press": 2, "bw_pike_push_up": 3,
    "db_seated_shoulder_press": 3, "bb_overhead_press": 4, "bb_push_press": 5,
    # horizontal_pull ladder
    "bw_inverted_row_bar": 2, "db_single_arm_row": 3, "db_chest_supported_row": 3,
    "bb_bent_over_row_pronated": 4, "bb_pendlay_row": 4, "bw_inverted_row_feet_elevated": 5,
    # vertical_pull ladder
    "machine_assisted_pull_up": 1, "cable_wide_grip_lat_pulldown": 2,
    "cable_neutral_grip_lat_pulldown": 3, "bw_pull_up_pronated": 4, "bw_weighted_pull_up": 5,
    # isolation overrides (rest default to 2)
    "bw_nordic_curl": 5, "bw_sissy_squat": 4, "bw_l_sit": 4, "bw_toes_to_bar": 3,
    # --- IMPLEMENTER: enumerate from exercise_db.py and add explicit tiers for: ---
    # (a) every lunge variant whose name contains bulgarian/cossack/single-leg/lateral -> 3
    # (b) every bodyweight compound harder than its ladder anchor: e.g. bw_chin_up_supinated -> 4,
    #     bw_weighted_chin_up -> 5, bw_dip -> 4, bw_deficit_push_up -> 5, bw_deficit_push_up_bench -> 3,
    #     bw_archer_push_up -> 5 (use the real ids present in the file; rubric in the spec Appx C)
}

_LUNGE_HARDER = ("bulgarian", "cossack", "single", "lateral", "skater")

def _default_tier(e: dict) -> int:
    """Backstop tier for any exercise not in DIFFICULTY_TIERS."""
    pat = e["movement_pattern"]
    if pat == "isolation":
        return 2
    if pat == "lunge":
        name = e["name"].lower()
        return 3 if any(k in name for k in _LUNGE_HARDER) else 2
    # compounds: a barbell variant ALWAYS requires proficiency -> >=4 (beginner safety)
    if "barbell" in e["equipment_required"]:
        return 4
    if e["equipment_required"] == ["bodyweight"]:
        return 3   # generic bodyweight compound (skill outliers are in DIFFICULTY_TIERS)
    return 2       # machine / smith / dumbbell / cable guided compound
```

Then change `get_exercise_db` to attach the tier (idempotent):

```python
def get_exercise_db() -> List[Dict[str, Any]]:
    for e in EXPANDED_EXERCISES_DATA:
        e["difficulty_tier"] = DIFFICULTY_TIERS.get(e["exercise_id"]) or _default_tier(e)
    return EXPANDED_EXERCISES_DATA
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_difficulty_tiers.py -v`
Expected: PASS (6 tests). If `test_every_barbell_compound...` or `test_known_hard_bodyweight...`
fails, you missed a dangerous id — add it to `DIFFICULTY_TIERS` (do NOT weaken the test).

- [ ] **Step 6: Run the full suite**

Run: `pytest -q`
Expected: green. (`Exercise(**ex)` at `generator.py:74` now receives `difficulty_tier`; the
model field accepts it.)

- [ ] **Step 7: Commit**

```bash
git add app/models.py app/exercise_db.py tests/test_difficulty_tiers.py
git commit -m "feat(exercise-db): difficulty_tier on all exercises + incline pike rung; barbell->=4 safety backstop (SP-B1 C1/C6)"
```

---

## Task 2: Ability module — ladders + rung logic (C2, selection core)

**Files:** Create `app/domain/workout/ability.py`; Test `tests/test_ability_module.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ability_module.py
from app.domain.workout import ability as ab

def test_families_and_ladders_present():
    assert set(ab.FAMILIES) == {"squat", "hinge", "horizontal_push", "vertical_push",
                                 "horizontal_pull", "vertical_pull"}
    for fam in ab.FAMILIES:
        assert ab.LADDERS[fam], f"{fam} ladder empty"

def test_ladders_are_nondecreasing_in_tier_and_ids_exist():
    from app.exercise_db import get_exercise_db
    db = {e["exercise_id"]: e for e in get_exercise_db()}
    for fam, rungs in ab.LADDERS.items():
        tiers = []
        for ex_id in rungs:
            assert ex_id in db, f"{fam}: {ex_id} not in DB"
            tiers.append(db[ex_id]["difficulty_tier"])
        assert tiers == sorted(tiers), f"{fam} ladder not ascending: {tiers}"

def test_global_ability_from_experience():
    assert ab.global_ability("beginner") == 2
    assert ab.global_ability("intermediate") == 3
    assert ab.global_ability("advanced") == 4

def test_client_ability_coerces_none_to_experience_default():
    # NULL exercise_ability -> experience default; present value overrides per family
    assert ab.client_ability("beginner", None, "squat") == 2
    assert ab.client_ability("advanced", {}, "squat") == 4
    assert ab.client_ability("beginner", {"squat": 4}, "squat") == 4
    assert ab.client_ability("beginner", {"squat": 4}, "hinge") == 2  # other family falls back

def test_ladder_rung_picks_highest_at_or_below_ability_equipment_valid():
    # ability 3, full equipment -> highest squat rung tier<=3 = smith_back_squat(3)
    assert ab.ladder_rung("squat", 3, ["full_gym"]) == "smith_back_squat"
    # ability 5, full -> top rung
    assert ab.ladder_rung("squat", 5, ["full_gym"]) == "bb_back_squat_lowbar"
    # bodyweight only, ability 3 -> only bw_air_squat(2) is equipment-valid
    assert ab.ladder_rung("squat", 3, ["bodyweight"]) == "bw_air_squat"

def test_ladder_rung_floor_when_ability_below_lowest():
    # vertical_pull lowest rung is machine_assisted_pull_up(1); ability 1 picks it
    assert ab.ladder_rung("vertical_pull", 1, ["full_gym"]) == "machine_assisted_pull_up"
    # ability below lowest equipment-valid rung -> floor to the lowest equipment-valid rung,
    # never None when SOME rung is valid
    assert ab.ladder_rung("squat", 1, ["bodyweight"]) == "bw_air_squat"  # air squat is t2 > 1 -> floor

def test_ladder_rung_none_when_no_equipment_valid_rung():
    # vertical_pull rungs all need pull_up_bar/cable; a no-equipment client -> None (slot skips)
    assert ab.ladder_rung("vertical_pull", 5, ["bodyweight"]) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ability_module.py -v`
Expected: FAIL — `ModuleNotFoundError: app.domain.workout.ability`.

- [ ] **Step 3: Create the module**

```python
# app/domain/workout/ability.py
"""Ability tiers, the 6 difficulty ladders, and rung selection (SP-B1).

Pure logic. difficulty_tier lives on the exercise dicts (see exercise_db.get_exercise_db);
this module orders the anchor variants per family and picks the client's rung.
"""
from __future__ import annotations

FAMILIES = ["squat", "hinge", "horizontal_push", "vertical_push",
            "horizontal_pull", "vertical_pull"]

# Ordered ascending by difficulty_tier (spec Appendix A). Keyed lookups use the exercise's
# own difficulty_tier, so list order only breaks within-tier ties (lowest index = canonical).
LADDERS: dict[str, list[str]] = {
    "squat": ["bw_air_squat", "db_goblet_squat", "smith_back_squat",
              "bb_back_squat_highbar", "bb_back_squat_lowbar"],
    "hinge": ["bw_glute_bridge", "cable_pull_through", "db_romanian_deadlift",
              "bb_romanian_deadlift", "bb_deadlift_conventional", "bb_deficit_deadlift"],
    "horizontal_push": ["bw_knee_push_up", "machine_chest_press", "bw_push_up",
                        "db_flat_bench_press", "bb_bench_press", "bw_weighted_dip"],
    "vertical_push": ["bw_incline_pike_push_up", "smith_shoulder_press", "bw_pike_push_up",
                      "db_seated_shoulder_press", "bb_overhead_press", "bb_push_press"],
    "horizontal_pull": ["bw_inverted_row_bar", "db_single_arm_row", "db_chest_supported_row",
                        "bb_bent_over_row_pronated", "bb_pendlay_row", "bw_inverted_row_feet_elevated"],
    "vertical_pull": ["machine_assisted_pull_up", "cable_wide_grip_lat_pulldown",
                      "cable_neutral_grip_lat_pulldown", "bw_pull_up_pronated", "bw_weighted_pull_up"],
}

_EXPERIENCE_DEFAULT = {"beginner": 2, "intermediate": 3, "advanced": 4}


def global_ability(experience_level: str) -> int:
    """Coarse ability for non-anchor (isolation/lunge) gating."""
    return _EXPERIENCE_DEFAULT.get(experience_level, 2)


def client_ability(experience_level: str, exercise_ability: "dict | None", family: str) -> int:
    """Per-family ability. NULL/missing family value -> experience default (never throws)."""
    if exercise_ability and family in exercise_ability and exercise_ability[family] is not None:
        return int(exercise_ability[family])
    return global_ability(experience_level)


def _equipment_ok(required: "list[str]", available: "list[str] | None") -> bool:
    avail = set(available or ["full_gym"])
    return "full_gym" in avail or all(tok in avail for tok in required)


def ladder_rung(family: str, ability: int, available_equipment: "list[str] | None"):
    """The exercise_id for the client's rung in `family`:
    highest difficulty_tier <= ability that is equipment-valid; tie-break by ladder index.
    FLOOR: if none <= ability is valid, the LOWEST equipment-valid rung (never above-ability
    unless forced). None only if NO rung is equipment-valid (caller skips the slot)."""
    from app.exercise_db import get_exercise_db
    db = {e["exercise_id"]: e for e in get_exercise_db()}
    rungs = LADDERS.get(family, [])
    valid = [(i, rid, db[rid]["difficulty_tier"]) for i, rid in enumerate(rungs)
             if rid in db and _equipment_ok(db[rid]["equipment_required"], available_equipment)]
    if not valid:
        return None
    at_or_below = [(i, rid, t) for (i, rid, t) in valid if t <= ability]
    if at_or_below:
        # highest tier, then lowest ladder index within that tier
        best_tier = max(t for (_, _, t) in at_or_below)
        return min((x for x in at_or_below if x[2] == best_tier), key=lambda x: x[0])[1]
    # floor: lowest tier available, then lowest index
    min_tier = min(t for (_, _, t) in valid)
    return min((x for x in valid if x[2] == min_tier), key=lambda x: x[0])[1]
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_ability_module.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add app/domain/workout/ability.py tests/test_ability_module.py
git commit -m "feat(ability): 6 difficulty ladders + per-family ability + rung pick with floor (SP-B1 C2)"
```

---

## Task 3: `exercise_ability` column + migration 0021 (C3)

**Files:** Modify `app/models.py`; Create `alembic/versions/0021_client_exercise_ability.py`; Test `tests/test_ability_module.py` (append).

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_ability_module.py
def test_clientprofile_has_exercise_ability_field():
    from app.models import ClientProfile
    p = ClientProfile(client_id="cl_x", exercise_ability={"squat": 3})
    assert p.exercise_ability == {"squat": 3}
    p2 = ClientProfile(client_id="cl_y")
    assert p2.exercise_ability is None  # NULL-safe default
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ability_module.py::test_clientprofile_has_exercise_ability_field -v`
Expected: FAIL — `TypeError: unexpected keyword 'exercise_ability'`.

- [ ] **Step 3: Add the model field**

In `app/models.py`, in `ClientProfile`, beside `coach_overrides` (the existing JSON-dict
column), add:

```python
    exercise_ability: Optional[Dict] = Field(default=None, sa_column=Column(JSON))
```

- [ ] **Step 4: Create the migration**

`alembic/versions/0021_client_exercise_ability.py`:

```python
"""Add exercise_ability JSON column to clientprofile (SP-B1 per-family ability).

Nullable — existing rows stay NULL and the selection layer coerces NULL to the
client's experience_level default, so legacy clients are unaffected until they
re-run intake.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("clientprofile", sa.Column("exercise_ability", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("clientprofile", "exercise_ability")
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_ability_module.py -v` then `pytest -q`
Expected: PASS / green. (SQLite `create_all` in tests picks up the column; the migration is
for the live Postgres.)

- [ ] **Step 6: Verify the migration applies (offline check)**

Run: `python -c "from alembic.config import Config; from alembic.script import ScriptDirectory; s=ScriptDirectory.from_config(Config('alembic.ini')); print([r.revision for r in s.walk_revisions()][:3])"`
Expected: lists `0021` ahead of `0020`.

- [ ] **Step 7: Commit**

```bash
git add app/models.py alembic/versions/0021_client_exercise_ability.py tests/test_ability_module.py
git commit -m "feat(models): ClientProfile.exercise_ability JSON + Alembic 0021 (SP-B1 C3)"
```

---

## Task 4: Ability survey at intake (C4)

**Files:** Modify `app/bot.py`; Test `tests/test_ability_intake.py`.

Inserts `ASK_ABILITY` after `ASK_EXPERIENCE`. `handle_experience` currently returns
`ASK_LIMITATIONS` (`bot.py:2086`) — it will return `ASK_ABILITY`. The 6 families are asked in
one message with an inline keyboard per family is too wide; instead ask **one family at a
time** reusing the SP-A single-question pattern, OR (simpler, chosen here) a single message
that cycles families via callback. To keep it bounded, use a **per-family sequence** stored in
`context.user_data["ability_idx"]`, each family a 3-button question + a Skip-all.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ability_intake.py
import pytest
from unittest.mock import AsyncMock
from tests.conftest import make_callback_update, make_context


@pytest.fixture
def mock_bot():
    return AsyncMock()


@pytest.mark.asyncio
async def test_ability_level_maps_and_advances(mock_bot):
    from app import bot
    ctx = make_context(mock_bot, {"experience_level": "beginner", "ability_idx": 0, "exercise_ability": {}})
    # the "I can do the standard version" button is abil:2 -> ability 3
    upd = make_callback_update(mock_bot, data="abil:2")
    nxt = await bot.handle_ability(upd, ctx)
    assert ctx.user_data["exercise_ability"]["squat"] == 3
    assert ctx.user_data["ability_idx"] == 1
    assert nxt == bot.ASK_ABILITY  # still cycling families


@pytest.mark.asyncio
async def test_ability_skip_defaults_from_experience(mock_bot):
    from app import bot
    ctx = make_context(mock_bot, {"experience_level": "advanced", "ability_idx": 0, "exercise_ability": {}})
    nxt = await bot.handle_ability(make_callback_update(mock_bot, data="abil_skip"), ctx)
    # skip-all -> every family defaulted from experience (advanced -> 4) and advance to limitations
    assert all(ctx.user_data["exercise_ability"][f] == 4 for f in bot._ABILITY_FAMILIES)
    assert nxt == bot.ASK_LIMITATIONS


@pytest.mark.asyncio
async def test_ability_last_family_advances_to_limitations(mock_bot):
    from app import bot
    ea = {f: 2 for f in bot._ABILITY_FAMILIES[:-1]}
    ctx = make_context(mock_bot, {"experience_level": "beginner",
                                  "ability_idx": len(bot._ABILITY_FAMILIES) - 1, "exercise_ability": ea})
    nxt = await bot.handle_ability(make_callback_update(mock_bot, data="abil:2"), ctx)
    assert nxt == bot.ASK_LIMITATIONS
    assert len(ctx.user_data["exercise_ability"]) == len(bot._ABILITY_FAMILIES)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ability_intake.py -v`
Expected: FAIL — `AttributeError: ... 'handle_ability'`.

- [ ] **Step 3: Add the state constant + families + level map**

In `app/bot.py`, after the SP-A equipment states (near line 169):

```python
ASK_ABILITY = "ASK_ABILITY"
_ABILITY_FAMILIES = ["squat", "hinge", "horizontal_push", "vertical_push",
                     "horizontal_pull", "vertical_pull"]
_ABILITY_FAMILY_PROMPT = {
    "squat": "your SQUAT (bodyweight squat → barbell back squat)",
    "hinge": "your HINGE / DEADLIFT (glute bridge → barbell deadlift)",
    "horizontal_push": "your PUSH (push-ups → bench press)",
    "vertical_push": "your OVERHEAD PRESS (pike push-up → barbell OHP)",
    "horizontal_pull": "your ROW (inverted row → barbell row)",
    "vertical_pull": "your PULL-UP (assisted → strict/weighted pull-up)",
}
_ABILITY_LEVEL = {"1": 2, "2": 3, "3": 4}  # button value -> ability tier (2/3/4)
```

- [ ] **Step 4: Add keyboards + handlers**

```python
def _ability_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌱 New / can't yet", callback_data="abil:1")],
        [InlineKeyboardButton("💪 I can do the standard version", callback_data="abil:2")],
        [InlineKeyboardButton("🏋️ Strong — barbell/loaded", callback_data="abil:3")],
        [InlineKeyboardButton("⏭️ Skip — use my experience level", callback_data="abil_skip")],
    ])


async def _prompt_ability(send, idx: int) -> None:
    fam = _ABILITY_FAMILIES[idx]
    await send(
        f"Quick ability check ({idx + 1}/6) — how's {_ABILITY_FAMILY_PROMPT[fam]}?",
        reply_markup=_with_back(_ability_keyboard(), ASK_ABILITY),
    )


async def handle_ability(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from app.domain.workout.ability import global_ability
    query = update.callback_query
    await query.answer()
    context.user_data.setdefault("exercise_ability", {})
    idx = context.user_data.get("ability_idx", 0)

    if query.data == "abil_skip":
        default = global_ability(context.user_data.get("experience_level", "beginner"))
        for fam in _ABILITY_FAMILIES:
            context.user_data["exercise_ability"].setdefault(fam, default)
        await _prompt_limitations(query.edit_message_text, context)
        return ASK_LIMITATIONS

    level = _ABILITY_LEVEL[query.data.split(":", 1)[1]]
    context.user_data["exercise_ability"][_ABILITY_FAMILIES[idx]] = level
    idx += 1
    context.user_data["ability_idx"] = idx
    if idx >= len(_ABILITY_FAMILIES):
        await _prompt_limitations(query.edit_message_text, context)
        return ASK_LIMITATIONS
    await _prompt_ability(query.edit_message_text, idx)
    return ASK_ABILITY
```

`_prompt_limitations(send, context)` — extract the existing limitations-prompt rendering
(the message + `_build_limitations_keyboard(set())` wrapped with `_with_back(..., ASK_LIMITATIONS)`)
into a small helper so both `handle_ability` and the back-render can call it. If
`handle_experience` already inlines that prompt, move it into `_prompt_limitations` and call it.

- [ ] **Step 5: Reroute `handle_experience` to the ability step**

In `handle_experience` (`bot.py:~2077`), replace its limitations prompt + `return ASK_LIMITATIONS`
with seeding the ability cycle and prompting the first family:

```python
    context.user_data["ability_idx"] = 0
    context.user_data["exercise_ability"] = {}
    await _prompt_ability(query.edit_message_text, 0)
    return ASK_ABILITY
```

- [ ] **Step 6: Wire back-nav + state registration + persistence**

(a) `_intake_predecessor` (`bot.py:2164-2190`): add `if leaving == ASK_ABILITY: return ASK_EXPERIENCE`,
and change the `ASK_LIMITATIONS` branch to `return ASK_ABILITY`.
(b) `_render_intake_step` (`bot.py:2193-2232`): add a branch
`if state == ASK_ABILITY: await _prompt_ability(query.edit_message_text, context.user_data.get("ability_idx", 0)); return ASK_ABILITY`.
(c) `_intake_states` (`bot.py:5531-5583`): register
`ASK_ABILITY: [CallbackQueryHandler(handle_intake_back, pattern=r"^intake_back:"), CallbackQueryHandler(handle_ability, pattern=r"^(abil:|abil_skip)")]`.
(d) `handle_email` persistence (both create + update branches, like SP-A's `available_equipment`):
on create pass `exercise_ability=context.user_data.get('exercise_ability')`; on update set
`if context.user_data.get('exercise_ability'): profile.exercise_ability = context.user_data['exercise_ability']`.

- [ ] **Step 7: Run tests**

Run: `pytest tests/test_ability_intake.py -v` then `pytest -q`
Expected: PASS / green. (If a prior intake test asserted `handle_experience` returns
`ASK_LIMITATIONS`, update it to `ASK_ABILITY`.)

- [ ] **Step 8: Commit**

```bash
git add app/bot.py tests/test_ability_intake.py
git commit -m "feat(bot): 6-family ability survey at intake, defaults from experience, back-nav wired (SP-B1 C4)"
```

---

## Task 5: Ability-appropriate selection (C5)

**Files:** Modify `app/generator.py`; Test `tests/test_ability_selection.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ability_selection.py
"""SP-B1 C5 headline guarantee: no exercise above the client's family ability."""
from app.generator import WorkoutGenerator
from app.exercise_db import get_exercise_db
from app.models import ClientProfile
from app.domain.workout.ability import LADDERS, client_ability

_DB = {e["exercise_id"]: e for e in get_exercise_db()}
_FAM_OF = {ex_id: fam for fam, rungs in LADDERS.items() for ex_id in rungs}

def _gen(**kw):
    base = dict(client_id="cl_t", avatar="gen_pop", training_days=4, limitations=[],
                available_equipment=["full_gym"])
    base.update(kw)
    return WorkoutGenerator().generate(ClientProfile(**base))

def test_beginner_never_gets_above_ability_in_anchor_families():
    client = ClientProfile(client_id="cl_b", avatar="gen_pop", training_days=4, limitations=[],
                           available_equipment=["full_gym"], experience_level="beginner",
                           exercise_ability={f: 2 for f in LADDERS})
    week = WorkoutGenerator().generate(client)
    for d in week.days:
        for s in d.slots:
            e = _DB.get(s.exercise_id)
            if e and e["movement_pattern"] in LADDERS:
                assert e["difficulty_tier"] <= 2, f"{s.exercise_id} t{e['difficulty_tier']} > 2"

def test_cant_pullup_client_gets_regression_not_strict_pullup():
    client = ClientProfile(client_id="cl_p", avatar="gen_pop", training_days=4, limitations=[],
                           available_equipment=["full_gym"], experience_level="beginner",
                           exercise_ability={f: 1 for f in LADDERS})
    week = WorkoutGenerator().generate(client)
    ids = [s.exercise_id for d in week.days for s in d.slots]
    assert "bw_pull_up_pronated" not in ids and "bw_weighted_pull_up" not in ids

def test_advanced_client_still_gets_barbell_mains():
    week = _gen(experience_level="advanced", exercise_ability={f: 4 for f in LADDERS})
    ids = {s.exercise_id for d in week.days for s in d.slots}
    # at least one tier-4 barbell main appears
    assert ids & {"bb_back_squat_highbar", "bb_bench_press", "bb_deadlift_conventional", "bb_overhead_press"}

def test_no_day_emptied_for_beginner():
    week = _gen(experience_level="beginner", exercise_ability={f: 2 for f in LADDERS})
    for d in week.days:
        assert len(d.slots) >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ability_selection.py -v`
Expected: FAIL — `test_beginner_never_gets_above_ability...` (today a beginner gets `bb_back_squat_highbar` t4 in a main slot).

- [ ] **Step 3: Add `max_difficulty` to `_filter_exercises`**

In `app/generator.py` `_filter_exercises`, in the kwargs-handling block (beside `max_fatigue`,
~lines 186-191), add:

```python
        if "max_difficulty" in kwargs and ex.difficulty_tier > kwargs["max_difficulty"]:
            continue
```

(`ex.difficulty_tier` exists now — Task 1 added the model field.)

- [ ] **Step 4: Ladder-pick + ceiling in `_select_for_slot`**

In `app/generator.py` `_select_for_slot`, add the ladder pick as the FIRST resolution for an
anchor-family slot, and thread `max_difficulty` through the existing fallback tiers (never
dropped). At the top of the method, after computing `pattern`/`avatars` and resolving any
injury substitution of `pattern`, insert:

```python
        from app.domain.workout.ability import LADDERS, client_ability, ladder_rung, global_ability
        # Ability gate. Per-family ceiling for anchor patterns; global scalar otherwise.
        if pattern in LADDERS:
            ability = client_ability(client.experience_level, client.exercise_ability, pattern)
            if client.avatar == "powerlifter" and is_main:   # competition mains exempt
                ability = 5
            max_diff = ability
            # Ladder pick ONLY when the pattern is not injury-banned; a banned anchor
            # pattern falls through to the existing tiers + Tier-5 injury substitution,
            # which stays difficulty-capped via max_diff below.
            if pattern not in self._banned_patterns(client):
                rung_id = ladder_rung(pattern, ability, client.available_equipment)
                if rung_id and rung_id not in used_ids:
                    ex = next((e for e in self.exercise_db if e.exercise_id == rung_id), None)
                    if ex:
                        return self._apply_override(ex, client)
        else:
            max_diff = global_ability(client.experience_level)
```

Then pass `max_difficulty=max_diff` into **every** `_filter_exercises(...)` call inside
`_select_for_slot` — Tier 1, Tier 2, Tier 3, **and the Tier-4 last-resort** (the ceiling must
NOT be dropped; only the *fatigue* bounds are dropped at Tier 4). For example Tier 1 becomes:

```python
        if pattern and muscle:
            ex = _pick(self._filter_exercises(client, avatars=avatars, pattern=pattern,
                                              primary_muscle=muscle, min_fatigue=min_fat,
                                              max_fatigue=max_fat, max_difficulty=max_diff))
            if ex:
                return self._apply_override(ex, client)
```

Apply the identical `max_difficulty=max_diff` addition to the Tier 2, Tier 3, Tier 4, **and
the Tier-5 injury-substitution** `_filter_exercises` calls (so an injured client's substitute
also stays at/under their ability). (The ladder pick already handled non-banned anchor
patterns with a floor, so the fallback mainly serves non-anchor and injury-banned slots;
keeping the ceiling on every tier closes the untiered-compound hole.)

NOTE: read the current `_select_for_slot` (around lines 307-380) to place these precisely;
preserve `used_ids`, rotation, and the injury Tier-5 substitution.

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_ability_selection.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Run the full suite**

Run: `pytest -q`
Expected: green. (Existing generator tests use default `experience_level`/no `exercise_ability`
→ `client_ability` coerces to the experience default; `intermediate`→3, so most existing
expectations hold. If a test asserted a specific tier-4 main for a default client, confirm the
default ability still admits it — `gen_pop` default `experience_level` is `beginner` in some
fixtures; update those fixtures to `intermediate`/`advanced` or set `exercise_ability` if they
expect barbell mains.)

- [ ] **Step 7: Commit**

```bash
git add app/generator.py tests/test_ability_selection.py
git commit -m "feat(generator): ability-governed ladder pick + difficulty ceiling never dropped (SP-B1 C5)"
```

---

## Task 6: Bodyweight-main check-in guard (C7)

**Files:** Modify `app/bot.py`; Test `tests/test_bodyweight_main_checkin.py`.

A bodyweight exercise now lands in a `main_compound` slot. The structured check-in
(`bot.py:2832-2848` first prompt, `handle_structured_weight` `:2971`, the pain handler's
advance) asks "top-set weight?" — wrong for a bodyweight lift (its `target_weight is None`).
Guard: for a bodyweight slot, skip the weight question and ask RPE directly.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bodyweight_main_checkin.py
import pytest
from app.bot import _checkin_slot_dicts
from app.models import WorkoutWeek, WorkoutDay, WorkoutSlot

def _week():
    loaded = WorkoutSlot(slot_order=0, slot_type="main_compound", exercise_id="bb_bench_press",
                         exercise_name="Barbell Bench Press", sets=3, reps="5", rpe=8, target_weight=100.0)
    bw = WorkoutSlot(slot_order=1, slot_type="main_compound", exercise_id="bw_air_squat",
                     exercise_name="Bodyweight Air Squat", sets=3, reps="12", rpe=7, target_weight=None)
    return WorkoutWeek(week_number=1, days=[WorkoutDay(day_name="A", slots=[loaded, bw], total_fatigue=7)])

def test_slot_dicts_flag_bodyweight():
    dicts = _checkin_slot_dicts([("A", s) for s in _week().days[0].slots])
    assert dicts[0]["bodyweight"] is False     # loaded bench
    assert dicts[1]["bodyweight"] is True       # air squat (target_weight None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_bodyweight_main_checkin.py -v`
Expected: FAIL — `ImportError: cannot import name '_checkin_slot_dicts'`.

- [ ] **Step 3: Extract a slot-dict builder that flags bodyweight**

In `app/bot.py`, replace the inline `checkin_structured_slots` list-comp (`:2834-2837`) with a
helper and use it:

```python
def _checkin_slot_dicts(main_slots) -> list[dict]:
    """Build the structured check-in slot dicts; flag bodyweight mains (no external load)."""
    return [
        {"day": d, "exercise_id": s.exercise_id, "exercise_name": s.exercise_name,
         "rpe": s.rpe, "bodyweight": s.target_weight is None}
        for d, s in main_slots
    ]
```

and at `:2834`:

```python
        context.user_data["checkin_structured_slots"] = _checkin_slot_dicts(main_slots)
```

- [ ] **Step 4: Skip the weight question for bodyweight slots**

Add a helper that prompts the right question for a slot, then use it in the three prompt sites
(first prompt `:2841-2848`, the resume prompt `:2898-2903`, and the pain handler's
advance-to-next-slot prompt):

```python
async def _prompt_checkin_slot(send, slot: dict, week_number: int = None) -> int:
    """Ask weight for a loaded slot, or RPE for a bodyweight slot. Returns the next state."""
    head = f"📋 *Week {week_number} Check-in*\n\n" if week_number is not None else ""
    if slot.get("bodyweight"):
        await send(f"{head}*{slot['exercise_name']}* ({slot['day']}) — what RPE was your top set? "
                   "(1–10)", parse_mode="Markdown")
        return CHECKIN_EX_RPE
    await send(f"{head}*{slot['exercise_name']}* ({slot['day']}) — what was your top-set weight? "
               "(kg, e.g. `100`)", parse_mode="Markdown")
    return CHECKIN_EX_WEIGHT
```

Replace the first-prompt block (`:2841-2848`) with:

```python
        first = context.user_data["checkin_structured_slots"][0]
        return await _prompt_checkin_slot(update.message.reply_text, first, week.week_number)
```

In the **pain handler** (the one that calls `_structured_advance` and then prompts the next
slot's weight + returns `CHECKIN_EX_WEIGHT` — read around `:3015-3075`), replace the next-slot
prompt with `return await _prompt_checkin_slot(<send>, next_slot)`. For a bodyweight next slot
it returns `CHECKIN_EX_RPE`, skipping the weight question. (`handle_structured_rpe` already
stores rpe and proceeds; a bodyweight slot simply has no `weight` key in its results — the
autoregulator already no-ops without `actual_weight`, so no further change is needed.)

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_bodyweight_main_checkin.py -v` then `pytest -q`
Expected: PASS / green.

- [ ] **Step 6: Commit**

```bash
git add app/bot.py tests/test_bodyweight_main_checkin.py
git commit -m "feat(bot): check-in asks RPE (not weight) for a bodyweight main; autoregulator skips it (SP-B1 C7)"
```

---

## Task 7: Docs (CLAUDE.md + CHANGELOG)

**Files:** Modify `CLAUDE.md`, `CHANGELOG.md`.

- [ ] **Step 1: Update CLAUDE.md key-design-constraints**

Add a bullet:

```markdown
- Exercise selection is **ability-aware** (SP-B1): every exercise has a `difficulty_tier`
  (1–5, skill/strength — NOT fatigue; barbell compounds are ≥4 by a safety backstop). Six
  movement families have ordered ladders (`app/domain/workout/ability.py` `LADDERS`,
  bodyweight→barbell). An intake survey sets `ClientProfile.exercise_ability` per family
  (Alembic 0021; NULL → coerced to the `experience_level` default in selection). An anchor
  compound slot picks the highest ladder rung ≤ the client's family ability that is
  equipment-valid (floor = lowest rung; never above ability except a powerlifter
  competition-main exemption); non-anchor slots are gated by a global experience scalar and
  the ceiling is never dropped in fallback. A bodyweight main collects RPE (not weight) at
  check-in. Variation auto-progression over time is **SP-B2** (deferred). See
  `docs/superpowers/specs/2026-06-20-spb1-ability-regressions-design.md`.
```

- [ ] **Step 2: Update CHANGELOG.md**

Add at the top:

```markdown
## [1.5.0] — 2026-06-20 — SP-B1: ability-appropriate exercise selection

### Added
- `difficulty_tier` on every exercise + 6 sourced difficulty ladders; a beginner who can't
  do a pull-up now gets the assisted pull-up / pulldown, an advanced client gets the barbell
  mains (C1/C2).
- `ClientProfile.exercise_ability` (Alembic 0021) set by a 6-family intake survey, defaulting
  from experience level (C3/C4).
- Ability-governed selection: no exercise exceeds the client's family ability; ceiling never
  dropped in fallback; bodyweight-main check-in guard (C5/C7).
- New `bw_incline_pike_push_up` regression rung (C6).

### Deferred
- SP-B2: auto-advancing the variant over time from check-in competence.
```

- [ ] **Step 3: Run the full suite one final time**

Run: `pytest -q`
Expected: green.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md CHANGELOG.md
git commit -m "docs: record SP-B1 ability-appropriate selection (1.5.0)"
```

---

## Definition of done

- Every exercise has a `difficulty_tier`; every barbell compound is ≥4 (tested).
- A beginner's plan contains no anchor-family exercise above tier 2; a "can't pull-up" client
  gets the assisted variant, never a strict pull-up; an advanced client still gets barbell
  mains; no day is emptied.
- The 6-family ability survey persists `exercise_ability`; skip defaults from experience;
  back-nav from `ASK_ABILITY` works; a NULL legacy row selects without error.
- A bodyweight main asks RPE (not weight) at check-in; the autoregulator leaves it untouched.
- Alembic 0021 applies; `pytest -q` green.
- **Deploy note:** like 0020, run `docker compose run --rm bot alembic upgrade head` on the
  server after deploying (the bot's `create_all` does not add columns to existing tables).
```
