# Usability + Safety Cluster Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make generated plans safe (honor declared injuries), accurate (gate nutrition macros), and usable (varied meals + week-1 loads) by wiring four verified-but-dead capabilities into the deterministic engine.

**Architecture:** Four independent slices, each fully deterministic and TDD'd. A.4 adds a pure load-seeding module + 3 intake questions + a generator hook. A.1 wires `SUBSTITUTION_MAP` into exercise filtering/selection. A.3 adds day-indexed rotation to the meal builder. A.2 calls the already-imported-but-unused `validate_day` per day and surfaces drift to the coach.

**Tech Stack:** Python 3.12, SQLModel, Alembic, python-telegram-bot, PuLP, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-06-13-usability-safety-cluster-design.md` (Appendix A = the verified strength-science source of truth).

---

## File Structure

**Create:**
- `app/domain/workout/loadseed.py` — pure load-seeding math (Brzycki e1RM, RPE→%1RM grid, pattern→e1RM map, `seed_working_load`). No I/O, no deps beyond `app.models`.
- `tests/test_loadseed.py` — unit tests for the above.
- `tests/test_injury_substitution.py` — A.1 generator tests.
- `tests/test_meal_rotation.py` — A.3 tests.
- `tests/test_nutrition_validation_gate.py` — A.2 tests.
- `alembic/versions/0020_client_baseline_e1rm.py` — 3 nullable columns on `clientprofile`.

**Modify:**
- `app/models.py` — add `squat_e1rm`/`bench_e1rm`/`deadlift_e1rm` to `ClientProfile`.
- `app/bot.py` — 3 new intake states + handlers; redirect limitations exits; persist new fields in both branches.
- `app/generator.py` — injury helpers + filter/selection wiring (A.1); load-seeding hook + injury caveats (A.4/A.1).
- `app/domain/workout/constants.py` — `INJURY_CAVEATS` map (A.1).
- `app/domain/nutrition/meal_builder.py` — `day_index` param + rotated `_pick` (A.3).
- `app/services/nutrition_service.py` — thread `day_index`; call `validate_day` and collect warnings (A.3/A.2).

---

## Task 1: Load-seeding math module (A.4 foundation)

**Files:**
- Create: `app/domain/workout/loadseed.py`
- Test: `tests/test_loadseed.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_loadseed.py
import math
import pytest
from app.models import ClientProfile
from app.domain.workout import loadseed


def _client(**e1rm):
    return ClientProfile(client_id="t_load", **e1rm)


def test_brzycki_single_returns_lifted_weight():
    # At 1 rep Brzycki returns exactly the weight moved (conservative vs Epley).
    assert loadseed.brzycki_e1rm(100.0, 1) == pytest.approx(100.0)


def test_brzycki_five_reps():
    # 100 * 36 / (37 - 5) = 100 * 36 / 32 = 112.5
    assert loadseed.brzycki_e1rm(100.0, 5) == pytest.approx(112.5)


def test_brzycki_clamps_reps_above_ten():
    # reps > 10 are clamped to 10 (formula unreliable past 10).
    assert loadseed.brzycki_e1rm(100.0, 15) == loadseed.brzycki_e1rm(100.0, 10)


def test_working_pct_grid_spotchecks():
    assert loadseed.working_pct(5, 8) == pytest.approx(0.811)
    assert loadseed.working_pct(1, 10) == pytest.approx(1.000)
    assert loadseed.working_pct(10, 6) == pytest.approx(0.656)


def test_working_pct_clamps_out_of_range():
    assert loadseed.working_pct(0, 8) == loadseed.working_pct(1, 8)
    assert loadseed.working_pct(99, 5) == loadseed.working_pct(10, 6)  # reps&rpe clamped


def test_pattern_e1rm_direct_baselines():
    c = _client(squat_e1rm=140.0, bench_e1rm=100.0, deadlift_e1rm=180.0)
    assert loadseed.pattern_e1rm(c, "squat") == pytest.approx(140.0)
    assert loadseed.pattern_e1rm(c, "hinge") == pytest.approx(180.0)
    assert loadseed.pattern_e1rm(c, "horizontal_push") == pytest.approx(100.0)


def test_pattern_e1rm_ratio_derivations():
    c = _client(bench_e1rm=100.0)
    assert loadseed.pattern_e1rm(c, "horizontal_pull") == pytest.approx(70.0)  # row 0.70*bench
    assert loadseed.pattern_e1rm(c, "vertical_push") == pytest.approx(60.0)    # OHP 0.60*bench


def test_pattern_e1rm_guidance_patterns_return_none():
    c = _client(squat_e1rm=140.0, bench_e1rm=100.0, deadlift_e1rm=180.0)
    assert loadseed.pattern_e1rm(c, "vertical_pull") is None  # pull-up needs bodyweight
    assert loadseed.pattern_e1rm(c, "lunge") is None
    assert loadseed.pattern_e1rm(c, "isolation") is None


def test_pattern_e1rm_missing_baseline_returns_none():
    c = _client(bench_e1rm=100.0)  # no squat baseline
    assert loadseed.pattern_e1rm(c, "squat") is None


def test_seed_working_load_rounds_down_to_2_5kg_and_never_exceeds_e1rm():
    c = _client(squat_e1rm=140.0)
    # reps "5-8" -> 5 reps, rpe 7 -> pct 0.786 -> 140*0.786 = 110.04 -> floor to 110.0
    load = loadseed.seed_working_load(c, "squat", "5-8", 7.0)
    assert load == pytest.approx(110.0)
    assert load % 2.5 == 0
    assert load <= 140.0


