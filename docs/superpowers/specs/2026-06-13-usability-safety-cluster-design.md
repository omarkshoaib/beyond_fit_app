# Design: Usability + Safety Cluster

**Date:** 2026-06-13
**Branch base:** `fix/audit-hardening`
**Status:** Approved design — pending implementation plan

## Problem

A scientific + production review of the deterministic coaching engine surfaced four
verified defects that make the generated plans either unsafe, inaccurate, or
unusable for a real paying client:

1. **Declared injuries are ignored (safety).** The bot collects `knee_pain` and
   `shoulder_impingement` (`bot.py:1898-1905`) but `_filter_exercises`
   (`generator.py:160-165`) only gates `lower_back_pain`. A client who declares a
   knee injury still receives squats. `SUBSTITUTION_MAP` (`constants.py:67-80`)
   exists to fix exactly this — and is **dead code, zero call sites**.
2. **Meal plans are monotonous (usability).** `_pick` returns `candidates[:n]` in
   DB order every day (`meal_builder.py:362`); the only variation is a >5×/week
   exclusion. All seven days pick the same foods (chicken + white rice + broccoli +
   olive oil), then a forced swap.
3. **Week-1 plans ship with no loads (usability).** `target_weight` is set only
   when prior-week telemetry exists (`generator.py:390-403`). The first plan gives
   sets/reps/RPE but no kg, so a client has no idea what to lift.
4. **The day-macro validator never runs (accuracy).** `validate_day` is imported
   into `nutrition_service` (`nutrition_service.py:21`) but has **zero call sites**.
   The only check is a whole-week near-zero-kcal guard (`nutrition_service.py:183-188`);
   per-day ±5% kcal / protein-floor / fiber tolerances are computed-but-unenforced.

## Goals

- Wire declared limitations into exercise selection via `SUBSTITUTION_MAP`, keeping
  each training day's intent (a knee-pain Leg day still trains legs).
- Produce a varied 7-day meal plan from the existing food pool, deterministically.
- Seed week-1 working loads from client-supplied baseline lifts (squat / bench /
  deadlift) using conservative, sourced strength science.
- Gate each generated nutrition day against `validate_day` and surface drift to the
  human coach at review.

## Non-goals

- No change to the macro math (protein/fat/fiber/water targets are textbook and
  stay as-is).
- No per-muscle landmark-driven volume budgeting, `bio_focus` lever, per-slot RPE,
  or TDEE bias-down decision — those are separate refinement slices.
- No new regional food catalog (separate slice).
- No removal of the legacy FastAPI / web profile fields.

## Determinism contract (unchanged)

Every component below is fully deterministic. No randomness, no LLM in the
selection or load path. The LLM continues to only format plans into readable text.
Same inputs → same plan, every run.

---

## Component 1 — Injury-aware exercise selection (A.1)

**Files:** `app/generator.py`, `app/domain/workout/constants.py`

### Verified facts
- `SUBSTITUTION_MAP` covers `lower_back_pain`, `knee_pain`, `shoulder_impingement`.
- **`broken_substitutions: []`** — every alternative pattern resolves to a
  non-empty pool for gen_pop / powerbuilder (powerlifter borrows the powerbuilder
  accessory pool): `lower_back_pain` hinge→horizontal_pull (14 exercises),
  squat→[lunge 13, horizontal_push 18]; `shoulder_impingement`
  vertical_push→horizontal_push (18), horizontal_pull→vertical_pull (13);
  `knee_pain` squat→horizontal_pull (14), lunge→hinge (16). All substitutions are
  viable — no slot will be emptied.
- `wrist_pain` and `hip_flexor_tightness` are collected by the bot but have **no**
  `SUBSTITUTION_MAP` entry and no clean pattern swap.

### Design
1. New helper `_banned_patterns(client) -> set[str]`: for each limitation in
   `client.limitations`, read `SUBSTITUTION_MAP[limitation]` and collect its keys
   (the unsafe `movement_pattern`s). Returns the union.
2. New helper `_substitute_pattern(limitations, pattern) -> list[str]`: returns the
   ordered alternative patterns for the first limitation that bans `pattern`
   (`SUBSTITUTION_MAP[limitation][pattern]`), else `[pattern]` unchanged.
3. `_select_for_slot`: before the 4-tier search, if `spec["pattern"]` is in the
   client's banned set, replace it with the substitute pattern list and attempt
   selection against each alternative in order (first hit wins) — so the day keeps
   its training intent instead of falling to an empty slot.
