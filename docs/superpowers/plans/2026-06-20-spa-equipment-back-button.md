# SP-A — Equipment-Aware Plans + Intake Back Button — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collect each client's real equipment at intake (replacing the hardcoded
`["full_gym"]`), let them edit it, add a bodyweight floor so a no-gym client gets a
complete plan, add intake back-navigation, and guard every coach exercise-add path
against the client's equipment.

**Architecture:** Pure logic (equipment vocabulary, the floor, the validator,
alternatives, pattern reachability) lives in a new module
`app/domain/workout/equipment.py` and is unit-tested in isolation. `app/bot.py` gets
thin conversation wiring that calls that module. The exercise DB gains 5 plain
bodyweight entries. No new DB columns, no migration (`available_equipment` is an
existing JSON list column).

**Tech Stack:** Python 3.12, python-telegram-bot (ConversationHandler), SQLModel/SQLite,
pytest. Tests drive bot handlers with the existing `tests/conftest.py` helpers
(`make_callback_update`, `make_text_update`, `make_context`) and an `AsyncMock` bot.

**Spec:** `docs/superpowers/specs/2026-06-20-spa-equipment-back-button-design.md`

---

## File structure

- **Create** `app/domain/workout/equipment.py` — equipment vocabulary, presets, floor,
  `validate_equipment`, `equipment_alternatives`, `reachable_patterns`. Pure, no I/O.
- **Modify** `app/exercise_db.py` — append 5 bodyweight exercises (Task 1).
- **Modify** `app/generator.py` — treat empty `available_equipment` as `full_gym` (Task 3).
- **Modify** `app/bot.py` — equipment survey states + handlers (Task 4), `UPD_EQUIPMENT`
  (Task 5), back-navigation (Task 6), pulling-gap surfacing (Task 7), coach guard wiring
  (Task 8).
- **Create** `tests/test_bodyweight_floor.py`, `tests/test_equipment_module.py`,
  `tests/test_equipment_intake.py`, `tests/test_equipment_guard.py`.
- **Modify** `CLAUDE.md`, `CHANGELOG.md` (Task 9).

**Task order & dependencies:** 1 (floor) → 2 (vocab) → 3 (validator) are independent pure
work. 4 (survey) depends on 2. 5 (edit) depends on 4. 6 (back) depends on 4. 7 (gap)
depends on 2+4. 8 (guard) depends on 3. 9 (docs) last.

---

## Task 1: Bodyweight floor — 5 new exercises (C4)

**Files:**
- Modify: `app/exercise_db.py` (append to `EXPANDED_EXERCISES_DATA`)
- Test: `tests/test_bodyweight_floor.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bodyweight_floor.py
"""A bodyweight-only client must get a complete, non-collapsed plan (SP-A C4)."""
from app.exercise_db import get_exercise_db
from app.generator import WorkoutGenerator
from app.models import ClientProfile

NEW_IDS = {
    "bw_air_squat", "bw_reverse_lunge", "bw_single_leg_rdl",
    "bw_knee_push_up", "bw_inverted_row_bar",
}

def test_new_bodyweight_exercises_exist_and_validate():
    db = {e["exercise_id"]: e for e in get_exercise_db()}
    for ex_id in NEW_IDS:
        assert ex_id in db, f"{ex_id} missing from exercise DB"
    air = db["bw_air_squat"]
    assert air["movement_pattern"] == "squat"
    assert air["equipment_required"] == ["bodyweight"]
    # inverted row is the only bar-gated one
    assert db["bw_inverted_row_bar"]["equipment_required"] == ["pull_up_bar", "bodyweight"]

def test_bodyweight_with_bar_covers_squat_and_pull():
    client = ClientProfile(
        client_id="cl_bw_bar", avatar="gen_pop", training_days=4,
        experience_level="beginner", limitations=[],
        available_equipment=["bodyweight", "pull_up_bar"],
    )
    week = WorkoutGenerator().generate(client)
    patterns = {
        s.exercise_id: e["movement_pattern"]
        for e in get_exercise_db()
        for d in week.days for s in d.slots
        if s.exercise_id == e["exercise_id"]
    }
    present = set(patterns.values())
    assert "squat" in present, "no squat pattern for a bodyweight+bar client"
    assert "horizontal_pull" in present or "vertical_pull" in present, "no pulling"

def test_bodyweight_only_has_no_empty_day():
    client = ClientProfile(
        client_id="cl_bw_only", avatar="gen_pop", training_days=4,
        experience_level="beginner", limitations=[],
        available_equipment=["bodyweight"],
    )
    week = WorkoutGenerator().generate(client)
    for d in week.days:
        assert len(d.slots) >= 1, f"day {d.day_name} collapsed to zero slots"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_bodyweight_floor.py -v`
Expected: FAIL — `bw_air_squat missing from exercise DB`.

- [ ] **Step 3: Add the 5 exercises**

Append these dicts to the `EXPANDED_EXERCISES_DATA` list in `app/exercise_db.py` (just
before the closing `]` of the list literal). Match the existing dict style exactly.

```python
    {"exercise_id": "bw_air_squat", "name": "Bodyweight Air Squat",
     "movement_pattern": "squat", "primary_muscle": "quadriceps",
     "secondary_muscles": ["glutes", "adductors", "core"], "fatigue_cost": 2,
     "equipment_required": ["bodyweight"], "avatar_tags": ["gen_pop", "powerbuilder"],
     "biomechanical_focus": "lengthened_position"},
    {"exercise_id": "bw_reverse_lunge", "name": "Bodyweight Reverse Lunge",
     "movement_pattern": "lunge", "primary_muscle": "quadriceps",
     "secondary_muscles": ["glutes", "hamstrings", "adductors", "core"], "fatigue_cost": 3,
     "equipment_required": ["bodyweight"], "avatar_tags": ["gen_pop", "powerbuilder"],
     "biomechanical_focus": "mid_range"},
    {"exercise_id": "bw_single_leg_rdl", "name": "Bodyweight Single-Leg Romanian Deadlift",
     "movement_pattern": "hinge", "primary_muscle": "hamstrings",
     "secondary_muscles": ["glutes", "lower_back", "core"], "fatigue_cost": 2,
     "equipment_required": ["bodyweight"], "avatar_tags": ["gen_pop", "powerbuilder"],
     "biomechanical_focus": "lengthened_position"},
    {"exercise_id": "bw_knee_push_up", "name": "Knee (Modified) Push-Up",
     "movement_pattern": "horizontal_push", "primary_muscle": "chest",
     "secondary_muscles": ["triceps", "front_delts", "core"], "fatigue_cost": 1,
     "equipment_required": ["bodyweight"], "avatar_tags": ["gen_pop"],
     "biomechanical_focus": "lengthened_position"},
    {"exercise_id": "bw_inverted_row_bar", "name": "Bar Inverted Row",
     "movement_pattern": "horizontal_pull", "primary_muscle": "mid_back",
     "secondary_muscles": ["lats", "biceps", "rear_delts", "core"], "fatigue_cost": 2,
     "equipment_required": ["pull_up_bar", "bodyweight"], "avatar_tags": ["gen_pop", "powerbuilder"],
     "biomechanical_focus": "mid_range"},
```

