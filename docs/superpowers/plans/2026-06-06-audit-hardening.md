# Beyond Fit — Audit Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Use superpowers:test-driven-development for every behavior change.

**Goal:** Fix the 29 confirmed-real bugs (4 critical) from the 43-agent audit and reshape nutrition to the owner's halal-only, single-balanced-diet model — leaving the app safe, correct, and ready to ship.

**Architecture:** Edit in place on a `fix/audit-hardening` branch off current HEAD (`bot-only-deploy`). Seven phases, each a self-contained, test-green commit, then one PR. No new unsourced food/exercise macros. Nutrition simplification is mostly deletion: collapse `diet_style` to balanced, drop the (halal-violating) pork item, retire the dead religious filter, make the medical filter safe.

**Tech Stack:** Python 3.12, FastAPI, SQLModel, python-telegram-bot, Jinja2/WeasyPrint, Flutter/Dart (mobile), pytest. LLM via OpenRouter.

**Baseline (verified):** 230 tests pass; 179 exercises; 68 foods. CLAUDE.md "known gaps" list is STALE — do not trust it; trust live code. Full findings: `AUDIT_REPORT.md`.

**Owner constraints (see memory `nutrition-product-constraints`):**
- Halal-only product — no non-halal foods exist; do NOT build a religious filter.
- One diet style: **balanced**. No vegan / vegetarian / pescatarian / keto / FODMAP as selectable styles.
- Low-carb is goal-integrated (fat-loss leans lower-carb inside the balanced plan), never a separate style.

---

## File Structure (what each change touches)

| Area | Files |
|---|---|
| Security | `app/settings.py`, `app/auth/jwt.py`, `app/auth/deps.py`, `app/routes.py`, `app/bot.py`, `app/api/profile.py` |
| Nutrition | `app/domain/nutrition/food_db.py`, `app/domain/nutrition/meal_builder.py`, `app/services/nutrition_service.py`, `app/bot.py` (diet intake), `app/models.py` (comments) |
| Workout engine | `app/generator.py`, `app/domain/workout/autoregulation.py`, `app/domain/workout/constants.py` |
| PDF + mobile | `app/adapters/pdf/templates/sections/shopping_list.html.j2`, `app/adapters/pdf/templates/partials/_meal_card.html.j2`, `app/adapters/pdf/renderer.py`, `mobile/lib/features/coach/coach_review_screen.dart` |
| Bot/LLM robustness | `app/bot.py` (checkin, lift catalog), `app/api/coach.py`, `app/services/llm_service.py` |
| Data quality | `app/exercise_db.py`, `app/domain/nutrition/food_db.py` |
| Tests | `tests/test_*.py` (new + amended) |

---

## Phase 0: Branch

- [ ] **Step 1: Create the working branch off current HEAD**

```bash
git checkout -b fix/audit-hardening
git status   # expect clean tree on fix/audit-hardening
```

- [ ] **Step 2: Record the green baseline**

```bash
pytest -q 2>&1 | tail -3   # expect "230 passed"
```

---

## Phase 1: Security (4 critical/high) → commit `fix(sec): ...`

### Task 1: JWT secret must not run on the public placeholder

**Files:** Modify `app/settings.py` (`auth_secret_key` ~line 58); Test: `tests/test_settings_security.py` (create).

The default is `"change-me-in-production"`. Anyone who reads the repo can forge admin/coach JWTs. Fail fast when the placeholder is used outside tests/dev.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_settings_security.py
import pytest
from app.settings import Settings

def test_default_secret_rejected_when_env_is_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(ValueError, match="auth_secret_key"):
        Settings(auth_secret_key="change-me-in-production").require_secure_secret()