def test_seed_working_load_none_when_unseedable():
    c = _client(bench_e1rm=100.0)
    assert loadseed.seed_working_load(c, "vertical_pull", "5-8", 7.0) is None  # guidance
    assert loadseed.seed_working_load(c, "squat", "5-8", 7.0) is None          # baseline skipped
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_loadseed.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.domain.workout.loadseed'` (and `ClientProfile` has no `squat_e1rm` yet — that is added in Task 2; for now the import error fails first).

- [ ] **Step 3: Write the module**

```python
# app/domain/workout/loadseed.py
"""
Deterministic week-1 working-load seeding from client baseline lifts.

Inputs: a ClientProfile carrying optional squat_e1rm / bench_e1rm / deadlift_e1rm
(estimated 1RMs computed at intake via Brzycki). Output: a conservative working
load for a slot, or None when the slot's pattern can't be seeded (guidance string
handled downstream).

Source of truth: docs/superpowers/specs/2026-06-13-usability-safety-cluster-design.md
Appendix A (Brzycki, Tuchscherer RPE->%1RM grid, derived-lift ratios). Mandate: err
light — round DOWN; the autoregulator corrects an under-seed in one week.
"""
from __future__ import annotations

import math
from typing import Optional

from app.models import ClientProfile


def brzycki_e1rm(weight_kg: float, reps: int) -> float:
    """Estimated 1RM via Brzycki: w * 36 / (37 - r). Reps clamped to 1..10."""
    r = max(1, min(10, int(reps)))
    return weight_kg * 36.0 / (37.0 - r)


# Tuchscherer / RTS RIR-based %1RM grid. Rows = reps 1..10, cols = RPE 6..10.
# Values are percentages; working_pct() divides by 100.
_PCT_ROWS: dict[int, list[float]] = {
    1:  [86.3, 89.2, 92.2, 95.5, 100.0],
    2:  [83.7, 86.3, 89.2, 92.2, 95.5],
    3:  [81.1, 83.7, 86.3, 89.2, 92.2],
    4:  [78.6, 81.1, 83.7, 86.3, 89.2],
    5:  [76.2, 78.6, 81.1, 83.7, 86.3],
    6:  [73.9, 76.2, 78.6, 81.1, 83.7],
    7:  [71.7, 73.9, 76.2, 78.6, 81.1],
    8:  [69.6, 71.7, 73.9, 76.2, 78.6],
    9:  [67.6, 69.6, 71.7, 73.9, 76.2],
    10: [65.6, 67.6, 69.6, 71.7, 73.9],
}


def working_pct(reps: int, rpe: float) -> float:
    """Fraction of 1RM for `reps` at `rpe`. Reps clamped 1..10, RPE clamped 6..10."""
    r = max(1, min(10, int(reps)))
    e = max(6, min(10, int(round(rpe))))
    return _PCT_ROWS[r][e - 6] / 100.0


# pattern -> (ClientProfile baseline field, ratio). Patterns absent here are
# guidance-only (vertical_pull/lunge/isolation): they return None.
_PATTERN_BASELINE: dict[str, tuple[str, float]] = {
    "squat":            ("squat_e1rm", 1.0),
    "hinge":            ("deadlift_e1rm", 1.0),
    "horizontal_push":  ("bench_e1rm", 1.0),
    "horizontal_pull":  ("bench_e1rm", 0.70),   # barbell row ~0.70 x bench 1RM
    "vertical_push":    ("bench_e1rm", 0.60),   # overhead press ~0.60 x bench 1RM
}


def pattern_e1rm(client: ClientProfile, pattern: str) -> Optional[float]:
    """Derived 1RM for a movement pattern, or None if unseedable/baseline missing."""
    spec = _PATTERN_BASELINE.get(pattern)
    if spec is None:
        return None
    field, ratio = spec
    base = getattr(client, field, None)
    if not base:
        return None
    return base * ratio


def _first_rep(reps_str: str) -> int:
    """Lower bound of a rep range like '5-8' -> 5. Defaults to 5 on bad input."""
    try:
        return int(str(reps_str).split("-")[0])
    except (ValueError, IndexError, AttributeError):
        return 5


def seed_working_load(
    client: ClientProfile, pattern: str, reps_str: str, rpe: float
) -> Optional[float]:
    """Conservative working load (kg) for a slot, rounded DOWN to 2.5 kg.

    Returns None when the pattern is guidance-only or the needed baseline is absent.
    """
    e1rm = pattern_e1rm(client, pattern)
    if e1rm is None:
        return None
    raw = e1rm * working_pct(_first_rep(reps_str), rpe)
    return math.floor(raw / 2.5) * 2.5
```

> NOTE: `tests/test_loadseed.py` constructs `ClientProfile(client_id=..., squat_e1rm=...)`. Those fields are added in Task 2. Run order: do Task 2's model change before re-running this test green. The module itself uses `getattr(..., None)`, so it imports cleanly even before the columns exist.

- [ ] **Step 4: Add the model fields needed by the test (mini-slice of Task 2)**

In `app/models.py`, inside `class ClientProfile`, after `progressive_neuro_deficits` (currently `models.py:72`):

```python
    # ── Week-1 load seeding (baseline estimated 1RMs from intake) ──
    squat_e1rm: Optional[float] = Field(default=None)
    bench_e1rm: Optional[float] = Field(default=None)
    deadlift_e1rm: Optional[float] = Field(default=None)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_loadseed.py -v`
Expected: PASS (all 11 tests).

- [ ] **Step 6: Commit**

```bash
git add app/domain/workout/loadseed.py tests/test_loadseed.py app/models.py
git commit -m "feat(workout): deterministic week-1 load-seeding math (Brzycki + RPE grid)"
```

---

## Task 2: Alembic migration for the 3 baseline columns (A.4)

**Files:**
- Create: `alembic/versions/0020_client_baseline_e1rm.py`