4. `_filter_exercises`: generalize the current `lower_back_pain`-only block to
   exclude any exercise whose `movement_pattern` ∈ banned set. Preserve the
   existing extra `lower_back_pain` rule that also strips exercises carrying
   `lower_back` as a secondary muscle (a stricter, movement-agnostic guard).
5. `wrist_pain` / `hip_flexor_tightness`: no exclusion (we do not fake safety).
   Attach a coaching-cue caveat string to affected slots — e.g. pressing/pulling
   slots for `wrist_pain`, hinge/lunge slots for `hip_flexor_tightness` — so the
   coach and client are warned. Implemented as an appended `coaching_cues` entry,
   not a filter.

### Edge cases
- A limitation banning a slot's pattern whose substitute also can't be filled
  (should not happen given `broken_substitutions: []`, but defensively): fall
  through the existing tiers, then leave the slot unfilled rather than crash.
- Multiple limitations banning the same pattern: union of banned patterns; the
  first matching substitution list is used (deterministic by limitation order).
- `safety_override_note` (physician clearance) already skips the hard-refuse gate;
  it does **not** skip injury substitution (substitution is conservative, not a
  hard refuse) — confirm this is the intended behavior in the plan.

### Tests
- Client with `knee_pain` → zero `squat`/`lunge`-pattern exercises in the week;
  Leg-day main compound is a hinge/horizontal-pull pattern; day still has its full
  slot count.
- Client with `shoulder_impingement` → no `vertical_push` (overhead) exercises.
- Client with `lower_back_pain` → no hinge and no `lower_back`-secondary exercises
  (regression guard for existing behavior).
- Client with `wrist_pain` → exercises unchanged, caveat cue present on pressing
  slots.
- Multi-limitation client → all bans honored, no slot crash.

---

## Component 2 — Meal rotation (A.3)

**Files:** `app/domain/nutrition/meal_builder.py`, `app/services/nutrition_service.py`

### Verified facts
- `build_day_plan` signature at `meal_builder.py:319-328` has no `day_index`.
- `_pick` at `meal_builder.py:359-362`; the line to change is `362: return candidates[:n]`.
- The 7-day loop at `nutrition_service.py:101` is `for _ in range(7):` — no index
  threaded in. Per-slug bookkeeping at 112-114, append at 115.

### Design
1. Add `day_index: int = 0` parameter to `build_day_plan`.
2. In `_pick`, replace `candidates[:n]` with a rotated modular selection:
   ```
   if not candidates:
       return []
   offset = (day_index + _CATEGORY_OFFSET[cat]) % len(candidates)
   rotated = candidates[offset:] + candidates[:offset]
   return rotated[:n]
   ```
   where `_CATEGORY_OFFSET` is a fixed small per-category constant (e.g.
   `{"protein": 0, "grain": 1, "veg": 2, "fat": 3, "fruit": 4}`) so different
   categories don't all rotate in lockstep.
3. Keep the existing `>5×/week` exclusion (`meal_builder.py:341-344`) — it now acts
   as a hard cap on top of rotation. Rotation spreads variety; the cap prevents any
   single food dominating.
4. Add a "not identical to yesterday" tiebreak: pass the previous day's chosen
   slugs per category (threaded from the caller) and, if the rotated top pick
   equals yesterday's, advance the offset by one. Optional refinement — include
   only if it doesn't complicate the deterministic contract; the rotation alone
   already breaks the all-same-week behavior.
5. `nutrition_service.py:101`: change `for _ in range(7):` → `for day_index in
   range(7):` and pass `day_index=day_index` into `build_day_plan`.

### Edge cases
- Pool smaller than the rotation span (e.g. only 2 proteins pass filters):
  modular rotation still cycles; the >5×/week cap may force reuse — acceptable, log
  if a category has <2 eligible foods.
- A category with zero eligible foods for a slot: existing sparse-selection
  fallback (`meal_builder.py:371-376`) still applies.

### Tests
- 7-day plan uses ≥3 distinct proteins and ≥2 distinct grains across the week
  (given a normal pool).
- No food appears on >5 of 7 days (regression guard for the cap).
- Day N and Day N+1 differ in at least one category's primary pick.
- Determinism: two runs with identical inputs produce byte-identical plans.

---

## Component 3 — Week-1 load seeding from baseline e1RM (A.4)

**Files:** `app/models.py`, `app/bot.py`, `app/generator.py`,
new `app/domain/workout/loadseed.py`, new `tests/test_loadseed.py`

### Decision
Client supplies **squat, bench, deadlift** baseline sets only (no row, no
bodyweight on the workout profile). Non-tested compounds derive by ratio from the
nearest baseline; un-derivable lifts fall back to a guidance string.