def test_custom_secret_passes(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    Settings(auth_secret_key="a-real-32char-minimum-secret-value!!").require_secure_secret()
```

- [ ] **Step 2: Run it, expect fail** — `pytest tests/test_settings_security.py -v` → FAIL (no `require_secure_secret`).

- [ ] **Step 3: Implement** — add to `Settings` a field `app_env: str = "dev"` (read from `APP_ENV`) and method:

```python
def require_secure_secret(self) -> None:
    insecure = {"change-me-in-production", "", None}
    if self.app_env.lower() in {"production", "prod"} and (
        self.auth_secret_key in insecure or len(self.auth_secret_key) < 32
    ):
        raise ValueError(
            "auth_secret_key is the insecure default or too short; set a strong AUTH_SECRET_KEY in production."
        )
```

Call `get_settings().require_secure_secret()` in the FastAPI lifespan startup (`app/main.py`) and at bot startup (`app/bot.py` main) so a misconfigured prod deploy refuses to boot. Keep dev/test default working.

- [ ] **Step 4: Run, expect pass.** **Step 5:** do not commit yet (batch at end of phase).

### Task 2: Access-token verifier must reject non-access tokens

**Files:** Modify `app/auth/jwt.py` (`create_access_token` line 31-33, `decode_token` 41-47); check callers in `app/auth/deps.py`; Test: `tests/test_jwt_token_types.py` (create).

`decode_token` accepts ANY validly-signed token. A refresh/reset/verify token is therefore usable as an access token (type confusion).

- [ ] **Step 1: Failing test**

```python
# tests/test_jwt_token_types.py
from app.auth import jwt as J

def test_access_token_roundtrips():
    t = J.create_access_token("user-1")
    assert J.decode_token(t) == "user-1"

def test_refresh_token_rejected_as_access():
    t = J.create_refresh_token("user-1")
    assert J.decode_token(t) is None

def test_reset_token_rejected_as_access():
    t = J.create_reset_token("user-1")
    assert J.decode_token(t) is None
```

- [ ] **Step 2: Expect fail** (refresh/reset currently decode to "user-1").

- [ ] **Step 3: Implement** — stamp access tokens and check type:

```python
def create_access_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode({"sub": subject, "exp": expire, "type": "access"}, _secret_key(), algorithm=ALGORITHM)

def decode_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, _secret_key(), algorithms=[ALGORITHM])
        if payload.get("type") != "access":
            return None
        return payload.get("sub")
    except JWTError:
        return None
```

Note: existing access tokens in the wild become invalid (acceptable — forces re-login). Verify no test signs a token by hand without `type`.

- [ ] **Step 4: pass.** Run full `pytest -q` to catch any auth-dependent test that relied on the loose behavior; fix those tests to use `create_access_token`.

### Task 3: Gate the unauthenticated `/generate*` routes

**Files:** Modify `app/routes.py` (lines 28-55); use `app/auth/deps.py` dependency; Test: `tests/test_generate_auth.py` (create).

`/generate` and `/generate_and_coach` accept an arbitrary `ClientProfile` body with no auth. Add the same auth dependency the other API routers use (find it in `app/auth/deps.py`, e.g. `get_current_user`/`require_*`). The authenticated subject's `client_id` should override the body to prevent acting as another client.

- [ ] **Step 1: Failing test** — POST `/generate` with no Authorization header expects 401:

```python
# tests/test_generate_auth.py
def test_generate_requires_auth(client):   # `client` = TestClient fixture from conftest
    r = client.post("/generate", json={"avatar": "gen_pop", "training_days": 3,
                                       "experience_level": "beginner"})
    assert r.status_code in (401, 403)
```

- [ ] **Step 2: Expect fail** (currently 200). **Step 3:** add `current=Depends(get_current_user)` to both routes; if the dependency name differs, match the one used in `app/api/plans.py`. **Step 4:** pass.

### Task 4: Authorize bot nutrition-approve / discard / safety-clear

**Files:** Modify `app/bot.py` — `handle_nutrition_approve`, `handle_nutrition_discard`, `handle_safety_clear`; reuse `auth_roles.is_super_admin(...)` and the coach-scope helper (`profile.assigned_coach_id == user_id`); Test: `tests/test_bot_authz.py` (create).

These handlers mutate plan/safety state with no caller check. `handle_safety_clear` clears a MEDICAL safety gate — any user can call it.

- [ ] **Step 1: Failing test** — call each handler with a non-admin, non-coach `effective_user.id`; assert it refuses (no state change, sends a denial). Model it on existing `tests/test_coach_scope.py` patterns (mock `Update`/`Context`).

- [ ] **Step 2: Expect fail.** **Step 3:** at the top of each handler add the same guard used by other admin handlers:

```python
uid = update.effective_user.id
if not (auth_roles.is_super_admin(uid) or _is_assigned_coach_of_target(uid, target_client_id)):
    await query.answer("Not authorized", show_alert=True)
    return