NOTE: if `EXPANDED_EXERCISES_DATA` is built differently (e.g. a `+ [...]` concatenation),
append into the final list literal — verify the ids appear in `get_exercise_db()` after.
Do **not** add any difficulty/regression field — that is SP-B.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_bodyweight_floor.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the full suite to confirm no regressions**

Run: `pytest -q`
Expected: all green (the new exercises are additive; existing selection is unchanged for
full-gym clients).

- [ ] **Step 6: Commit**

```bash
git add app/exercise_db.py tests/test_bodyweight_floor.py
git commit -m "feat(exercise-db): bodyweight floor — air squat, reverse lunge, SL-RDL, knee push-up, bar inverted row (SP-A C4)"
```

---

## Task 2: Equipment vocabulary, presets, floor (C1 pure core)

**Files:**
- Create: `app/domain/workout/equipment.py`
- Test: `tests/test_equipment_module.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_equipment_module.py
from app.domain.workout import equipment as eq

def test_presets_map_to_tokens():
    assert eq.EQUIPMENT_PRESETS["commercial"] == ["full_gym"]
    assert eq.EQUIPMENT_PRESETS["minimal"] == ["bodyweight", "pull_up_bar"]
    assert eq.EQUIPMENT_PRESETS["bodyweight"] == ["bodyweight"]
    # home preset pre-checks a sensible set
    assert set(eq.EQUIPMENT_PRESETS["home"]) == {"dumbbells", "bench", "pull_up_bar"}

def test_checklist_excludes_bodyweight_and_full_gym():
    assert "bodyweight" not in eq.CHECKLIST_TOKENS
    assert "full_gym" not in eq.CHECKLIST_TOKENS
    # every checklist token is a real DB equipment token
    from app.exercise_db import get_exercise_db
    real = {t for e in get_exercise_db() for t in e["equipment_required"]}
    assert set(eq.CHECKLIST_TOKENS) <= real

def test_floor_never_empty():
    assert eq.floor_equipment([]) == ["bodyweight"]
    assert eq.floor_equipment(None) == ["bodyweight"]
    assert eq.floor_equipment(["dumbbells"]) == ["dumbbells"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_equipment_module.py -v`
Expected: FAIL — `ModuleNotFoundError: app.domain.workout.equipment`.

- [ ] **Step 3: Create the module (vocabulary + floor)**

```python
# app/domain/workout/equipment.py
"""Equipment vocabulary, intake presets, and the equipment floor (SP-A C1).

Pure helpers — no I/O. The 16 real equipment tokens are whatever the exercise DB
uses; ``bodyweight`` is always implicit (never a checkbox) and ``full_gym`` is the
wildcard meaning "has everything". The checklist is the remaining real tokens.
"""
from __future__ import annotations

# The 15 client-facing checklist tokens (bodyweight is implicit; full_gym is the
# wildcard preset). Grouped roughly free-weights → machines → calisthenics stations;
# the niche barbell attachments (ez_bar, trap_bar, landmine) are included so a Custom
# build can express them, but presets fold them under "Commercial gym".
CHECKLIST_TOKENS: list[str] = [
    "barbell", "squat_rack", "bench", "dumbbells", "kettlebell",
    "smith_machine", "cable_machine", "leg_press_machine",
    "leg_extension_machine", "leg_curl_machine",
    "pull_up_bar", "dip_station", "ez_bar", "trap_bar", "landmine",
]

# Preset key → the equipment list it resolves to. "home" opens the checklist
# pre-checked with this set; "custom" opens it empty (handled in the bot layer).
EQUIPMENT_PRESETS: dict[str, list[str]] = {
    "commercial": ["full_gym"],
    "home": ["dumbbells", "bench", "pull_up_bar"],
    "minimal": ["bodyweight", "pull_up_bar"],
    "bodyweight": ["bodyweight"],
}


def floor_equipment(tokens: "list[str] | None") -> list[str]:
    """Never return an empty equipment list — an empty list makes the generator
    reject every exercise and produce a zero-exercise plan. Empty/None → bodyweight."""
    return list(tokens) if tokens else ["bodyweight"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_equipment_module.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add app/domain/workout/equipment.py tests/test_equipment_module.py
git commit -m "feat(equipment): vocabulary, presets, and the no-empty floor (SP-A C1)"
```

---

## Task 3: `validate_equipment`, alternatives, reachable patterns + generator empty-guard (C6/C5 pure core)

**Files:**
- Modify: `app/domain/workout/equipment.py`
- Modify: `app/generator.py:154-160` (`_filter_exercises` equipment loop)
- Test: `tests/test_equipment_module.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_equipment_module.py
from app.models import ClientProfile, WorkoutWeek, WorkoutDay, WorkoutSlot
from app.generator import WorkoutGenerator

def _week_with(ex_id: str) -> WorkoutWeek:
    slot = WorkoutSlot(slot_order=0, slot_type="main_compound", exercise_id=ex_id,
                       exercise_name=ex_id, sets=3, reps="5", rpe=7)
    return WorkoutWeek(week_number=1, days=[WorkoutDay(day_name="A", slots=[slot], total_fatigue=3)])

def test_validate_flags_absent_equipment():
    # bb_back_squat_highbar needs barbell+squat_rack; a dumbbell-only client lacks them
    week = _week_with("bb_back_squat_highbar")
    violations = eq.validate_equipment(week, ["dumbbells"])
    assert len(violations) == 1
    assert violations[0].exercise_id == "bb_back_squat_highbar"
    assert "barbell" in violations[0].missing

def test_validate_passes_full_gym_and_valid():
    week = _week_with("bb_back_squat_highbar")
    assert eq.validate_equipment(week, ["full_gym"]) == []
    assert eq.validate_equipment(_week_with("bw_air_squat"), ["bodyweight"]) == []

def test_validate_flags_unknown_exercise():
    violations = eq.validate_equipment(_week_with("not_a_real_id"), ["full_gym"])
    assert len(violations) == 1 and violations[0].missing == ["<unknown exercise>"]

def test_alternatives_are_same_muscle_and_equipment_valid():
    alts = eq.equipment_alternatives("bb_back_squat_highbar", ["bodyweight"])
    assert any(a["exercise_id"] == "bw_air_squat" for a in alts)
    for a in alts:
        assert all(t in {"bodyweight"} for t in a["equipment_required"])

def test_reachable_patterns_no_bar_has_no_pull():
    reach = eq.reachable_patterns(["bodyweight"])
    assert "squat" in reach
    assert "horizontal_pull" not in reach and "vertical_pull" not in reach
    reach_bar = eq.reachable_patterns(["bodyweight", "pull_up_bar"])
    assert "horizontal_pull" in reach_bar or "vertical_pull" in reach_bar

def test_generator_treats_empty_equipment_as_full_gym():
    # legacy/corrupt row: empty list must NOT yield a zero-exercise plan
    client = ClientProfile(client_id="cl_empty", avatar="gen_pop", training_days=3,
                           experience_level="beginner", limitations=[], available_equipment=[])
    week = WorkoutGenerator().generate(client)
    assert sum(len(d.slots) for d in week.days) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_equipment_module.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'validate_equipment'`.

- [ ] **Step 3: Add validator, alternatives, reachable_patterns to the module**