### Strength-science reference (verified, sourced — see Appendix A)
- **1RM formula: Brzycki** `1RM = w × 36 / (37 − r)`, inputs clamped to `r ≤ 10`
  (reject/clamp higher-rep inputs; Brzycki is conservative and never seeds heavier
  than Epley across 1–10 reps).
- **Working load:** `working_kg = e1RM × pct(reps, rpe)` from the Tuchscherer
  RIR-based %1RM table (Appendix A §2). `reps` = lower bound of the slot's rep
  range; `rpe` = the week's target RPE. Round **down** to the nearest 2.5 kg
  (err light).
- **Full pattern → e1RM map** (`pattern_e1rm`). This single map serves both main
  AND secondary compounds, so a Push day's seeded bench (main) and OHP (secondary)
  are consistent rather than one numeric and one blank:

  | movement_pattern  | derivation              | source            |
  |-------------------|-------------------------|-------------------|
  | `squat`           | `squat_e1RM`            | tested baseline   |
  | `hinge`           | `deadlift_e1RM`         | tested baseline   |
  | `horizontal_push` | `bench_e1RM`            | tested baseline   |
  | `horizontal_pull` | `0.70 × bench_e1RM`     | row ratio (A.3)   |
  | `vertical_push`   | `0.60 × bench_e1RM`     | OHP ratio (A.3)   |
  | `vertical_pull`   | **None → guidance**     | pull-up needs BW  |
  | `lunge`           | **None → guidance**     | no clean ratio    |
  | `isolation`       | **None → guidance**     | never seeded      |

  `vertical_pull` (pull-up) is bodyweight-loaded and we don't collect bodyweight on
  the workout profile, so it emits the guidance string, not a number. `lunge` has
  no defensible single ratio, so it is guidance too. Isolations are always
  guidance ("pick a load you can complete the reps at the target RPE").
- Each derivation requires its baseline to be present; if the client skipped that
  baseline lift, the pattern yields None → guidance string. So a client who entered
  only squat gets seeded squat-pattern loads and guidance everywhere else.

### Schema
Add three nullable floats to `ClientProfile` (`models.py`, additive — existing
SQLite/Postgres rows unaffected, no migration tooling required by SQLModel for
nullable adds, but document the column add):
```
squat_e1rm: Optional[float] = None
bench_e1rm: Optional[float] = None
deadlift_e1rm: Optional[float] = None
```

### Intake flow (`app/bot.py`)
- States are `ASK_AVATAR, ASK_DAYS, ASK_EXPERIENCE, ASK_LIMITATIONS, ASK_EMAIL =
  range(5)` at `bot.py:157`. Add three new states (extend the range or add string
  constants — values must stay distinct within the one ConversationHandler):
  `ASK_BASE_SQUAT, ASK_BASE_BENCH, ASK_BASE_DEADLIFT`.
- Redirect **all three** limitations exit points that currently `return ASK_EMAIL`
  to the first baseline state: `handle_limitations_confirm` (`bot.py:1981`),
  `handle_limitations_other` (`bot.py:1988`), and legacy `handle_limitations`
  (`bot.py:1996`).
- Each baseline handler: prompt `"Best recent SQUAT set? e.g. 100x5 — or tap Skip"`,
  parse `weight x reps` (accept `x`/`*`/`X`, whitespace tolerant), reject reps >10
  or unparseable with a re-ask, compute Brzycki e1RM, stash into
  `context.user_data['squat_e1rm']` etc. A **Skip** inline button stores `None`.
  The last (`ASK_BASE_DEADLIFT`) returns `ASK_EMAIL`.
- `handle_email` persists in **two** branches — update (`bot.py:2024-2034`,
  commit 2035) and create (`bot.py:2042-2053`, commit 2055). Add the three e1rm
  fields to **both**, read via `context.user_data.get(...)`.

### Generator (`app/generator.py`)
- In `_construct_slot`, after the existing prior-week auto-regulation block: if
  `slot.target_weight is None` (no telemetry — i.e. week 1 or an unlogged
  exercise) and the client has a usable baseline for this slot's pattern, call
  `loadseed.seed_working_load(client, exercise.movement_pattern, reps, rpe)` and
  assign the result. The prior-week path keeps precedence — seeding only fills the
  gap it leaves.
- Deload scaling (`generator.py:459-460`) applies on top of a seeded weight exactly
  as it does today for an autoregulated weight — no change needed.