```

Use the existing coach-scope check (`app/auth/roles.py`) — do not invent a new one. **Step 4:** pass.

### Task 5: Scrub PII on account deletion

**Files:** Modify `app/api/profile.py` (delete handler ~93-125); Test: `tests/test_account_delete_pii.py` (create).

Deletion leaves recoverable email/name in `ProfileSnapshot.snapshot_json` and `Feedback`. Null/anonymize those on delete.

- [ ] **Step 1: Failing test** — create client with email `a@b.com`, a snapshot, a feedback row; call delete; assert no row anywhere still contains `a@b.com`.

- [ ] **Step 2: Expect fail.** **Step 3:** in the delete handler, before/after removing the profile, overwrite `ProfileSnapshot.snapshot_json` for that client with a redacted blob (drop email/name) and null PII columns on `Feedback`. **Step 4:** pass.

- [ ] **Phase 1 commit:**
```bash
pytest -q && git add -A && git commit -m "fix(sec): enforce secure JWT secret, reject token-type confusion, gate /generate, authz bot safety/nutrition handlers, scrub PII on delete"
```

---

## Phase 2: Nutrition correctness (2 critical) → commit `fix(nutrition): ...`

### Task 6: Make the catalog actually halal; retire the dead religious filter

**Files:** Modify `app/domain/nutrition/food_db.py` (remove `pork_tenderloin` line ~33; fix `egan` tag on `chicken_breast` line 18 — see Task 23 may merge here; update docstring "~150 items" → real count); Modify `app/domain/nutrition/meal_builder.py` (remove the inert `religious_restrictions` branch lines 102-103) and `app/services/nutrition_service.py` (stop passing `religious_restrictions`); Test: `tests/test_nutrition_halal.py` (create).

- [ ] **Step 1: Failing test**

```python
# tests/test_nutrition_halal.py
from app.domain.nutrition.food_db import get_food_db

def test_catalog_contains_no_pork():
    names = " ".join(f.name.lower() for f in get_food_db())
    assert "pork" not in names and "bacon" not in names and "ham " not in names

def test_no_garbage_diet_tags():
    valid = {"omnivore", "keto", "gluten_free", "vegan", "vegetarian", "pescatarian"}
    for f in get_food_db():
        for t in f.diet_tags:
            assert t in valid, f"{f.slug} has junk diet tag {t!r}"
```

(Note: `keto`/`vegan` tags may remain on foods as harmless metadata even though those styles are not user-selectable; the test just forbids GARBAGE like `egan`.)

- [ ] **Step 2: Expect fail** (pork present; `egan` junk). **Step 3:** delete the `pork_tenderloin` FoodItem; rewrite the chicken_breast diet_tags literal to `["omnivore","keto","gluten_free"]` (plain list, no string slicing); remove the `religious_restrictions` filter branch and its argument plumbing; correct the docstring count. **Step 4:** pass.

### Task 7: Medical filter must never yield an empty pool / 0-kcal plan (SAFETY GUARD ONLY)

**Files:** Modify `app/domain/nutrition/meal_builder.py` (`filter_food_pool` medical branch 109-114) and `app/services/nutrition_service.py` (guard before persisting, ~85-115); Test: `tests/test_nutrition_medical.py` (create).

Today: `hypertension`/`type2_diabetes` filter on `medical_tags`/`low_sodium`/`low_sugar` which are set on **0 of 68** foods → empty pool → a persisted 7-day 0-kcal plan.

**DECISION (advisor + owner scope):** Do **NOT** manufacture `medical_tags`. The food DB has no sodium field — any `low_sodium` tag would be a guess, and inventing medical data is the most dangerous possible gold-plating. The owner never asked for medical handling. Ship ONLY the safety guard.

- [ ] **Step 1: Failing test**

```python
# tests/test_nutrition_medical.py
from app.domain.nutrition.meal_builder import filter_food_pool
from app.domain.nutrition.food_db import get_food_db

def test_medical_filter_never_empties_pool():
    for cond in (["hypertension"], ["type2_diabetes"], ["hypertension", "type2_diabetes"]):
        pool = filter_food_pool(pool=get_food_db(), medical_conditions=cond)
        assert len(pool) >= 10, f"{cond} produced a {len(pool)}-food pool"