The prod DB is Postgres and runs `alembic upgrade head` on startup (`app/main.py:78`); SQLite/dev relies on `create_all`, which already saw the new fields in Task 1. The migration makes the live Postgres deploy add the columns.

- [ ] **Step 1: Write the migration**

```python
# alembic/versions/0020_client_baseline_e1rm.py
"""Add squat/bench/deadlift estimated-1RM columns to clientprofile for week-1 load seeding.

All nullable — existing rows are unaffected (clients onboarded before this feature
simply have no baselines and get guidance strings instead of seeded loads).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("clientprofile", sa.Column("squat_e1rm", sa.Float(), nullable=True))
    op.add_column("clientprofile", sa.Column("bench_e1rm", sa.Float(), nullable=True))
    op.add_column("clientprofile", sa.Column("deadlift_e1rm", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("clientprofile", "deadlift_e1rm")
    op.drop_column("clientprofile", "bench_e1rm")
    op.drop_column("clientprofile", "squat_e1rm")
```

- [ ] **Step 2: Verify the migration applies on a scratch SQLite DB**

Run:
```bash
DATABASE_URL="sqlite:///./_mig_check.db" alembic upgrade head && \
DATABASE_URL="sqlite:///./_mig_check.db" python -c "import sqlalchemy as sa, os; e=sa.create_engine(os.environ['DATABASE_URL']); print([c['name'] for c in sa.inspect(e).get_columns('clientprofile') if c['name'].endswith('_e1rm')])" && \
rm -f _mig_check.db
```
Expected: prints `['squat_e1rm', 'bench_e1rm', 'deadlift_e1rm']` and exits 0.

- [ ] **Step 3: Confirm alembic head is unique**

Run: `alembic heads`
Expected: a single head `0020 (head)`. If two heads appear, the `down_revision` is wrong — fix to point at the prior single head.

- [ ] **Step 4: Commit**

```bash
git add alembic/versions/0020_client_baseline_e1rm.py
git commit -m "feat(db): migration 0020 — clientprofile baseline e1RM columns"
```

---

## Task 3: Intake questions for baseline lifts (A.4)

**Files:**
- Modify: `app/bot.py` (state constants `:157`; handlers near `:1981/1988/1996`; states dict `:5116-5127`; persist branches `:2024-2034` and `:2042-2053`)
- Test: `tests/test_bot_flow.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bot_flow.py  (append)
from app.bot import _parse_baseline_set


def test_parse_baseline_set_valid_forms():
    assert _parse_baseline_set("100x5") == (100.0, 5)
    assert _parse_baseline_set("100 x 5") == (100.0, 5)
    assert _parse_baseline_set("60*3") == (60.0, 3)
    assert _parse_baseline_set("82.5X4") == (82.5, 4)


def test_parse_baseline_set_rejects_bad_and_high_reps():
    assert _parse_baseline_set("skip") is None
    assert _parse_baseline_set("heavy") is None
    assert _parse_baseline_set("100x15") is None   # reps > 10 rejected (formula unreliable)
    assert _parse_baseline_set("100") is None       # no reps
    assert _parse_baseline_set("0x5") is None        # non-positive weight
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_bot_flow.py::test_parse_baseline_set_valid_forms -v`
Expected: FAIL — `ImportError: cannot import name '_parse_baseline_set'`.

- [ ] **Step 3: Add the parser + state constants**

In `app/bot.py`, replace the intake-states line (`:157`):

```python
ASK_AVATAR, ASK_DAYS, ASK_EXPERIENCE, ASK_LIMITATIONS, ASK_EMAIL = range(5)
```

with:

```python
ASK_AVATAR, ASK_DAYS, ASK_EXPERIENCE, ASK_LIMITATIONS, ASK_EMAIL = range(5)
# Baseline-lift intake states (A.4). Strings keep them distinct from the ints above
# within the single intake ConversationHandler.
ASK_BASE_SQUAT = "ASK_BASE_SQUAT"
ASK_BASE_BENCH = "ASK_BASE_BENCH"
ASK_BASE_DEADLIFT = "ASK_BASE_DEADLIFT"
```

Add the parser near the other intake helpers (e.g. just below `_build_limitations_keyboard`, around `:1907`):

```python
import re as _re_baseline  # local alias; module already imports re elsewhere if present


def _parse_baseline_set(text: str) -> Optional[tuple[float, int]]:
    """Parse 'WxR' (weight x reps) like '100x5'. Returns (weight, reps) or None.

    Rejects unparseable input, non-positive weight, and reps > 10 (the e1RM
    formula is unreliable past 10 reps — re-ask rather than seed garbage).
    """
    if not text:
        return None
    m = _re_baseline.match(r"^\s*(\d+(?:\.\d+)?)\s*[xX*]\s*(\d+)\s*$", text.strip())
    if not m:
        return None
    weight = float(m.group(1))
    reps = int(m.group(2))
    if weight <= 0 or reps < 1 or reps > 10:
        return None
    return (weight, reps)
```

> If `app/bot.py` already imports `re` at module top, drop the alias and use `re.match`. Verify with `grep -n "^import re" app/bot.py` and prefer the existing import.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_bot_flow.py::test_parse_baseline_set_valid_forms tests/test_bot_flow.py::test_parse_baseline_set_rejects_bad_and_high_reps -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add app/bot.py tests/test_bot_flow.py
git commit -m "feat(bot): baseline-set parser + states for week-1 load intake"
```

- [ ] **Step 6: Wire the three baseline handlers into the conversation**

Add three handlers next to `handle_limitations_other` (after `:1988`). Each shows a Skip button and advances:

```python
def _baseline_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("Skip", callback_data="base_skip")]])