```python
# append to app/domain/workout/equipment.py
from dataclasses import dataclass


@dataclass
class Violation:
    exercise_id: str
    exercise_name: str
    missing: list[str]  # missing equipment tokens, or ["<unknown exercise>"]


def _has_all(required: "list[str]", available: "set[str]") -> bool:
    return "full_gym" in available or all(tok in available for tok in required)


def validate_equipment(week, available_equipment: "list[str] | None") -> list[Violation]:
    """Every slot's exercise must be satisfiable by the client's equipment.
    An exercise id not in the DB is also a violation (cannot verify it)."""
    from app.exercise_db import get_exercise_db
    db = {e["exercise_id"]: e for e in get_exercise_db()}
    avail = set(available_equipment or ["full_gym"])  # empty → wildcard (legacy-safe)
    out: list[Violation] = []
    seen: set[str] = set()
    for day in week.days:
        for slot in day.slots:
            if slot.exercise_id in seen:
                continue
            seen.add(slot.exercise_id)
            ex = db.get(slot.exercise_id)
            if ex is None:
                out.append(Violation(slot.exercise_id, slot.exercise_name, ["<unknown exercise>"]))
                continue
            if not _has_all(ex["equipment_required"], avail):
                missing = [t for t in ex["equipment_required"] if t not in avail]
                out.append(Violation(slot.exercise_id, slot.exercise_name, missing))
    return out


def equipment_alternatives(exercise_id: str, available_equipment: "list[str] | None",
                           limit: int = 5) -> list[dict]:
    """Equipment-valid exercises sharing the target's primary muscle (and pattern when
    possible), deterministically sorted. Empty if the target id is unknown."""
    from app.exercise_db import get_exercise_db
    db = get_exercise_db()
    target = next((e for e in db if e["exercise_id"] == exercise_id), None)
    if target is None:
        return []
    avail = set(available_equipment or ["full_gym"])
    same_muscle = [
        e for e in db
        if e["exercise_id"] != exercise_id
        and e["primary_muscle"] == target["primary_muscle"]
        and _has_all(e["equipment_required"], avail)
    ]
    # prefer same movement pattern first, then the rest, both id-sorted (deterministic)
    same_pat = sorted((e for e in same_muscle if e["movement_pattern"] == target["movement_pattern"]),
                      key=lambda e: e["exercise_id"])
    other = sorted((e for e in same_muscle if e["movement_pattern"] != target["movement_pattern"]),
                   key=lambda e: e["exercise_id"])
    return (same_pat + other)[:limit]


def reachable_patterns(available_equipment: "list[str] | None") -> set[str]:
    """Movement patterns for which at least one exercise is equipment-valid."""
    from app.exercise_db import get_exercise_db
    avail = set(available_equipment or ["full_gym"])
    return {e["movement_pattern"] for e in get_exercise_db()
            if _has_all(e["equipment_required"], avail)}
```

- [ ] **Step 4: Add the generator empty-equipment guard**

In `app/generator.py`, the `_filter_exercises` equipment loop (around lines 154-160)
reads `client.available_equipment` directly. Make an empty list behave as `full_gym`.
Change the loop to read a normalized local first. Replace:

```python
            has_equipment = True
            for eq in ex.equipment_required:
                if eq not in client.available_equipment and "full_gym" not in client.available_equipment:
                    has_equipment = False
                    break
            if not has_equipment:
                continue
```

with:

```python
            avail = client.available_equipment or ["full_gym"]   # empty → wildcard (legacy-safe)
            has_equipment = True
            for eq in ex.equipment_required:
                if eq not in avail and "full_gym" not in avail:
                    has_equipment = False
                    break
            if not has_equipment:
                continue
```

(The local is named `avail`; the loop variable `eq` is the existing one — do not confuse
it with the `equipment` module.)

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_equipment_module.py -v`
Expected: PASS (all tests, including `test_generator_treats_empty_equipment_as_full_gym`).

- [ ] **Step 6: Run the full suite**

Run: `pytest -q`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add app/domain/workout/equipment.py app/generator.py tests/test_equipment_module.py
git commit -m "feat(equipment): validate_equipment + alternatives + reachable_patterns; generator treats empty equipment as full_gym (SP-A C3/C6)"
```

---

## Task 4: Equipment survey at intake (C1 bot wiring)

**Files:**
- Modify: `app/bot.py` (state constants ~158-164; new handlers near `handle_days`;
  persistence in `handle_email` ~2117-2146; states registration ~5209-5232)
- Test: `tests/test_equipment_intake.py`

Inserts the equipment step **between days and experience**: `handle_days` will return
`ASK_EQUIPMENT` instead of `ASK_EXPERIENCE`, and the new equipment-confirm handler will
render the experience prompt and return `ASK_EXPERIENCE`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_equipment_intake.py
"""SP-A C1: equipment survey at intake."""
import pytest
from unittest.mock import AsyncMock
from tests.conftest import make_callback_update, make_context


@pytest.fixture
def mock_bot():
    return AsyncMock()


@pytest.mark.asyncio
async def test_commercial_preset_sets_full_gym_and_advances(mock_bot):
    from app import bot
    ctx = make_context(mock_bot, {"avatar": "gen_pop", "days": 4})
    upd = make_callback_update(mock_bot, data="equip_preset:commercial")
    nxt = await bot.handle_equipment_preset(upd, ctx)
    assert ctx.user_data["available_equipment"] == ["full_gym"]
    assert nxt == bot.ASK_EXPERIENCE


@pytest.mark.asyncio
async def test_bodyweight_preset_asks_pullup(mock_bot):
    from app import bot
    ctx = make_context(mock_bot, {"avatar": "gen_pop", "days": 4})
    upd = make_callback_update(mock_bot, data="equip_preset:bodyweight")
    nxt = await bot.handle_equipment_preset(upd, ctx)
    assert nxt == bot.ASK_EQUIPMENT_PULLUP


@pytest.mark.asyncio
async def test_pullup_yes_adds_bar(mock_bot):
    from app import bot
    ctx = make_context(mock_bot, {"avatar": "gen_pop", "days": 4})
    upd = make_callback_update(mock_bot, data="equip_pullup:yes")
    nxt = await bot.handle_equipment_pullup(upd, ctx)
    assert "pull_up_bar" in ctx.user_data["available_equipment"]
    assert "bodyweight" in ctx.user_data["available_equipment"]
    assert nxt == bot.ASK_EXPERIENCE


@pytest.mark.asyncio
async def test_custom_done_with_nothing_floors_to_bodyweight(mock_bot):
    from app import bot
    ctx = make_context(mock_bot, {"avatar": "gen_pop", "days": 4, "equip_selected": set()})
    upd = make_callback_update(mock_bot, data="equip_confirm")
    nxt = await bot.handle_equipment_confirm(upd, ctx)
    assert ctx.user_data["available_equipment"] == ["bodyweight"]
    assert nxt == bot.ASK_EXPERIENCE