```

- [ ] **Step 2: Expect fail** (0-food pool). **Step 3:** graceful-degrade fix only:
  1. In `filter_food_pool`, make the medical branch degrade like the soft filters: if applying a condition drops the pool below a safe minimum (e.g. < 10 items), keep the pre-condition (full balanced) pool and append a coach-surfaced warning string instead of emptying it. (Since no food is medically tagged today, this means medical conditions currently fall back to the full balanced pool + a flag — correct and safe.)
  2. Add a guard in `nutrition_service` so a day/plan whose kcal rounds to ~0 is **NEVER** persisted — raise/skip with a log + coach flag.
- [ ] **Step 4: pass.** Tag `low_sugar`/`low_sodium` is explicitly OUT of scope; if the owner later wants real medical handling it needs sourced sodium/sugar data.

### Task 8: Collapse `diet_style` to balanced-only

**Files:** Modify `app/bot.py` `_dn_ask_diet_style` (lines 3299-3316) to offer only Balanced (or remove the step and auto-set `diet_style="balanced"`); update `app/models.py:186` comment; meal_builder already treats `balanced` as a no-op (line 104) so no filter change needed; Test: amend `tests/test_nutrition.py` / add `tests/test_diet_style_balanced.py`.

- [ ] **Step 1: Failing test** — assert the diet-style keyboard exposes only `balanced` (no `vegan`/`keto`/`pescatarian` callbacks):

```python
def test_diet_picker_offers_only_balanced():
    import app.bot as bot
    # call _dn_ask_diet_style with a fake query, capture reply_markup
    # assert all callback_data are "dn_diet_balanced"
```

- [ ] **Step 2: Expect fail.** **Step 3:** reduce the keyboard to a single Balanced button (or skip straight to the next step setting `diet_style="balanced"`). Keep the `dn_diet_style` handler accepting `balanced`. **Step 4:** pass. Verify the meal-build path still produces a valid plan with `diet_style="balanced"`.

### Task 9: Confirm low-carb is goal-integrated (no new style)

**Files:** Verify `app/domain/nutrition/macros.py` (no change expected — fat-loss already uses higher protein 2.2 g/kg + remainder carbs, which leans lower-carb at a deficit); Test: `tests/test_macros_goal.py` (create) to lock the behavior.

- [ ] **Step 1: Test** — assert `calculate_macros` for `fat_loss` yields a lower carb_g (as % kcal) than `bulk` at the same weight/kcal, and carbs never go negative.

```python
from app.domain.nutrition.macros import calculate_macros
def test_fat_loss_is_lower_carb_than_bulk():
    cut = calculate_macros(1800, 80, "fat_loss")
    bulk = calculate_macros(1800, 80, "bulk")
    assert cut["carb_g"] < bulk["carb_g"]
    assert cut["carb_g"] >= 0
```

- [ ] **Step 2-3:** Should PASS as-is; if not, adjust the goal map minimally. Document that low-carb = the fat_loss macro profile, not a diet_style.

- [ ] **Phase 2 commit:**
```bash
pytest -q && git add -A && git commit -m "fix(nutrition): halal-only catalog, safe medical filter (no 0-kcal plans), single balanced diet style, goal-integrated low-carb"
```

---

## Phase 3: Workout engine correctness (3 high + gaps) → commit `fix(generator): ...`

> **EXECUTION NOTES (advisor):**
> - **Measure before asserting.** Do NOT hardcode set-count thresholds. Run the generator first, print the actual achievable floor for the combo, then assert to *that* value. Invented numbers (≥8 sets, max−min≤3) risk unsatisfiable tests.
> - **One worker for all of Phase 3.** T10/T11/T12/T14 all mutate `app/generator.py` and interact (budget × splits × min-slots). Do them sequentially, not as parallel subagents.
> - **pytest-golden is active.** These changes will churn generator golden snapshots. Read each golden diff to confirm it's the intended change, then regenerate — never blind-regenerate, never treat churn as failure.
> - **T14 bodyweight-only caveat.** If a muscle has NO bodyweight option, the ≥2-slot assertion is unsatisfiable without adding exercises (unauthorized). Relax T14 to "no EMPTY days (≥1 slot) and no day below the measured achievable floor for its equipment set", and surface any bodyweight coverage hole to the owner instead of forcing content.

### Task 10: Powerlifter splits/pool — no thin days

**Files:** Modify `app/generator.py` `_resolve_split` (76-98) add powerlifter 5/6-day templates; `_filter_exercises` (136-179) let powerlifter accept powerbuilder exercises for NON-main slots; Test: `tests/test_generator_powerlifter.py` (create).

Root cause (verified): only 30/179 exercises are powerlifter-tagged, 4 of them low-fatigue → advanced powerlifter 5/6-day collapses to 2-slot days with recurring Barbell Shrug. The pool fix is load-bearing; templates are secondary.

- [ ] **Step 1: Failing test**

```python
# tests/test_generator_powerlifter.py
from app.generator import WorkoutGenerator
from app.models import ClientProfile