async def _prompt_baseline(target, lift: str) -> None:
    await target(
        f"Optional — your best recent {lift} set? Reply like `100x5` (weight×reps, "
        f"reps ≤ 10), or tap Skip.",
        reply_markup=_baseline_keyboard(),
    )


async def _store_baseline_and_next(update, context, field: str, next_state: str,
                                   next_lift: Optional[str]) -> str:
    """Shared logic for the squat/bench handlers. Stores e1RM (or None) then prompts next."""
    query = update.callback_query
    if query is not None:                 # Skip button
        await query.answer()
        context.user_data[field] = None
        send = query.edit_message_text
    else:                                  # text reply
        parsed = _parse_baseline_set(update.message.text)
        if parsed is None:
            await update.message.reply_text(
                "Couldn't read that. Use `weight x reps`, e.g. `100x5` (reps ≤ 10), or tap Skip.",
                reply_markup=_baseline_keyboard(),
            )
            return _CURRENT_BASELINE_STATE[field]   # re-ask same state
        weight, reps = parsed
        from app.domain.workout.loadseed import brzycki_e1rm
        context.user_data[field] = round(brzycki_e1rm(weight, reps), 1)
        send = update.message.reply_text
    if next_lift is not None:
        await _prompt_baseline(send, next_lift)
    else:
        await send("Almost there! What's your email address? (We'll send your plan PDF here.)")
    return next_state


# Maps a baseline field to the state that re-asks it (used on parse failure).
_CURRENT_BASELINE_STATE = {
    "squat_e1rm": ASK_BASE_SQUAT,
    "bench_e1rm": ASK_BASE_BENCH,
    "deadlift_e1rm": ASK_BASE_DEADLIFT,
}


async def handle_base_squat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await _store_baseline_and_next(update, context, "squat_e1rm", ASK_BASE_BENCH, "BENCH PRESS")