@pytest.mark.asyncio
async def test_custom_toggle_accumulates(mock_bot):
    from app import bot
    ctx = make_context(mock_bot, {"avatar": "gen_pop", "days": 4})
    await bot.handle_equipment_toggle(
        make_callback_update(mock_bot, data="equip_toggle_dumbbells"), ctx)
    await bot.handle_equipment_toggle(
        make_callback_update(mock_bot, data="equip_toggle_bench"), ctx)
    assert ctx.user_data["equip_selected"] == {"dumbbells", "bench"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_equipment_intake.py -v`
Expected: FAIL — `AttributeError: module 'app.bot' has no attribute 'handle_equipment_preset'`.

- [ ] **Step 3: Add the equipment state constants**

In `app/bot.py`, after line 164 (`ASK_BASE_DEADLIFT = "ASK_BASE_DEADLIFT"`), add:

```python
# Equipment survey states (SP-A C1). Strings keep them distinct from the intake ints.
ASK_EQUIPMENT = "ASK_EQUIPMENT"
ASK_EQUIPMENT_CUSTOM = "ASK_EQUIPMENT_CUSTOM"
ASK_EQUIPMENT_PULLUP = "ASK_EQUIPMENT_PULLUP"
```

- [ ] **Step 4: Add the equipment keyboards + handlers**

Add these near `_build_limitations_keyboard` / `handle_days` in `app/bot.py`. Import the
equipment module at the top of the function bodies (lazy import keeps module load cheap):

```python
def _equipment_preset_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏢 Commercial gym (everything)", callback_data="equip_preset:commercial")],
        [InlineKeyboardButton("🏠 Home gym — customize", callback_data="equip_preset:home")],
        [InlineKeyboardButton("🧰 Minimal (bodyweight + pull-up bar)", callback_data="equip_preset:minimal")],
        [InlineKeyboardButton("🧍 Bodyweight only", callback_data="equip_preset:bodyweight")],
        [InlineKeyboardButton("⚙️ Custom — pick each item", callback_data="equip_preset:custom")],
    ])


def _equipment_checklist_keyboard(selected: set) -> InlineKeyboardMarkup:
    from app.domain.workout.equipment import CHECKLIST_TOKENS
    rows = []
    for i in range(0, len(CHECKLIST_TOKENS), 2):
        row = []
        for tok in CHECKLIST_TOKENS[i:i + 2]:
            label = f"✓ {tok}" if tok in selected else tok
            row.append(InlineKeyboardButton(label, callback_data=f"equip_toggle_{tok}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("✅ Done", callback_data="equip_confirm")])
    return InlineKeyboardMarkup(rows)


def _pullup_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes", callback_data="equip_pullup:yes"),
        InlineKeyboardButton("❌ No", callback_data="equip_pullup:no"),
    ]])


async def _prompt_experience(send) -> None:
    keyboard = [
        [InlineKeyboardButton("Beginner", callback_data="beginner")],
        [InlineKeyboardButton("Intermediate", callback_data="intermediate")],
        [InlineKeyboardButton("Advanced", callback_data="advanced")],
    ]
    await send("What is your experience level?", reply_markup=InlineKeyboardMarkup(keyboard))


async def handle_equipment_preset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from app.domain.workout.equipment import EQUIPMENT_PRESETS
    query = update.callback_query
    await query.answer()
    preset = query.data.split(":", 1)[1]
    context.user_data["equip_preset"] = preset
    if preset == "commercial":
        context.user_data["available_equipment"] = list(EQUIPMENT_PRESETS["commercial"])
        await _prompt_experience(query.edit_message_text)
        return ASK_EXPERIENCE
    if preset == "minimal":
        context.user_data["available_equipment"] = list(EQUIPMENT_PRESETS["minimal"])
        await _prompt_experience(query.edit_message_text)
        return ASK_EXPERIENCE
    if preset == "bodyweight":
        await query.edit_message_text(
            "Do you have a pull-up bar? It unlocks all your back/pull training.",
            reply_markup=_pullup_keyboard(),
        )
        return ASK_EQUIPMENT_PULLUP
    # home (pre-checked) or custom (empty) → open the checklist
    selected = set(EQUIPMENT_PRESETS["home"]) if preset == "home" else set()
    # bodyweight is implicit and not a checkbox; drop it from the editable set
    selected.discard("bodyweight")
    context.user_data["equip_selected"] = selected
    await query.edit_message_text(
        "Check everything you have, then tap Done:",
        reply_markup=_equipment_checklist_keyboard(selected),
    )
    return ASK_EQUIPMENT_CUSTOM


async def handle_equipment_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tok = query.data[len("equip_toggle_"):]
    selected: set = context.user_data.get("equip_selected", set())
    if tok in selected:
        selected.discard(tok)
    else:
        selected.add(tok)
    context.user_data["equip_selected"] = selected
    await query.edit_message_reply_markup(reply_markup=_equipment_checklist_keyboard(selected))
    return ASK_EQUIPMENT_CUSTOM


async def handle_equipment_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from app.domain.workout.equipment import floor_equipment
    query = update.callback_query
    await query.answer()
    selected = sorted(context.user_data.get("equip_selected", set()))
    # bodyweight is always available; persist it alongside the picked machines.
    tokens = floor_equipment(selected + ["bodyweight"] if selected else [])
    context.user_data["available_equipment"] = tokens
    await _prompt_experience(query.edit_message_text)
    return ASK_EXPERIENCE


async def handle_equipment_pullup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    answer = query.data.split(":", 1)[1]
    if answer == "yes":
        context.user_data["available_equipment"] = ["bodyweight", "pull_up_bar"]
    else:
        context.user_data["available_equipment"] = ["bodyweight"]
        await query.edit_message_text(
            "Heads up: bodyweight-only means *no back/pull training* until you get a "
            "pull-up bar or your coach adds bands. Your coach will see this.",
            parse_mode="Markdown",
        )
    await _prompt_experience(context.bot.send_message.__self__.send_message
                             if False else query.message.reply_text)
    return ASK_EXPERIENCE
```

NOTE on the last line of `handle_equipment_pullup`: after the "No" branch edits the
message with the warning, you cannot `edit_message_text` again on the same callback to
show the experience prompt — send it as a new message via `query.message.reply_text`.
For the "yes" branch you may use `query.edit_message_text`. Simplify to:

```python
async def handle_equipment_pullup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    answer = query.data.split(":", 1)[1]
    if answer == "yes":
        context.user_data["available_equipment"] = ["bodyweight", "pull_up_bar"]
        await _prompt_experience(query.edit_message_text)
    else:
        context.user_data["available_equipment"] = ["bodyweight"]
        await query.edit_message_text(
            "Heads up: bodyweight-only means *no back/pull training* until you get a "
            "pull-up bar or your coach adds bands. Your coach will see this.",
            parse_mode="Markdown",
        )
        await _prompt_experience(query.message.reply_text)
    return ASK_EXPERIENCE
```

Use the **simplified** version.

- [ ] **Step 5: Point `handle_days` at the equipment step**

In `handle_days` (`app/bot.py:1890-1901`), replace the experience keyboard + return with
the equipment prompt. Change the body after `context.user_data['days'] = int(query.data)`
to:

```python
    await query.edit_message_text(
        "What equipment do you have access to?",
        reply_markup=_equipment_preset_keyboard(),
    )
    return ASK_EQUIPMENT
```

(The experience prompt now lives in `_prompt_experience`, reached from the equipment
handlers.)

- [ ] **Step 6: Persist `available_equipment` in `handle_email`**

In `handle_email` (`app/bot.py`), import the floor and write the surveyed value in **both**
branches.

Update branch — replace line 2123
`profile.available_equipment = profile.available_equipment or ["full_gym"]` with:

```python
                from app.domain.workout.equipment import floor_equipment
                if context.user_data.get('available_equipment'):
                    profile.available_equipment = floor_equipment(context.user_data['available_equipment'])
                else:
                    profile.available_equipment = profile.available_equipment or ["full_gym"]