def _gen(days):
    c = ClientProfile(avatar="powerlifter", training_days=days,
                      experience_level="advanced", available_equipment=["full_gym"])
    return WorkoutGenerator().generate(c)

def test_powerlifter_days_have_no_thin_days():
    for d in (3, 4, 5, 6):
        wk = _gen(d)
        for day in wk.days:
            assert len(day.slots) >= 3, f"{d}-day plan has thin day {day.name} ({len(day.slots)})"
```

- [ ] **Step 2: Expect fail.** **Step 3:** in `_filter_exercises`, replace the strict `client.avatar not in ex.avatar_tags` gate for accessory/isolation selection so a powerlifter also draws from powerbuilder-tagged accessories (keep competition-lift selection powerlifter-specific for the main_compound). Add 5/6-day powerlifter templates so structure is coherent. **Step 4:** pass; also assert no day repeats the same exercise_id and main compounds still appear.

### Task 11: Weekly volume budget — divide across repeated day-types

**Files:** Modify `app/generator.py` (`generate` budget build ~471 and `_spend_budget`/`_fill_slots` 193-200, 416-419); Test: `tests/test_generator_budget.py` (create).

Budget built once/week and consumed greedily in day order → later occurrences of a repeated day (6-day PPL Push#2, Pull#2) get starved to non-training volume.

- [ ] **Step 1: Failing test**

```python
# tests/test_generator_budget.py
def test_repeated_day_types_get_balanced_volume():
    c = ClientProfile(avatar="gen_pop", training_days=6, experience_level="beginner",
                      available_equipment=["full_gym"])
    wk = WorkoutGenerator().generate(c)
    pushes = [d for d in wk.days if d.name.startswith("Push")]
    sets = [sum(s.sets for s in d.slots) for d in pushes]
    assert max(sets) - min(sets) <= 3, f"Push days unbalanced: {sets}"
    for d in wk.days:
        assert sum(s.sets for s in d.slots) >= 8, f"{d.name} below trainable volume"
```

- [ ] **Step 2: Expect fail.** **Step 3:** before filling, count how many days train each muscle/group and divide each weekly cap by that count (ceil), or fill round-robin so repeated day-types share evenly. **Step 4:** pass; verify weekly per-muscle totals still respect the cap (sum across days ≈ original budget).

### Task 12: Cap AutoRegulator weekly load jump

**Files:** Modify `app/generator.py` `AutoRegulator.calculate_next_load` (30-46); Test: `tests/test_autoregulator_cap.py` (create).

The live path is uncapped (up to +20%/wk) while the check-in `derive_plan_delta` path caps at ±10%. Align them.

- [ ] **Step 1: Failing test**

```python
# tests/test_autoregulator_cap.py
from app.generator import AutoRegulator
def test_weekly_jump_capped_at_10pct():
    nxt = AutoRegulator.calculate_next_load(last_weight=100, last_target_rpe=8,
                                            last_actual_rpe=5, next_target_rpe=8)
    assert nxt <= 110.0 + 1e-6     # never more than +10%
    down = AutoRegulator.calculate_next_load(100, 8, 10, 8)
    assert down >= 90.0 - 1e-6     # never less than -10%