### `app/domain/workout/loadseed.py` (new, pure functions)
- `brzycki_e1rm(weight_kg, reps) -> float` (clamps `reps` to 1..10).
- `RPE_PCT: dict[tuple[int,int], float]` — the Tuchscherer grid (Appendix A §2),
  with a lookup that clamps reps to 1..10 and RPE to 6..10.
- `pattern_e1rm(client, pattern) -> Optional[float]` — applies the
  pattern→baseline map and ratio derivations; returns None when un-seedable.
- `seed_working_load(client, pattern, reps_str, rpe) -> Optional[float]` —
  composes the above, rounds **down** to 2.5 kg, returns None for guidance-string
  cases.

### Edge cases
- Client skips all three baselines → behaves exactly as today (no seeded loads,
  guidance downstream). No regression.
- Reps input >10 → clamp to 10 for the formula (with a note) or re-ask; pick one in
  the plan (recommend re-ask for honest data).
- Seed lands heavy → autoregulator pulls it down 4%/RPE point, ±10%/week clamp
  (Appendix A §4); conservative rounding makes light the default failure mode.

### Tests (`tests/test_loadseed.py` + generator tests)
- Brzycki: `brzycki_e1rm(100,1)==100.0`; `brzycki_e1rm(100,5)==112.5`;
  reps>10 clamped.
- `RPE_PCT` grid spot-checks against Appendix A (e.g. 5 reps @ RPE 8 = 81.1%).
- `seed_working_load` for squat/bench/deadlift patterns returns a numeric, 2.5-kg
  rounded, never-above-e1RM load; `vertical_pull` returns None.
- Generator week-1 with baselines: tested-pattern main compounds have numeric
  `target_weight`; skipped baselines → None.
- Generator week-2 with prior telemetry: auto-regulation still takes precedence
  (seed does not override a logged progression).

---

## Component 4 — Nutrition day validation gate (A.2)

**Files:** `app/services/nutrition_service.py`

### Verified facts
- `validate_day` (`meal_builder.py:255`) is imported (`nutrition_service.py:21`)
  but never called.
- It requires a `weight_kg` argument (0.8 g/kg fat floor) — available as
  `profile.weight_kg` in `generate()`.
- The only existing check is the whole-week degenerate guard
  (`nutrition_service.py:183-188`).

### Design
- Inside the 7-day loop, immediately after `build_day_plan` returns (after
  `nutrition_service.py:111`), call `validate_day(day, target_kcal,
  macros["protein_g"], macros["fat_g"], macros["fiber_g"], profile.weight_kg,
  strict=True)`.