```

Create branch — replace line 2138 `available_equipment=["full_gym"],` with:

```python
                available_equipment=floor_equipment(context.user_data.get('available_equipment')),
```

and add `from app.domain.workout.equipment import floor_equipment` at the top of
`handle_email` (or module level). `floor_equipment(None)` → `["bodyweight"]`, but a normal
intake always sets `available_equipment`, so the create branch gets the surveyed value.

- [ ] **Step 7: Register the equipment states**

In the `_intake_states` dict (`app/bot.py:5209-5232`), add after the `ASK_DAYS` entry:

```python
        ASK_EQUIPMENT: [CallbackQueryHandler(handle_equipment_preset, pattern=r"^equip_preset:")],
        ASK_EQUIPMENT_CUSTOM: [
            CallbackQueryHandler(handle_equipment_toggle, pattern=r"^equip_toggle_"),
            CallbackQueryHandler(handle_equipment_confirm, pattern=r"^equip_confirm$"),
        ],
        ASK_EQUIPMENT_PULLUP: [CallbackQueryHandler(handle_equipment_pullup, pattern=r"^equip_pullup:")],
```

- [ ] **Step 8: Run tests**

Run: `pytest tests/test_equipment_intake.py -v`
Expected: PASS (5 tests).

- [ ] **Step 9: Run the full suite**

Run: `pytest -q`
Expected: all green. (If a pre-existing intake test asserted `handle_days` returns
`ASK_EXPERIENCE`, update it to `ASK_EQUIPMENT` — search `tests/` for `handle_days`.)

- [ ] **Step 10: Commit**

```bash
git add app/bot.py tests/test_equipment_intake.py
git commit -m "feat(bot): equipment survey at intake — preset + checklist + pull-up question, replaces hardcoded full_gym (SP-A C1)"
```

---

## Task 5: Edit equipment after intake — `UPD_EQUIPMENT` (C2)

**Files:**
- Modify: `app/bot.py` (state const ~173; `_upd_pick_keyboard`; `upd_pick`; new handlers;
  `_upd_summary_line`; UPD states registration ~5286-5297)
- Test: `tests/test_equipment_intake.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_equipment_intake.py
@pytest.mark.asyncio
async def test_upd_equipment_saves_and_returns_to_pick(mock_bot, tmp_path, monkeypatch):
    from app import bot
    from app.models import ClientProfile
    from app.database import engine
    from sqlmodel import Session
    cid = "cl_upd_equip"
    with Session(engine) as s:
        s.merge(ClientProfile(client_id=cid, avatar="gen_pop", training_days=3,
                              experience_level="beginner", limitations=[],
                              available_equipment=["full_gym"]))
        s.commit()
    ctx = make_context(mock_bot, {"upd_client_id": cid, "equip_selected": {"dumbbells"}})
    nxt = await bot.upd_equipment_confirm(make_callback_update(mock_bot, data="equip_confirm"), ctx)
    with Session(engine) as s:
        p = s.get(ClientProfile, cid)
    assert set(p.available_equipment) == {"dumbbells", "bodyweight"}
    assert nxt == bot.UPD_PICK
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_equipment_intake.py::test_upd_equipment_saves_and_returns_to_pick -v`
Expected: FAIL — `AttributeError: ... 'upd_equipment_confirm'`.

- [ ] **Step 3: Add the `UPD_EQUIPMENT` state + menu entry**

After line 173 (`UPD_EMAIL = "UPD_EMAIL"`) add:

```python
UPD_EQUIPMENT = "UPD_EQUIPMENT"
```

In `_upd_pick_keyboard` (`app/bot.py:2171-2180`), add a button before the regenerate row:

```python
        [InlineKeyboardButton("🏋️ Equipment", callback_data="upd:equip")],
```

In `_upd_summary_line` (`app/bot.py:2183-2189`), append equipment to the summary string
(before the closing `)`):

```python
        f" · equipment: {', '.join(profile.available_equipment) if profile.available_equipment else 'full_gym'}"
```

- [ ] **Step 4: Route `upd:equip` in `upd_pick`**

In `upd_pick` (`app/bot.py:2227`), add before the final `return UPD_PICK`:

```python
    if choice == "equip":
        context.user_data["equip_selected"] = set()
        await query.edit_message_text(
            "Check everything you have, then tap Done:",
            reply_markup=_equipment_checklist_keyboard(set()),
        )
        return UPD_EQUIPMENT
```

- [ ] **Step 5: Add the UPD equipment handlers**

Add near the other `upd_*` handlers:

```python
async def upd_equipment_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    query = update.callback_query
    await query.answer()
    tok = query.data[len("equip_toggle_"):]
    selected: set = context.user_data.get("equip_selected", set())
    if tok in selected:
        selected.discard(tok)
    else:
        selected.add(tok)
    context.user_data["equip_selected"] = selected
    await query.edit_message_reply_markup(reply_markup=_equipment_checklist_keyboard(selected))
    return UPD_EQUIPMENT


async def upd_equipment_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    from app.domain.workout.equipment import floor_equipment
    query = update.callback_query
    await query.answer()
    selected = sorted(context.user_data.get("equip_selected", set()))
    tokens = floor_equipment(selected + ["bodyweight"] if selected else [])
    client_id = context.user_data["upd_client_id"]
    _save_profile_field(client_id, available_equipment=tokens)
    context.user_data["upd_dirty"] = True
    await _upd_show_menu(query, client_id, dirty_note=f"✅ Equipment set to: *{', '.join(tokens)}*.")
    return UPD_PICK
```

- [ ] **Step 6: Register the `UPD_EQUIPMENT` state**

In the `/update_profile` ConversationHandler states (`app/bot.py:5286-5297`), add:

```python
            UPD_EQUIPMENT: [
                CallbackQueryHandler(upd_equipment_toggle, pattern=r"^equip_toggle_"),
                CallbackQueryHandler(upd_equipment_confirm, pattern=r"^equip_confirm$"),
            ],
```

- [ ] **Step 7: Run tests**

Run: `pytest tests/test_equipment_intake.py -v`
Expected: PASS (all, including the new UPD test).

- [ ] **Step 8: Commit**

```bash
git add app/bot.py tests/test_equipment_intake.py
git commit -m "feat(bot): UPD_EQUIPMENT — edit equipment after intake; unfreezes legacy full_gym clients (SP-A C2)"
```

---

## Task 6: Intake back navigation (C3)

**Files:**
- Modify: `app/bot.py` (back button on each step's prompt; `_intake_back`;
  `handle_limitations_confirm` idempotency; states registration adds back handlers)
- Test: `tests/test_equipment_intake.py`

Model: **forward-replay** — Back moves to the previous step only; the client re-taps
forward through pre-filled steps. Committed answers are preserved; confirm handlers are
idempotent. (See spec C3.)

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_equipment_intake.py
@pytest.mark.asyncio
async def test_back_from_equipment_returns_to_days(mock_bot):
    from app import bot
    ctx = make_context(mock_bot, {"avatar": "gen_pop", "days": 4})
    nxt = await bot.handle_intake_back(make_callback_update(mock_bot, data="intake_back:ASK_EQUIPMENT"), ctx)
    assert nxt == bot.ASK_DAYS


@pytest.mark.asyncio
async def test_back_from_baseline_computes_predecessor(mock_bot):
    from app import bot
    # no 'other' chosen → predecessor of baseline is ASK_LIMITATIONS
    ctx = make_context(mock_bot, {"avatar": "gen_pop", "days": 4,
                                  "experience_level": "beginner", "_ask_limitations_other": False})
    nxt = await bot.handle_intake_back(make_callback_update(mock_bot, data="intake_back:ASK_BASE_SQUAT"), ctx)
    assert nxt == bot.ASK_LIMITATIONS


@pytest.mark.asyncio
async def test_limitations_confirm_idempotent_clears_other_flag(mock_bot):
    from app import bot
    # second pass: 'other' no longer selected → flag must be False, not stale True
    ctx = make_context(mock_bot, {"selected_limitations": {"knee_pain"},
                                  "_ask_limitations_other": True})
    await bot.handle_limitations_confirm(make_callback_update(mock_bot, data="lim_confirm"), ctx)
    assert ctx.user_data["_ask_limitations_other"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_equipment_intake.py -k back -v`