```

- [ ] **Step 2: Expect fail** (currently can exceed). **Step 3:** clamp the final returned weight to `[0.90*last_weight, 1.10*last_weight]` before rounding to plate. **Step 4:** pass.

### Task 13: ~~Program core~~ — DEFERRED (coaching preference, not a bug)

**DECISION (advisor):** The engine deliberately never programs core. Forcing core onto every plan changes every plan's structure and is a coaching opinion the owner did NOT ask for — it is not a defect. **Do not implement as a "fix."** Surface to the owner as a one-line question in the final summary: "Want core/abs programmed into every plan? (currently never programmed by design)". Skip the budget-key de-aggregation too unless a measured test (Task 11) shows a head is starved to ZERO across the whole week — only then treat that specific starvation as a bug.

### Task 14: Minimum-slot guarantee (defensive)

**Files:** Modify `app/generator.py` `_fill_slots`; Test: `tests/test_generator_min_slots.py` (create).

Guarantee no training day is emitted with < 2 slots for any valid `(avatar, days, experience, equipment)` combo (belt-and-suspenders after Tasks 10/11).

- [ ] **Step 1: Failing test** — sweep ALL combos: avatars × days(2-6) × experience(3) × equipment(full_gym, dumbbells-only, bodyweight-only); assert every day has ≥2 slots and no empty days.

```python
import itertools
def test_no_empty_days_across_all_combos():
    avatars = ["gen_pop", "powerbuilder", "powerlifter"]
    eqs = [["full_gym"], ["dumbbells", "bench"], ["bodyweight"]]
    for a, d, e, eq in itertools.product(avatars, range(2,7),
                                         ["beginner","intermediate","advanced"], eqs):
        c = ClientProfile(avatar=a, training_days=d, experience_level=e, available_equipment=eq)
        wk = WorkoutGenerator().generate(c)
        for day in wk.days:
            assert len(day.slots) >= 2, f"{a}/{d}d/{e}/{eq} -> {day.name} has {len(day.slots)} slots"
```

- [ ] **Step 2: Expect fail** for at least bodyweight-only / powerlifter combos. **Step 3:** in slot filling, if a slot can't be filled by the strict filter, relax (drop avatar restriction for accessories, then drop bio_focus, then allow any matching pattern) before emitting a thin day; if still impossible (e.g. bodyweight-only for a machine-only muscle) substitute the closest bodyweight option. **Step 4:** pass the whole sweep.

- [ ] **Phase 3 commit:**
```bash
pytest -q && git add -A && git commit -m "fix(generator): powerlifter pool/splits, balanced repeated-day volume, capped weekly load jump, program core, no-empty-day guarantee"
```

---

## Phase 4: PDF + mobile render → commit `fix(pdf): ...`

### Task 15: Shopping list field name

**Files:** Modify `app/adapters/pdf/templates/sections/shopping_list.html.j2:14` (`item.total_g` → `item.total_grams`); Test: covered by Task 17.

- [ ] **Step 1:** change `{{ item.total_g | ... }}` to `{{ item.total_grams | ... }}` (renderer builds `total_grams`, renderer.py:236/241). **Step 2:** verified by the realistic PDF test (Task 17).

### Task 16: Meal-card item iteration

**Files:** Inspect `app/adapters/pdf/renderer.py` (how meal slots/items are passed to the template) and `app/adapters/pdf/templates/partials/_meal_card.html.j2:14`; Test: Task 17.

`{% for food, grams in slot.items %}` crashes if `slot` is a dict (`.items` resolves to the dict method) or if items aren't 2-tuples. Make the renderer pass slot items as an explicit list of objects/tuples and the template iterate a named key (e.g. `slot.foods` with `.name`/`.grams`), so it never collides with `dict.items`.

- [ ] **Step 1:** trace the exact structure the renderer hands the template. **Step 2:** align template ↔ renderer on a non-colliding key and 2-field rows. **Step 3:** verified by Task 17.

### Task 17: Realistic nutrition PDF fixture (catches 15 & 16)

**Files:** Modify `tests/test_pdf.py` (100-119) to render a PDF from a REAL `nutrition_service` plan (or a fixture matching its real shape), not the simplified stub that hides the crashes.

- [ ] **Step 1: Failing test** — build a plan via the real nutrition path (balanced, 4 meals) and render the full PDF; assert it produces non-empty bytes and the nutrition section is present.

```python
def test_full_pdf_renders_with_real_nutrition_plan():
    # build profile -> nutrition_service plan -> renderer.render(...)
    pdf = render_full_plan(workout_week, nutrition_plan)
    assert pdf and len(pdf) > 1000