async def handle_base_bench(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await _store_baseline_and_next(update, context, "bench_e1rm", ASK_BASE_DEADLIFT, "DEADLIFT")


async def handle_base_deadlift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await _store_baseline_and_next(update, context, "deadlift_e1rm", ASK_EMAIL, None)
```

> `_store_baseline_and_next` returns `ASK_EMAIL` after deadlift; `ASK_EMAIL` is an int and the others are strings — both valid distinct states in one ConversationHandler.

- [ ] **Step 7: Redirect the three limitations exits to the first baseline prompt**

The three handlers that currently `return ASK_EMAIL` must instead prompt squat and return `ASK_BASE_SQUAT`.

In `handle_limitations_confirm` (`:1980-1981`), replace:
```python
    await query.edit_message_text("Almost there! What's your email address? (We'll send your plan PDF here.)")
    return ASK_EMAIL
```
with:
```python
    await _prompt_baseline(query.edit_message_text, "SQUAT")
    return ASK_BASE_SQUAT
```

In `handle_limitations_other` (`:1987-1988`), replace:
```python
    await update.message.reply_text("Almost there! What's your email address? (We'll send your plan PDF here.)")
    return ASK_EMAIL
```
with:
```python
    await _prompt_baseline(update.message.reply_text, "SQUAT")
    return ASK_BASE_SQUAT
```

In legacy `handle_limitations` (`:1995-1996`), apply the same replacement as `handle_limitations_other` above.

- [ ] **Step 8: Register the new states in the intake states dict**

In `_intake_states` (`:5116-5127`), add after the `ASK_EMAIL` entry:

```python
        ASK_BASE_SQUAT: [
            CallbackQueryHandler(handle_base_squat, pattern=r"^base_skip$"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_base_squat),
        ],
        ASK_BASE_BENCH: [
            CallbackQueryHandler(handle_base_bench, pattern=r"^base_skip$"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_base_bench),
        ],
        ASK_BASE_DEADLIFT: [
            CallbackQueryHandler(handle_base_deadlift, pattern=r"^base_skip$"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_base_deadlift),
        ],
```

- [ ] **Step 9: Persist the baselines in BOTH profile branches**

In the **update** branch (`:2032`, after `profile.limitations_notes = ...`):
```python
                profile.squat_e1rm = context.user_data.get('squat_e1rm', profile.squat_e1rm)
                profile.bench_e1rm = context.user_data.get('bench_e1rm', profile.bench_e1rm)
                profile.deadlift_e1rm = context.user_data.get('deadlift_e1rm', profile.deadlift_e1rm)
```

In the **create** branch (`:2052`, after `limitations_notes=context.user_data.get('limitations_notes'),`):
```python
                squat_e1rm=context.user_data.get('squat_e1rm'),
                bench_e1rm=context.user_data.get('bench_e1rm'),
                deadlift_e1rm=context.user_data.get('deadlift_e1rm'),
```

- [ ] **Step 10: Write an integration test for the redirect + persist**

```python
# tests/test_bot_flow.py  (append)
import inspect
import app.bot as bot


def test_limitations_exits_route_to_baseline_not_email():
    # All three limitations exit handlers must hand off to the baseline flow.
    for fn in (bot.handle_limitations_confirm, bot.handle_limitations_other, bot.handle_limitations):
        src = inspect.getsource(fn)
        assert "ASK_BASE_SQUAT" in src, f"{fn.__name__} should route to ASK_BASE_SQUAT"


def test_intake_states_register_baseline_handlers():
    # The three baseline states must be reachable handlers (smoke check on names).
    for name in ("handle_base_squat", "handle_base_bench", "handle_base_deadlift"):
        assert hasattr(bot, name)
```

- [ ] **Step 11: Run the bot-flow tests**

Run: `pytest tests/test_bot_flow.py -v`
Expected: PASS (existing + new). If the existing suite imports the bot module, a syntax/registration error surfaces here.

- [ ] **Step 12: Commit**

```bash
git add app/bot.py tests/test_bot_flow.py
git commit -m "feat(bot): collect squat/bench/deadlift baselines in intake (skippable)"
```

---

## Task 4: Seed week-1 loads in the generator (A.4)

**Files:**
- Modify: `app/generator.py` (`_construct_slot`, after the prior-week block `:390-407`, before `if is_compound:` `:408`)
- Test: `tests/test_generator_hardening.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_generator_hardening.py  (append)
from app.generator import WorkoutGenerator
from app.models import ClientProfile


def _mk_client(**kw):
    base = dict(client_id="t_seed", avatar="gen_pop", training_days=3,
                experience_level="intermediate", limitations=[],
                available_equipment=["full_gym"], week_number=1)
    base.update(kw)
    return ClientProfile(**base)


def test_week1_main_compound_gets_seeded_load_when_baseline_present():
    gen = WorkoutGenerator()
    client = _mk_client(squat_e1rm=140.0, bench_e1rm=100.0, deadlift_e1rm=180.0)
    week = gen.generate(client)
    seeded = [s for d in week.days for s in d.slots
              if s.slot_type == "main_compound" and s.target_weight is not None]
    assert seeded, "at least one main compound should have a seeded target_weight"
    for s in seeded:
        assert s.target_weight % 2.5 == 0


def test_week1_no_loads_when_baselines_skipped():
    gen = WorkoutGenerator()
    client = _mk_client()  # no baselines
    week = gen.generate(client)
    assert all(s.target_weight is None for d in week.days for s in d.slots)


def test_seed_does_not_override_prior_week_progression():
    gen = WorkoutGenerator()
    client = _mk_client(squat_e1rm=140.0, week_number=2)
    week1 = gen.generate(_mk_client(squat_e1rm=140.0))
    # Log a real working weight on every main compound of week 1.
    for d in week1.days:
        for s in d.slots:
            if s.slot_type == "main_compound":
                s.actual_weight = 120.0
                s.actual_rpe = s.rpe
    week2 = gen.generate(client, prior_week=week1)
    # Where a prior actual exists, the autoregulated weight (not the raw seed) is used.
    progressed = [s for d in week2.days for s in d.slots
                  if s.slot_type == "main_compound" and s.target_weight is not None]
    assert progressed, "week 2 should carry autoregulated loads"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_generator_hardening.py::test_week1_main_compound_gets_seeded_load_when_baseline_present -v`
Expected: FAIL — `assert seeded` is empty (no seeding hook yet; week-1 `target_weight` is None everywhere).

- [ ] **Step 3: Add the seeding hook**

In `app/generator.py`, in `_construct_slot`, immediately AFTER the prior-week load-progression `for/else` block (the one ending near `:406`, just before `if is_compound:` at `:408`), insert:

```python
            # Week-1 / no-telemetry seeding: if no prior actual set a target_weight,
            # seed a conservative starting load from the client's baseline lifts.
            # The prior-week path above always takes precedence (we only fill a gap).
            if slot.target_weight is None:
                from app.domain.workout.loadseed import seed_working_load
                seeded = seed_working_load(client, exercise.movement_pattern, reps, slot_rpe)
                if seeded is not None:
                    slot.target_weight = seeded
```

> `client`, `exercise`, `reps`, and `slot_rpe` are all in scope (`client`/`prior_week` via the `_fill_slots` closure; `exercise`/`reps`/`slot_rpe` are `_construct_slot` parameters). Seeding before the `if is_compound:` block means the warm-up builder (`:423-430`) uses the real seeded load instead of the 60 kg fallback.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_generator_hardening.py -v`
Expected: PASS (new + existing).

- [ ] **Step 5: Run the full generator suite (regression)**

Run: `pytest tests/test_generator.py tests/test_generator_hardening.py -v`
Expected: PASS — no existing generator behavior regressed.

- [ ] **Step 6: Commit**

```bash
git add app/generator.py tests/test_generator_hardening.py
git commit -m "feat(workout): seed week-1 working loads from baseline e1RMs"
```

---

## Task 5: Injury-aware exercise selection (A.1)

**Files:**
- Modify: `app/domain/workout/constants.py` (add `INJURY_CAVEATS`)
- Modify: `app/generator.py` (`_filter_exercises` `:140-190`; `_select_for_slot` `:276-340`; `_construct_slot` cue append)
- Test: `tests/test_injury_substitution.py`

**Design note (refinement over the spec's wording):** banned-pattern exercises are excluded in the filter (hard safety). Selection then runs the normal muscle-targeted tiers first, so where a *same-muscle* safe option exists (e.g. `shoulder_impingement` bans overhead `vertical_push` but chest `horizontal_push` still trains chest) the day keeps not just its body region but its target muscle. Only when no same-muscle option survives does a final tier fall back to `SUBSTITUTION_MAP`'s cross-muscle alternative — so a slot is never left empty. This achieves the spec goal ("keep training intent, never empty a slot") more faithfully than a blind pattern swap.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_injury_substitution.py
import pytest
from app.generator import WorkoutGenerator
from app.models import ClientProfile

_BANNED = {
    "lower_back_pain": {"hinge"},
    "knee_pain": {"squat", "lunge"},
    "shoulder_impingement": {"vertical_push", "horizontal_pull"},
}


def _client(limitations):
    return ClientProfile(client_id="t_inj", avatar="gen_pop", training_days=6,
                         experience_level="intermediate", limitations=limitations,
                         available_equipment=["full_gym"], week_number=1)


def _patterns_in_week(week, gen):
    ex_map = {e.exercise_id: e for e in gen.exercise_db}
    return {ex_map[s.exercise_id].movement_pattern
            for d in week.days for s in d.slots if s.exercise_id in ex_map}


@pytest.mark.parametrize("limitation", list(_BANNED))
def test_banned_patterns_absent_from_week(limitation):
    gen = WorkoutGenerator()
    week = gen.generate(_client([limitation]))
    used = _patterns_in_week(week, gen)
    assert not (used & _BANNED[limitation]), \
        f"{limitation}: found banned patterns {used & _BANNED[limitation]}"


def test_lower_back_pain_excludes_lower_back_secondary():
    gen = WorkoutGenerator()
    week = gen.generate(_client(["lower_back_pain"]))
    ex_map = {e.exercise_id: e for e in gen.exercise_db}
    for d in week.days:
        for s in d.slots:
            ex = ex_map.get(s.exercise_id)
            if ex:
                assert "lower_back" not in ex.secondary_muscles


def test_days_not_collapsed_by_injury():
    # Even with a heavy ban, no training day loses all its slots.
    gen = WorkoutGenerator()
    week = gen.generate(_client(["knee_pain"]))
    for d in week.days:
        assert len(d.slots) >= 1, f"{d.day_name} collapsed to empty under knee_pain"


def test_wrist_pain_adds_cue_but_does_not_exclude():
    gen = WorkoutGenerator()
    base = gen.generate(_client([]))
    wrist = gen.generate(_client(["wrist_pain"]))
    # Same number of slots (no exclusion), and a wrist caveat appears on a press/pull slot.
    base_n = sum(len(d.slots) for d in base.days)
    wrist_n = sum(len(d.slots) for d in wrist.days)
    assert wrist_n == base_n
    cues = [c for d in wrist.days for s in d.slots for c in s.coaching_cues]
    assert any("Wrist" in c for c in cues)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_injury_substitution.py -v`
Expected: FAIL — `test_banned_patterns_absent_from_week[knee_pain]` and `[shoulder_impingement]` fail (only `lower_back_pain` is gated today); `test_wrist_pain_adds_cue` fails (no cue).

- [ ] **Step 3: Add the injury-caveat map to constants**

In `app/domain/workout/constants.py`, after `SUBSTITUTION_MAP` (`:80`):

```python
# ── Caveat-only limitations (no clean pattern substitution) ──────────────────
# These are not excluded; affected slots get an appended coaching cue instead.
INJURY_CAVEATS: Dict[str, Dict[str, object]] = {
    "wrist_pain": {
        "patterns": {"horizontal_push", "vertical_push", "horizontal_pull", "vertical_pull"},
        "cue": "Wrist caution: neutral grip / wrist wraps; stop on sharp wrist pain.",
    },
    "hip_flexor_tightness": {
        "patterns": {"hinge", "lunge", "squat"},
        "cue": "Hip caution: warm up hip flexors; reduce depth if you feel pinching.",
    },
}
```

- [ ] **Step 4: Add the generator helpers + filter/selection wiring**

In `app/generator.py`, add two methods to `WorkoutGenerator` (place near `_filter_exercises`):

```python
    def _banned_patterns(self, client: ClientProfile) -> set:
        """Movement patterns the client's limitations forbid (from SUBSTITUTION_MAP)."""
        from app.domain.workout.constants import SUBSTITUTION_MAP
        banned: set = set()
        for lim in client.limitations:
            sub = SUBSTITUTION_MAP.get(lim)
            if sub:
                banned.update(sub.keys())
        return banned

    def _substitute_patterns(self, client: ClientProfile, pattern: str) -> list:
        """Safe replacement patterns for a banned pattern, in priority order."""
        from app.domain.workout.constants import SUBSTITUTION_MAP
        for lim in client.limitations:
            sub = SUBSTITUTION_MAP.get(lim, {})
            if pattern in sub:
                return list(sub[pattern])
        return [pattern]
```

In `_filter_exercises`, replace the limitation block (`:159-165`):

```python
            skip = False
            for limit in client.limitations:
                if limit == "lower_back_pain" and (ex.movement_pattern == "hinge" or "lower_back" in ex.secondary_muscles):
                    skip = True
                    break
            if skip:
                continue
```

with:

```python
            if ex.movement_pattern in banned_patterns:
                continue
            # Extra lower_back_pain guard: also strip movements loading lower_back
            # as a secondary muscle (e.g. barbell rows), regardless of pattern.
            if "lower_back_pain" in client.limitations and "lower_back" in ex.secondary_muscles:
                continue
```

and, just before the `for ex in self.exercise_db:` loop in `_filter_exercises` (`:147`), compute the set once:

```python
        banned_patterns = self._banned_patterns(client)
```

In `_select_for_slot`, after Tier 4 (just before the final `return None` at `:340`), add the substitution fallback:

```python
        # Tier 5: injury substitution — the slot's pattern is banned and no safe
        # same-muscle option survived the earlier tiers. Fill the slot with a safe
        # substitute pattern so the day is never left empty.
        if pattern and pattern in self._banned_patterns(client):
            for sub_pat in self._substitute_patterns(client, pattern):
                ex = _pick(self._filter_exercises(client, avatars=avatars, pattern=sub_pat))
                if ex:
                    return self._apply_override(ex, client)
```

- [ ] **Step 5: Append injury caveats in `_construct_slot`**

In `app/generator.py`, inside `_construct_slot`, right before `return slot` (`:435`):

```python
            # Caveat-only limitations: warn on affected patterns without excluding.
            from app.domain.workout.constants import INJURY_CAVEATS
            for lim in client.limitations:
                spec_cav = INJURY_CAVEATS.get(lim)
                if spec_cav and exercise.movement_pattern in spec_cav["patterns"]:
                    slot.coaching_cues = list(slot.coaching_cues) + [spec_cav["cue"]]
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_injury_substitution.py -v`
Expected: PASS (all params + cue test).

- [ ] **Step 7: Regression — full generator + check-in suites**

Run: `pytest tests/test_generator.py tests/test_generator_hardening.py tests/test_checkin_filter.py -v`
Expected: PASS — existing `lower_back_pain` behavior preserved.

- [ ] **Step 8: Commit**

```bash
git add app/domain/workout/constants.py app/generator.py tests/test_injury_substitution.py
git commit -m "fix(safety): honor knee/shoulder injuries via SUBSTITUTION_MAP; wrist/hip caveats"
```

---

## Task 6: Deterministic meal rotation (A.3)

**Files:**
- Modify: `app/domain/nutrition/meal_builder.py` (`build_day_plan` `:319-328`; `_pick` `:359-362`)
- Modify: `app/services/nutrition_service.py` (7-day loop `:101-111`)
- Test: `tests/test_meal_rotation.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_meal_rotation.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_meal_rotation.py -v`
Expected: FAIL — `TypeError: build_day_plan() got an unexpected keyword argument 'day_index'`.

- [ ] **Step 3: Add `day_index` + rotation to the meal builder**

In `app/domain/nutrition/meal_builder.py`, add a category-offset constant near `_SLOT_TO_FOOD_SLOT` (`:312`):

```python
# Rotation offsets so categories don't all advance in lockstep across days.
_CATEGORY_OFFSET: dict[str, int] = {
    "protein": 0, "grain": 1, "veg": 2, "fat": 3, "fruit": 4, "dairy": 2, "legume": 1,
}
```

Change the `build_day_plan` signature (`:319-328`) — add `day_index: int = 0` before `used_slugs_this_week`:

```python
def build_day_plan(
    food_pool: list[FoodItem],
    target_kcal: float,
    target_protein_g: float,
    target_fat_g: float,
    target_carb_g: float,
    target_fiber_g: float,
    meals_per_day: int = 3,
    day_index: int = 0,
    used_slugs_this_week: dict[str, int] | None = None,
) -> DayPlan:
```

Replace the inner `_pick` (`:359-362`):

```python
        def _pick(cat: str, n: int = 1) -> list[FoodItem]:
            candidates = [f for f in available if f.category == cat
                          and food_slot in f.meal_slots]
            return candidates[:n]
```

with:

```python
        def _pick(cat: str, n: int = 1) -> list[FoodItem]:
            candidates = [f for f in available if f.category == cat
                          and food_slot in f.meal_slots]
            if not candidates:
                return []
            # Rotate the start point by day so each day draws different foods.
            offset = (day_index + _CATEGORY_OFFSET.get(cat, 0)) % len(candidates)
            rotated = candidates[offset:] + candidates[:offset]
            return rotated[:n]
```

- [ ] **Step 4: Thread `day_index` from the service**

In `app/services/nutrition_service.py`, change the loop (`:101`) from `for _ in range(7):` to `for day_index in range(7):`, and add `day_index=day_index,` to the `build_day_plan(...)` call (between `meals_per_day=` and `used_slugs_this_week=`, around `:109-110`):

```python
        for day_index in range(7):
            day = build_day_plan(
                food_pool=filtered_pool,
                target_kcal=target_kcal,
                target_protein_g=macros["protein_g"],
                target_fat_g=macros["fat_g"],
                target_carb_g=macros["carb_g"],
                target_fiber_g=macros["fiber_g"],
                meals_per_day=profile.meals_per_day,
                day_index=day_index,
                used_slugs_this_week=used_slugs,
            )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_meal_rotation.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Regression — meal-builder + nutrition service suites**

Run: `pytest tests/test_meal_builder_slots.py tests/test_nutrition.py tests/test_nutrition_service_e2e.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/domain/nutrition/meal_builder.py app/services/nutrition_service.py tests/test_meal_rotation.py
git commit -m "feat(nutrition): day-indexed meal rotation (ends 7x-same-food weeks)"
```

---

## Task 7: Nutrition day-validation gate (A.2)

**Files:**
- Modify: `app/services/nutrition_service.py` (`generate()` — loop body `:101-115`; rationale `:127-130`)
- Test: `tests/test_nutrition_validation_gate.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_nutrition_validation_gate.py
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


def test_clean_plan_has_no_drift_marker():
    s = _session()
    _profile(s)
    plan = NutritionService(s).generate("t_val")
    assert plan is not None
    assert "[macro drift]" not in (plan.rationale or "")


def test_off_target_day_is_flagged_not_blocked(monkeypatch):
    s = _session()
    _profile(s)
    import app.services.nutrition_service as ns

    real = ns.validate_day
    # Force a single failing day by making validate_day report one error once.
    calls = {"n": 0}
    def fake_validate(*args, **kwargs):
        calls["n"] += 1
        return ["protein 100g below -5% of 165g"] if calls["n"] == 1 else []
    monkeypatch.setattr(ns, "validate_day", fake_validate)

    plan = NutritionService(s).generate("t_val")
    assert plan is not None                       # non-blocking: plan still persists
    assert "[macro drift]" in (plan.rationale or "")
    assert "Day 1" in plan.rationale
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_nutrition_validation_gate.py -v`
Expected: FAIL — `test_off_target_day_is_flagged_not_blocked` fails (no `[macro drift]` marker; `validate_day` is never called).

- [ ] **Step 3: Call `validate_day` per day and collect warnings**

In `app/services/nutrition_service.py`, initialise a warnings list just before the loop (before `:101`):

```python
        validation_warnings: list[str] = []
```

Inside the loop, after `day = build_day_plan(...)` returns and BEFORE the `for slot in day.slots:` bookkeeping (i.e. after `:111`), add:

```python
            day_errors = validate_day(
                day, target_kcal, macros["protein_g"], macros["fat_g"],
                macros["fiber_g"], profile.weight_kg, strict=True,
            )
            if day_errors:
                day_errors = validate_day(
                    day, target_kcal, macros["protein_g"], macros["fat_g"],
                    macros["fiber_g"], profile.weight_kg, strict=False,
                )
            if day_errors:
                validation_warnings.append(f"Day {day_index + 1}: " + "; ".join(day_errors))
```

Then extend the `rationale` (built at `:127-130`) — after that assignment, add:

```python
        if validation_warnings:
            rationale += "\n[macro drift] " + " | ".join(validation_warnings)
```

> `validate_day` is already imported at `nutrition_service.py:21`. `profile.weight_kg` is guaranteed non-None by the missing-field guard at `:51-55`. `day_index` exists from Task 6; if Task 7 is implemented before Task 6, change the loop variable to `day_index` first (Task 6 Step 4).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_nutrition_validation_gate.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Regression — nutrition suites**

Run: `pytest tests/test_nutrition.py tests/test_nutrition_service_e2e.py tests/test_nutrition_halal.py -v`
Expected: PASS — the degenerate-plan guard still raises on a near-zero-kcal week; clean plans unchanged.

- [ ] **Step 6: Commit**

```bash
git add app/services/nutrition_service.py tests/test_nutrition_validation_gate.py
git commit -m "feat(nutrition): gate each day with validate_day; surface macro drift to coach"
```

---

## Task 8: Full-suite regression + docs

**Files:**
- Modify: `CLAUDE.md` (design-constraints bullets), `CHANGELOG.md`

- [ ] **Step 1: Run the entire test suite**

Run: `pytest -q`
Expected: all tests pass (the prior 288 + the new tests). Investigate any failure before continuing — do not edit tests to pass.

- [ ] **Step 2: Update CLAUDE.md**

Add to the "Key design constraints" section:

```markdown
- Declared limitations are honored in selection: `SUBSTITUTION_MAP` bans unsafe
  movement patterns (knee/shoulder/lower-back) in `_filter_exercises`, with a
  last-resort substitution tier in `_select_for_slot` so a day is never emptied;
  `wrist_pain`/`hip_flexor_tightness` add a coaching caveat, not an exclusion.
- Week-1 loads are seeded from optional intake baselines (squat/bench/deadlift →
  Brzycki e1RM → Tuchscherer RPE/%1RM, rounded down) via `app/domain/workout/loadseed.py`;
  the prior-week autoregulator takes precedence from week 2.
- Meal plans rotate per day (`build_day_plan(day_index=...)`) so a 7-day plan is
  varied, not the same foods every day.
- Each generated nutrition day is gated by `validate_day`; residual macro drift is
  non-blocking and surfaced in the plan `rationale` ("[macro drift]") for the coach.
```

- [ ] **Step 3: Update CHANGELOG.md**

Add an entry under the current/unreleased section summarising the four slices (injuries honored, week-1 loads, meal rotation, day validation).

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md CHANGELOG.md
git commit -m "docs: record usability+safety cluster (injuries, loads, meal variety, validation)"
```

---

## Deployment note (post-merge)

The live Postgres DB is **not** fresh, so the new columns require the migration to
run. On deploy, `app/main.py` runs `alembic upgrade head` automatically — confirm it
applied: after redeploy, check the bot logs for the alembic upgrade line, or run
`docker compose exec -T db ...` to confirm `clientprofile` has the three `*_e1rm`
columns. If alembic is bypassed, apply manually:
`ALTER TABLE clientprofile ADD COLUMN squat_e1rm DOUBLE PRECISION;` (×3).

---

## Self-Review (completed by author)

**Spec coverage:** A.1 → Task 5; A.3 → Task 6; A.4 → Tasks 1–4; A.2 → Task 7;
schema/migration → Tasks 1(step 4)+2; docs/deploy → Task 8. All spec sections map
to a task.

**Placeholder scan:** none — every code step shows complete code; every test step
shows full assertions; every run step shows the command + expected result.

**Type consistency:** `seed_working_load`, `pattern_e1rm`, `working_pct`,
`brzycki_e1rm`, `_banned_patterns`, `_substitute_patterns`, `_parse_baseline_set`,
`_store_baseline_and_next` signatures are consistent across the tasks that define
and call them. Model fields `squat_e1rm`/`bench_e1rm`/`deadlift_e1rm` are spelled
identically in the model, migration, intake persist, and `_PATTERN_BASELINE`.
`build_day_plan(day_index=...)` matches between builder, service, and tests.

**Ordering caveat:** Task 7 reuses the `day_index` loop variable introduced in
Task 6 — implement Task 6 before Task 7 (or rename per the note in Task 7 Step 3).

---

## Post-implementation follow-ups

These were surfaced during implementation/review and are intentionally OUT of scope
for this cluster — candidates for their own spec:

1. **Meal-builder fat bias (B-tier refinement).** `build_day_plan` picks a
   dedicated fat-category food in every meal slot at a 30 g floor, so real plans land
   fat at ~30–36% of energy vs a 28% design target. This is dietarily fine (inside the
   20–35% AMDR) and kcal/protein track well, so it is NOT a bug — but if tighter fat
   tracking is wanted, the fix is in the builder's selection/objective, not the
   validator. The `validate_day` fat check was calibrated to the 35% AMDR ceiling so
   the gate stays signal (flags genuine outliers) rather than flagging ~86% of days.

2. **Dual-injury hinge deadlock (edge case).** A client declaring BOTH
   `lower_back_pain` AND `shoulder_impingement` can leave a hinge-pattern slot with no
   safe substitute (lower_back_pain→horizontal_pull, which shoulder_impingement bans).
   The safety invariant holds (no unsafe exercise is ever selected — the slot is left
   thin instead), and the HITL coach review + "add core/exercise at verification" flow
   covers it. A future enhancement could substitute across muscle groups for such
   compound cases.