Expected: FAIL — `AttributeError: ... 'handle_intake_back'`.

- [ ] **Step 3: Add `_intake_back` + the back handler**

Add to `app/bot.py` near the intake handlers:

```python
async def handle_intake_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Go back one intake step (forward-replay model). The state being LEFT is encoded
    in callback_data as 'intake_back:<STATE>'; we compute its predecessor from
    context.user_data and re-render that step pre-filled."""
    query = update.callback_query
    await query.answer()
    leaving = query.data.split(":", 1)[1]
    target = _intake_predecessor(leaving, context)
    return await _render_intake_step(target, query, context)


def _intake_predecessor(leaving: str, context: ContextTypes.DEFAULT_TYPE) -> str:
    """Conditional predecessors: baseline's predecessor depends on whether 'other' was
    chosen; custom-equipment's predecessor is the preset menu."""
    if leaving == ASK_EQUIPMENT:
        return ASK_DAYS
    if leaving in (ASK_EQUIPMENT_CUSTOM, ASK_EQUIPMENT_PULLUP):
        return ASK_EQUIPMENT
    if leaving == ASK_EXPERIENCE:
        return ASK_EQUIPMENT
    if leaving == ASK_LIMITATIONS:
        return ASK_EXPERIENCE
    if leaving == ASK_LIMITATIONS_OTHER:
        return ASK_LIMITATIONS
    if leaving == ASK_BASE_SQUAT:
        return ASK_LIMITATIONS_OTHER if context.user_data.get("_ask_limitations_other") else ASK_LIMITATIONS
    if leaving == ASK_BASE_BENCH:
        return ASK_BASE_SQUAT
    if leaving == ASK_BASE_DEADLIFT:
        return ASK_BASE_BENCH
    if leaving == ASK_EMAIL:
        return ASK_BASE_DEADLIFT
    return ASK_AVATAR


async def _render_intake_step(state: str, query, context: ContextTypes.DEFAULT_TYPE):
    """Re-render a step pre-filled from committed user_data, and return its state."""
    ud = context.user_data
    if state == ASK_DAYS:
        keyboard = [[InlineKeyboardButton("3 Days", callback_data="3"),
                     InlineKeyboardButton("4 Days", callback_data="4")],
                    [InlineKeyboardButton("5 Days", callback_data="5"),
                     InlineKeyboardButton("6 Days", callback_data="6")]]
        await query.edit_message_text("How many days a week can you train?",
                                      reply_markup=InlineKeyboardMarkup(keyboard))
        return ASK_DAYS
    if state == ASK_EQUIPMENT:
        await query.edit_message_text("What equipment do you have access to?",
                                      reply_markup=_equipment_preset_keyboard())
        return ASK_EQUIPMENT
    if state == ASK_EXPERIENCE:
        await _prompt_experience(query.edit_message_text)
        return ASK_EXPERIENCE
    if state == ASK_LIMITATIONS:
        selected = ud.get("selected_limitations", set())
        await query.edit_message_text("Select any injuries or limitations:",
                                      reply_markup=_build_limitations_keyboard(selected))
        return ASK_LIMITATIONS
    # ASK_LIMITATIONS_OTHER and baseline steps are free-text; re-prompt them
    if state == ASK_LIMITATIONS_OTHER:
        await query.edit_message_text(
            "Please describe your limitation in one sentence (e.g. 'recovering from ankle sprain'):")
        return ASK_LIMITATIONS_OTHER
    if state in (ASK_BASE_SQUAT, ASK_BASE_BENCH, ASK_BASE_DEADLIFT):
        lift = {"ASK_BASE_SQUAT": "SQUAT", "ASK_BASE_BENCH": "BENCH PRESS",
                "ASK_BASE_DEADLIFT": "DEADLIFT"}[state]
        await _prompt_baseline(query.edit_message_text, lift)
        return state
    # fallback: avatar
    keyboard = [[InlineKeyboardButton("Powerlifter", callback_data="powerlifter")],
                [InlineKeyboardButton("Powerbuilder", callback_data="powerbuilder")],
                [InlineKeyboardButton("General Fitness", callback_data="gen_pop")]]
    await query.edit_message_text("What is your primary training goal?",
                                  reply_markup=InlineKeyboardMarkup(keyboard))
    return ASK_AVATAR


def _with_back(markup: InlineKeyboardMarkup, leaving: str) -> InlineKeyboardMarkup:
    """Append a Back row that encodes the state being left."""
    rows = list(markup.inline_keyboard)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"intake_back:{leaving}")])
    return InlineKeyboardMarkup(rows)
```

- [ ] **Step 4: Make `handle_limitations_confirm` idempotent**

In `handle_limitations_confirm` (`app/bot.py:1983-2005`), set the `_ask_limitations_other`
flag on **every** path (not only when "other" is selected). Replace the function body's
branch logic with:

```python
    selected: set = context.user_data.get('selected_limitations', set())

    if "other" in selected:
        selected.discard("other")
        context.user_data['limitations'] = sorted(s for s in selected if s != "none")
        context.user_data['_ask_limitations_other'] = True
        await query.edit_message_text(
            "Please describe your limitation in one sentence (e.g. 'recovering from ankle sprain'):"
        )
        return ASK_LIMITATIONS_OTHER

    context.user_data['_ask_limitations_other'] = False        # idempotent: always set
    context.user_data.pop('limitations_notes', None)            # drop stale 'other' note on replay
    if "none" in selected or not selected:
        context.user_data['limitations'] = []
    else:
        context.user_data['limitations'] = sorted(selected)

    await _prompt_baseline(query.edit_message_text, "SQUAT")
    return ASK_BASE_SQUAT
```

- [ ] **Step 5: Add Back buttons to each step's prompt + register the back handler**

Wrap each post-first step's keyboard with `_with_back(..., "<THIS_STATE>")`:
- `handle_avatar`'s days keyboard → `_with_back(InlineKeyboardMarkup(keyboard), ASK_DAYS)`
  (the Back here leaves ASK_DAYS → returns to ASK_AVATAR).
- `handle_days`'s equipment keyboard → `_with_back(_equipment_preset_keyboard(), ASK_EQUIPMENT)`.
- `_equipment_checklist_keyboard` callers (custom) → wrap with `ASK_EQUIPMENT_CUSTOM`.
- `_pullup_keyboard` → wrap with `ASK_EQUIPMENT_PULLUP`.
- `_prompt_experience` keyboard → wrap with `ASK_EXPERIENCE`.
- `_build_limitations_keyboard` callers in intake → wrap with `ASK_LIMITATIONS`.
- `_baseline_keyboard` → add a Back row alongside Skip (leaving the current baseline state).