```

- [ ] **Step 2: Expect fail** (KeyError/UndefinedError before Tasks 15/16). **Step 3:** Tasks 15+16 make it pass. **Step 4:** pass; also render a sparse plan (deload week, 0 meals if possible) to confirm no template crash on thin data.

### Task 18: Mobile coach-review exercise names show `?`

**Files:** Modify `mobile/lib/features/coach/coach_review_screen.dart:349` (and the model mapping it reads); Test: dart widget test if a harness exists, else manual-verify note in PR.

Names render as `?` — likely a field-name mismatch between the dart model and the API payload (e.g. `exercise_name` vs `name`).

- [ ] **Step 1:** read line 349 + the model; identify the wrong key. **Step 2:** map to the actual API field returned by `app/api/coach.py`. **Step 3:** if a Flutter test harness exists (`mobile/test/`), add a widget/model test asserting a known exercise name renders; otherwise document the before/after in the PR and verify against a sample payload.

- [ ] **Phase 4 commit:**
```bash
pytest -q && git add -A && git commit -m "fix(pdf): repair nutrition meal-card/shopping-list render, realistic PDF test; fix(mobile): coach-review exercise names"
```

---

## Phase 5: Bot/LLM robustness → commit `fix(bot): ...`

### Task 19: Check-in extraction failure must not silently advance the week

**Files:** Modify `app/bot.py` check-in completion (~2736-2790); Test: `tests/test_checkin_extraction_failure.py` (create).

On extraction failure the bot advances `week_number` and discards the client's telemetry with no error shown.

- [ ] **Step 1: Failing test** — mock the extractor to raise/return empty; drive the check-in completion; assert the week is NOT advanced, telemetry is preserved, and the user is told to retry.

- [ ] **Step 2: Expect fail.** **Step 3:** wrap extraction; on failure, keep the current `WorkoutHistory` row, do not increment week, send a clear retry message, log the raw input for the coach. **Step 4:** pass.

### Task 20: Pass canonical exercise_ids (not names) to the extraction schema

**Files:** Modify `app/bot.py` (~2431-2436) where the lift catalog is built; align with the extraction prompt/schema in `app/adapters/llm/extractors.py` / `app/domain/checkin/schema.py`; Test: `tests/test_checkin_catalog_ids.py` (create).

The bot passes exercise NAMES, but the prompt/schema require canonical `exercise_id`s → degraded matching.

- [ ] **Step 1: Failing test** — assert the catalog handed to the extractor contains `exercise_id` values present in `get_exercise_db()`, not display names.

- [ ] **Step 2: Expect fail.** **Step 3:** build the catalog from slot `exercise_id`s (map to names only for display). **Step 4:** pass.

### Task 21: Validate LLM output against WorkoutWeek before writing to a live plan

**Files:** Modify `app/api/coach.py` (204-221) and `app/services/llm_service.py` `apply_coach_edits`; Test: `tests/test_coach_edit_validation.py` (create).

Coach-edit writes raw LLM JSON to the active plan with no schema validation → a malformed LLM response corrupts the plan.

- [ ] **Step 1: Failing test** — feed `apply_coach_edits` a deliberately malformed LLM response (mock); assert it raises/returns an error and the original plan is unchanged (not overwritten).

- [ ] **Step 2: Expect fail.** **Step 3:** parse the LLM output and validate it constructs a valid `WorkoutWeek` (Pydantic) before persisting; on failure, keep the existing plan and surface an error to the coach. Apply the same guard in `coach.py`. **Step 4:** pass.

- [ ] **Phase 5 commit:**
```bash
pytest -q && git add -A && git commit -m "fix(bot): preserve telemetry on check-in extraction failure, pass canonical exercise_ids, validate coach-edit LLM output before persisting"
```

---

## Phase 6: Data quality → commit `fix(data): ...`

### Task 22: De-duplicate exercise clones; fix contradictory fatigue_cost

**Files:** Modify `app/exercise_db.py`; Test: `tests/test_exercise_db_integrity.py` (create).

Confirmed clones (different ids, identical/near-identical): two `Single-Leg Leg Extension`, two `Smith Machine Standing Calf Raise`, two `High-to-Low Cable Fly` (fatigue 2 vs 1), two `Low-to-High Cable Fly` (2 vs 1). (`Incline Dumbbell Fly` duplicate was REFUTED by verification — leave it.)

- [ ] **Step 1: Failing test**

```python
# tests/test_exercise_db_integrity.py
import collections
from app.exercise_db import EXPANDED_EXERCISES_DATA as E