- If it returns failures, retry the check with `strict=False` (±8% kcal fallback,
  matching the builder's documented tolerance).
- Residual failures are **non-blocking** (consistent with the HITL model — a coach
  approves before dispatch): collect them into a `validation_warnings` list keyed
  by day, and append a concise summary to the plan `rationale` so the coach sees
  drift at review (e.g. `"Day 3: protein 142g below -5% of 160g"`).
- The existing whole-week degenerate guard (`183-188`) stays as the hard stop.

### Why non-blocking
`build_day_plan` is deterministic; re-running it yields the same day, so a hard
"regenerate on failure" would loop or fail the whole plan. Surfacing drift to the
human coach is the correct gate for a HITL system and matches the existing
approve-before-dispatch flow.

### Tests
- A day forced off-target (mocked builder) produces a `validation_warnings` entry
  and a rationale line; the plan still persists.
- A clean plan produces no warnings and an unchanged rationale shape.
- Regression: the degenerate-plan guard still raises on a near-zero-kcal week.

---

## Testing strategy

- **Unit:** `loadseed.py` math (Brzycki, RPE table, ratios), `_banned_patterns` /
  `_substitute_pattern`, `_pick` rotation, `validate_day` gating.
- **Integration:** full `WorkoutGenerator.generate()` for each limitation and for
  week-1 seeding; full `NutritionService.generate()` for variety + validation.
- **Regression:** existing 288-test suite must stay green; explicitly re-assert the
  prior `lower_back_pain` behavior and the auto-regulation precedence.
- **Determinism:** every new path asserted to produce identical output across two
  runs.

## Risks

- **Intake friction (A.4):** three new questions lengthen onboarding. Mitigated by
  per-lift Skip and graceful fallback to today's behavior.
- **Schema add (A.4):** three nullable columns on `ClientProfile`. Additive and
  null-safe, but the live Postgres table needs the columns added on deploy
  (document an `ALTER TABLE ... ADD COLUMN ... NULL` or rely on SQLModel
  create-all for fresh DBs; the prod DB is non-fresh, so an explicit ALTER is
  required — call this out in the plan).
- **Substitution correctness (A.1):** verified `broken_substitutions: []`, but the
  plan should add the regression tests above before relying on it in production.

## Out of scope (tracked for later slices)

- Per-muscle landmark-driven volume budgets (B.5).
- TDEE bias-down vs calibration decision (B.6).
- Per-slot-type RPE (B.7) and `bio_focus` lengthened-position lever (B.8).
- Regional halal food catalog (C).
- Surfacing volume/push-pull warnings to the coach UI (C).

---

## Appendix A — Load-Seeding Reference (verified, sourced)

> Governing mandate: **err light.** A first working weight that comes out light is
> corrected by the autoregulator within one week; one that comes out heavy risks a
> failed first session and a two-week walk-down. Every formula choice, ratio, and
> rounding direction is biased conservative.

### A.1 1RM formula — Brzycki (chosen over Epley)
```
Brzycki: 1RM = w × 36 / (37 − r)      # use this; inputs clamped to r ≤ 10
Epley:   1RM = w × (1 + r/30)         # reference only
```
At `r=1` Brzycki returns exactly `w`; Epley inflates by 3.33%. Across 1–9 reps
Brzycki is the lower (conservative) estimate; they tie at `r=10`. Above ~10–12
reps both are unreliable. Sources: Wikipedia (One-repetition maximum); Arvo
(Epley & Brzycki explained); OpenSIUC validation study.

### A.2 Reps × RPE → %1RM (Tuchscherer / RTS, RIR-based)
RIR: RPE10=0 RIR, 9=1, 8=2, 7=3, 6=4. Each cell = %1RM.
```
reps |  RPE 6 |  RPE 7 |  RPE 8 |  RPE 9 | RPE 10
-----+--------+--------+--------+--------+--------
  1  |  86.3  |  89.2  |  92.2  |  95.5  | 100.0
  2  |  83.7  |  86.3  |  89.2  |  92.2  |  95.5
  3  |  81.1  |  83.7  |  86.3  |  89.2  |  92.2
  4  |  78.6  |  81.1  |  83.7  |  86.3  |  89.2
  5  |  76.2  |  78.6  |  81.1  |  83.7  |  86.3
  6  |  73.9  |  76.2  |  78.6  |  81.1  |  83.7
  7  |  71.7  |  73.9  |  76.2  |  78.6  |  81.1
  8  |  69.6  |  71.7  |  73.9  |  76.2  |  78.6
  9  |  67.6  |  69.6  |  71.7  |  73.9  |  76.2
 10  |  65.6  |  67.6  |  69.6  |  71.7  |  73.9
```
(11–12 rep rows omitted — they extrapolate past the validated range; seed from
≤10-rep inputs.) Internal consistency verified against the RIR rule
`(r reps @ RPE n) == (r + (10−n) reps @ RPE 10)`. Sources: Fitness Volt; Ripped
Body (Helms); CalculateRPE — all transcribing the Tuchscherer grid.

### A.3 Derived-lift ratios (1RM : 1RM — do NOT pre-discount; the RPE table does the working-load conversion)
```
Overhead press   ~0.60 × bench
Barbell row      ~0.70 × bench     (chest-supported reference; err-light floor)
Incline bench    ~0.75 × bench
Front squat      ~0.80 × squat
RDL              ~0.65 × deadlift  (1RM:1RM — NOT the ~0.50 working-load figure)
Pull-up (added)  = 0.90 × bench − bodyweight   (needs bodyweight; not seeded here)
```
Of these, only **barbell row (0.70 × bench)** is needed for a seeded main compound
(`horizontal_pull` in Pull day). `vertical_pull` (pull-up) is left to guidance
because bodyweight is not on the workout profile. Source: Christian Thibaudeau,
"Know Your Ratios" (OHP 60%, incline 80%, front squat 85%, chest-supported row 70%,
chin-up 90% BW-included); cross-checked against ExRx strength standards. Ranges
narrowed to the lighter end.

### A.4 Why err light — autoregulator correction (verified in code)
`AutoRegulator.calculate_next_load()` (`generator.py:34-48`) applies a 4%-per-RPE-point
error correction and clamps weekly change to ±10%
(`max(last_weight*0.90, min(last_weight*1.10, next_target))`). A seed error ≤10% is
fully corrected in one week; a larger over-seed costs a bad session and takes two
weeks to walk down. Under-seeding self-corrects upward with zero risk — hence the
conservative defaults throughout.