For free-text steps the Back arrives as a CallbackQuery, so register
`handle_intake_back` in **every** intake state. Add to each entry in `_intake_states`
(`app/bot.py:5209-5232`) a `CallbackQueryHandler(handle_intake_back, pattern=r"^intake_back:")`.
For example `ASK_EMAIL` becomes:

```python
        ASK_EMAIL: [
            CallbackQueryHandler(handle_intake_back, pattern=r"^intake_back:"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_email),
        ],
```

Apply the same addition to `ASK_LIMITATIONS_OTHER`, `ASK_BASE_SQUAT`, `ASK_BASE_BENCH`,
`ASK_BASE_DEADLIFT`, `ASK_DAYS`, `ASK_EQUIPMENT`, `ASK_EQUIPMENT_CUSTOM`,
`ASK_EQUIPMENT_PULLUP`, `ASK_EXPERIENCE`, and `ASK_LIMITATIONS`. (To show Back on a
free-text prompt like email, add a `reply_markup=_with_back(InlineKeyboardMarkup([]), ASK_EMAIL)`
when sending that prompt — i.e. the email prompt in `handle_base_deadlift`'s `_store_baseline_and_next`
gains a Back-only keyboard.)

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_equipment_intake.py -k "back or idempotent" -v`
Expected: PASS (3 tests).

- [ ] **Step 7: Run the full suite**

Run: `pytest -q`
Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add app/bot.py tests/test_equipment_intake.py
git commit -m "feat(bot): intake back navigation (forward-replay) + idempotent limitations confirm (SP-A C3)"
```

---

## Task 7: Pulling-gap surfacing — coach flag (C5)

**Files:**
- Modify: `app/bot.py` (`run_generation_and_dispatch`, the review DM composition ~544-560)
- Test: `tests/test_equipment_guard.py`

The intake warning to the client already ships in `handle_equipment_pullup` "No" (Task 4).
This task adds the **coach** flag on the approval DM.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_equipment_guard.py
from app.domain.workout import equipment as eq

def test_equipment_gap_note_for_no_bar_bodyweight():
    note = eq.equipment_gap_note(["bodyweight"])
    assert note and "pull" in note.lower()

def test_no_gap_note_with_bar():
    assert eq.equipment_gap_note(["bodyweight", "pull_up_bar"]) is None
    assert eq.equipment_gap_note(["full_gym"]) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_equipment_guard.py -v`
Expected: FAIL — `AttributeError: ... 'equipment_gap_note'`.

- [ ] **Step 3: Add `equipment_gap_note` to the module**

```python
# append to app/domain/workout/equipment.py
def equipment_gap_note(available_equipment: "list[str] | None") -> "str | None":
    """A coach-facing warning when the client's equipment can train no pulling pattern
    (no horizontal_pull and no vertical_pull is reachable). Returns None when fine."""
    reach = reachable_patterns(available_equipment)
    if "horizontal_pull" not in reach and "vertical_pull" not in reach:
        return ("⚠️ Equipment gap: no pulling movements available for this client — "
                "recommend a pull-up bar or resistance band.")
    return None
```

- [ ] **Step 4: Surface it in the coach approval DM**

In `run_generation_and_dispatch` (`app/bot.py`), where the review DM text is assembled
(the `notes_section` around lines 544-548), add the equipment-gap line. After:

```python
            gen_notes = generator.last_generation_notes
            notes_section = ""
            if gen_notes:
                notes_section = "\n\n*Generator notes:*\n" + "\n".join(f"• {n}" for n in gen_notes)
```

insert:

```python
            from app.domain.workout.equipment import equipment_gap_note
            gap = equipment_gap_note(profile.available_equipment if profile else None)
            if gap:
                notes_section += f"\n\n{gap}"
```

(`profile` is the function parameter; `notes_section` is then concatenated into
`admin_text` as it already is.)

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_equipment_guard.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add app/bot.py app/domain/workout/equipment.py tests/test_equipment_guard.py
git commit -m "feat(bot): coach approval DM flags a no-pulling equipment gap (SP-A C5)"
```

---

## Task 8: Coach equipment guard — validate every write path (C6)

**Files:**
- Modify: `app/bot.py` (`/override` set-time check ~5053-5058; reject path ~4158-4171;
  a shared `_equipment_bounce` helper)
- Test: `tests/test_equipment_guard.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_equipment_guard.py
import pytest
from unittest.mock import AsyncMock
from sqlmodel import Session
from app.database import engine
from app.models import ClientProfile
from tests.conftest import make_text_update, make_context


@pytest.mark.asyncio
async def test_override_to_unavailable_equipment_is_rejected(monkeypatch):
    from app import bot
    # treat the acting user as a coach so the auth gate + scope check pass
    monkeypatch.setattr(bot.auth_roles, "is_coach", lambda uid: True)
    monkeypatch.setattr(bot.auth_roles, "is_super_admin", lambda uid: False)
    cid = "cl_guard_override"
    with Session(engine) as s:
        s.merge(ClientProfile(client_id=cid, avatar="gen_pop", training_days=3,
                              experience_level="beginner", limitations=[],
                              available_equipment=["bodyweight"], assigned_coach_id=999))
        s.commit()
    mock_bot = AsyncMock()
    ctx = make_context(mock_bot)
    ctx.args = [cid, "bw_air_squat", "bb_back_squat_highbar"]  # target needs barbell+rack
    upd = make_text_update(mock_bot, user_id=999, text="/override")
    await bot.handle_override(upd, ctx)
    # override NOT stored
    with Session(engine) as s:
        p = s.get(ClientProfile, cid)
    assert not (p.coach_overrides or {}).get("bw_air_squat")
    # coach was told why (message.reply_text routes to mock_bot.send_message)
    sent = " ".join(str(c.kwargs.get("text", "")) + str(c.args)
                    for c in mock_bot.send_message.call_args_list)
    assert "barbell" in sent or "squat_rack" in sent


def test_validate_then_persist_blocks_bad_week(tmp_path):
    """The helper returns violations instead of writing when equipment is missing."""
    from app.domain.workout import equipment as eq
    from app.models import WorkoutWeek, WorkoutDay, WorkoutSlot
    slot = WorkoutSlot(slot_order=0, slot_type="main_compound",
                       exercise_id="bb_back_squat_highbar", exercise_name="Squat",
                       sets=3, reps="5", rpe=7)
    week = WorkoutWeek(week_number=1, days=[WorkoutDay(day_name="A", slots=[slot], total_fatigue=5)])
    violations = eq.validate_equipment(week, ["bodyweight"])
    assert violations and violations[0].exercise_id == "bb_back_squat_highbar"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_equipment_guard.py -v`
Expected: FAIL — `/override` currently stores the override unconditionally (assertion
`not ...get("bw_air_squat")` fails).

- [ ] **Step 3: Add the `/override` set-time equipment check**

In `handle_override` (`app/bot.py`), replace the set block (lines 5053-5058):

```python
        from_id, to_id = args[1], args[2]
        overrides = dict(profile.coach_overrides or {})
        overrides[from_id] = to_id
        profile.coach_overrides = overrides
        session.add(profile)
        session.commit()
```