def test_no_duplicate_names():
    dups = [n for n, c in collections.Counter(e["name"] for e in E).items() if c > 1]
    assert not dups, f"duplicate exercise names: {dups}"

def test_unique_ids_and_valid_fatigue():
    ids = [e["exercise_id"] for e in E]
    assert len(ids) == len(set(ids))
    for e in E:
        assert 1 <= e["fatigue_cost"] <= 5
```

- [ ] **Step 2: Expect fail** (dups). **Step 3:** remove the duplicate entries (keep one per name; for the contradictory-fatigue pairs keep the more accurate single value). Do not break any test that references a removed `exercise_id` — grep first. **Step 4:** pass.

### Task 23: Junk `egan` diet tag

Merged into Task 6 (chicken_breast tag rewritten to a plain list). If Task 6 was skipped, fix it here: replace `"vegan"[1:]+"egan"[1:][:0]` with the intended plain tags. Verified there is exactly ONE such obfuscation in the codebase.

- [ ] **Phase 6 commit:**
```bash
pytest -q && git add -A && git commit -m "fix(data): de-duplicate exercise clones, correct contradictory fatigue costs"
```

---

## Phase 7: Regression sweep, docs, PR → commit `chore: ...`

### Task 24: Fill the highest-value test gaps (from audit `tests-coverage`)

**Files:** `tests/` — ensure these exist (several created above): generator combo-sweep (Task 14), nutrition medical (Task 7), nutrition halal (Task 6), macros goal (Task 9), full-PDF (Task 17), bot authz (Task 4), JWT token types (Task 2), autoregulator cap (Task 12), coach-edit validation (Task 21). Add any remaining: nutrition_service end-to-end (BMR→TDEE→macros→7-day build→validate) with a non-zero plan assertion.

- [ ] **Step 1:** add `tests/test_nutrition_service_e2e.py` asserting a full balanced plan for a normal profile has 7 days, each day kcal within ±10% of target, no day at 0 kcal. **Step 2-4:** TDD to green.

### Task 25: Update stale docs

**Files:** `CLAUDE.md` (remove the false "Key design constraints / known gaps" claims now verified wrong or fixed); `app/domain/nutrition/food_db.py` docstring (real food count); `CHANGELOG.md` (summary of this hardening pass).

- [ ] **Step 1:** edit CLAUDE.md — drop the `CoachedWorkoutResponse` mismatch claim (route uses `workout=`/model matches — verify), the `slot_type main_lift` claim (re-verify current state), and the `test_api.py client_id=="999"` claim (tests pass). Replace with the now-true behavior. **Step 2:** correct food_db docstring count. **Step 3:** add CHANGELOG entry.

### Task 26: Final verification + PR

- [ ] **Step 1:** `pytest -q` → expect all green (230 + new tests).
- [ ] **Step 2:** run the app smoke per `/run` (generate a plan for 2-3 representative profiles incl. powerlifter 5-day, diabetic balanced, bodyweight-only) and render one PDF end-to-end.
- [ ] **Step 3:** confirm PR base with owner (CLAUDE.md says `master`, but current work sits on unmerged `bot-only-deploy` — ask whether base is `master` or `bot-only-deploy`).
- [ ] **Step 4:** open ONE PR with a summary table of every fix and a link to `AUDIT_REPORT.md`.

---

## Self-Review notes

- **Spec coverage:** Every confirmed-real high/critical finding maps to a task — security (T1-5), nutrition criticals (T6-7), diet model (T8-9), workout engine highs (T10-12) + gaps (T13-14), PDF crashes (T15-17), mobile (T18), bot/LLM (T19-21), data (T22-23), tests (T24), docs (T25). Refuted findings (Incline Dumbbell Fly dup, `create_all` vs alembic, LLM model-id fallback) are intentionally NOT actioned.
- **Owner constraints:** halal-only and single-balanced-diet are realized by deletion (T6, T8), not by building filters.
- **Health-safety constraint:** no task invents unsourced macros; medical tags derive from existing USDA values; new food/exercise content is out of scope per owner ("no extra diet types").
- **Type consistency:** `total_grams` used in both renderer and template after T15; `type:"access"` claim added in T2 and checked in `decode_token`; `require_secure_secret` defined in T1 and called in main/bot.