with an equipment guard before storing:

```python
        from_id, to_id = args[1], args[2]
        from app.domain.workout.equipment import validate_equipment, equipment_alternatives
        from app.models import WorkoutWeek, WorkoutDay, WorkoutSlot
        probe = WorkoutWeek(week_number=1, days=[WorkoutDay(
            day_name="probe",
            slots=[WorkoutSlot(slot_order=0, slot_type="isolation", exercise_id=to_id,
                               exercise_name=to_id, sets=1, reps="1", rpe=1)],
            total_fatigue=1)])
        bad = validate_equipment(probe, profile.available_equipment)
        if bad:
            missing = ", ".join(bad[0].missing)
            alts = equipment_alternatives(to_id, profile.available_equipment)
            alt_txt = "\n".join(f"  `{a['exercise_id']}` — {a['name']}" for a in alts) or "  (none in DB)"
            await update.message.reply_text(
                f"🚫 Can't set that override: `{to_id}` needs *{missing}*, which "
                f"{profile.name or client_id} doesn't have.\n\nEquipment-valid alternatives:\n{alt_txt}",
                parse_mode="Markdown",
            )
            return
        overrides = dict(profile.coach_overrides or {})
        overrides[from_id] = to_id
        profile.coach_overrides = overrides
        session.add(profile)
        session.commit()
```

- [ ] **Step 4: Guard the reject (LLM-edit) write path**

In the reject feedback handler (`app/bot.py:4155-4171`), after parsing `new_workout`
(line 4158) and before writing `pending.workout_json` (line 4166), validate it:

```python
            new_workout = WorkoutWeek.model_validate_json(mutated_json)
            from app.domain.workout.equipment import validate_equipment, equipment_alternatives
            _eq_client = session.get(ClientProfile, pending.client_id)
            _avail = _eq_client.available_equipment if _eq_client else None
            _violations = validate_equipment(new_workout, _avail)
            if _violations:
                v = _violations[0]
                alts = equipment_alternatives(v.exercise_id, _avail)
                alt_txt = "\n".join(f"• {a['name']} (`{a['exercise_id']}`)" for a in alts) or "(none in DB)"
                await update.message.reply_text(
                    f"🚫 That edit added *{v.exercise_name}*, which needs "
                    f"*{', '.join(v.missing)}* — the client doesn't have it. "
                    f"Plan NOT changed.\n\nEquipment-valid alternatives:\n{alt_txt}",
                    parse_mode="Markdown",
                )
                return ConversationHandler.END
```

(Place this immediately after the `new_workout = WorkoutWeek.model_validate_json(...)`
line and before `_feedback_client = ...` so the plan is never overwritten on a violation.)

- [ ] **Step 5: Defensive validation at the initial-generation write**

The `/override` set-time check (Step 3) only guards overrides set *after* this ships. An
override stored **before** the guard (or set via the web API at `app/api/coach.py:204`,
which is out of bot-only-prod scope) is applied during generation and would otherwise reach
the coach unflagged. Add a defensive check at the generation write
(`run_generation_and_dispatch`, around the `PendingApproval(...)` at `app/bot.py:513-524`).
Because generation is automatic (no coach to bounce to yet), a violation is **surfaced on
the approval DM**, not blocked — the coach then fixes it via `/override` or reject. After
the `notes_section` assembly (the same place as Task 7), add:

```python
            from app.domain.workout.equipment import validate_equipment
            _gen_violations = validate_equipment(new_workout, profile.available_equipment if profile else None)
            if _gen_violations:
                bad_list = ", ".join(f"{v.exercise_name} (needs {', '.join(v.missing)})" for v in _gen_violations)
                notes_section += f"\n\n🚫 *Equipment mismatch in this plan:* {bad_list}"
```

Note in a comment that the **Add-core** path (`bot.py:4567`, `_core_choices_for_client`) is
already equipment-filtered and needs no guard. This makes the guard cover all three
`PendingApproval.workout_json` write sites: generation (defensive flag), reject LLM-edit
(block, Step 4), and add-core (already safe).

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_equipment_guard.py -v`
Expected: PASS.

- [ ] **Step 7: Run the full suite**

Run: `pytest -q`
Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add app/bot.py tests/test_equipment_guard.py
git commit -m "feat(bot): equipment guard — /override set-time, reject LLM-edit block, generation-write coach flag; reason + alternatives (SP-A C6)"
```

---

## Task 9: Docs — CLAUDE.md + CHANGELOG (C-docs)

**Files:**
- Modify: `CLAUDE.md`, `CHANGELOG.md`

- [ ] **Step 1: Update CLAUDE.md key-design-constraints**

Add a bullet under "Key design constraints":

```markdown
- Equipment is collected at intake (preset + 15-item checklist + an explicit pull-up-bar
  question on the bodyweight path) and editable via `/update_profile` → Equipment; it
  replaces the old hardcoded `["full_gym"]`. The empty selection is floored to
  `["bodyweight"]` (an empty list would make the generator emit a zero-exercise plan); a
  legacy/empty row is treated as `full_gym` at generation. Coach exercise-adds are
  equipment-guarded: `/override` is checked at set-time and the reject LLM-edit path is
  validated before it can overwrite a plan, both bouncing with the reason + equipment-valid
  alternatives. A bodyweight-only client with no bar can train no pulling pattern — the
  coach approval DM flags this. Bodyweight floor: `bw_air_squat`, `bw_reverse_lunge`,
  `bw_single_leg_rdl`, `bw_knee_push_up`, `bw_inverted_row_bar` (no regression metadata —
  that is SP-B). See `docs/superpowers/specs/2026-06-20-spa-equipment-back-button-design.md`.
```

- [ ] **Step 2: Update CHANGELOG.md**

Add a new section at the top:

```markdown
## [1.4.0] — 2026-06-20

### Added
- Equipment survey at intake (preset + checklist + pull-up-bar question), replacing the
  hardcoded `full_gym` — non-gym clients no longer receive impossible exercises (SP-A C1).
- `/update_profile` → Equipment to edit equipment after intake (SP-A C2).
- Intake back navigation (forward-replay) so a wrong answer can be corrected (SP-A C3).
- Bodyweight floor: 5 exercises so a no-gym client gets a complete plan (SP-A C4).
- Coach approval DM flags a no-pulling equipment gap (SP-A C5).
- Equipment guard on `/override` (set-time) and the reject LLM-edit path, with reason +
  alternatives (SP-A C6).
```

- [ ] **Step 3: Run the full suite one final time**

Run: `pytest -q`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md CHANGELOG.md
git commit -m "docs: record SP-A equipment-aware plans + intake back button (1.4.0)"
```

---

## Definition of done

- A new intake collects equipment (not hardcoded `full_gym`); the bodyweight presets ask
  about a pull-up bar; an empty custom selection floors to bodyweight.
- `/update_profile` can change equipment; a legacy `full_gym` client can move to a home set.
- Back works from every post-first intake step (computed predecessor; idempotent replay).
- A dumbbell-only and a bodyweight+bar client generate plans whose every exercise is
  equipment-valid (Task 1 + Task 3 end-to-end tests).
- A coach cannot `/override` to, or LLM-edit in, an exercise the client lacks equipment for
  — both bounce with reason + alternatives.
- The coach approval DM flags a no-pulling client.
- `pytest -q` green.
```
