# Design: SP-A — Equipment-Aware Plans + Intake Back Button

**Date:** 2026-06-20
**Branch base:** `fix/audit-hardening`
**Status:** Approved design — pending implementation plan

This is the **first** of four sub-projects (SP-A → SP-D) decomposed from a batch of
client-test feedback. The remaining slices are deferred and out of scope here:

- **SP-B** — exercise regression/progression DB + client ability survey (feedback #5, #6)
- **SP-C** — client↔coach Q&A channel (feedback #3)
- **SP-D** — pre-payment pitch / packages (feedback #4)

## Problem (feedback this slice closes)

Two pieces of real client-test feedback:

1. **#1 "Back in the menus."** Intake is strictly forward-only. A client who taps the
   wrong avatar / days / experience / limitation cannot go back and fix it without
   `/start`-ing over. Verified: no core intake state has a Back button
   (`bot.py:5209-5232`); the only Back buttons live in the pre-payment menu, the
   coach-profile picker, and the admin reject flow.

2. **#2 "Limitations in machine."** Three sub-asks:
   - The client should declare **what equipment he actually has** (a checklist), since
     plans must match his gym — "he may have a leg press but not a hack squat."
   - If a **coach adds an exercise needing equipment the client lacks**, the bot must
     **stop the coach, give the reason, and offer alternatives.**
   - Handle the client **who has nothing → bodyweight only.**

   Verified live defect: every client's `available_equipment` is hardcoded to
   `["full_gym"]` (`bot.py:2138` create; `bot.py:2123` default-if-empty on update) and
   is **never collected from the client**. The engine already filters on it
   (`generator.py:154-160`), so a home/garage client silently receives barbell hack
   squats and leg-press work **today**. The coach-edit path (`apply_coach_edits`,
   `llm_service.py:123-136`) validates only JSON + `WorkoutWeek` schema — **no
   equipment check** — and `/override` (`coach_overrides` → `_apply_override`,
   `generator.py:293-304`) substitutes any exercise id with **only a DB-existence
   check**, no equipment guard. The exercise DB has **no bodyweight squat or lunge at
   all**, so a true bodyweight-only client gets a **collapsed, push-only plan**
   (empirically: an `["bodyweight"]` 4-day client's Upper day shrinks 6→3 slots, all
   push, and the generator logs `push/pull imbalance … ratio=inf`).

## Goals

- Collect each client's real equipment at intake (preset + per-item checklist),
  replacing the hardcoded `["full_gym"]`, and let the client **edit it after intake**.
- Add intake **back navigation** so any prior answer can be corrected mid-conversation.
- Add a minimal **bodyweight floor** to the exercise DB so a bodyweight-only client
  gets a complete legs + push day (and full 7/7 coverage if he has a pull-up bar).
- Guard **every** coach exercise-add path against the client's equipment at a single
  pre-dispatch choke point, bouncing violations back with the reason and
  equipment-valid alternatives.
- Never let the engine receive an empty equipment list and produce a zero-exercise plan.

## Non-goals (explicitly deferred)

- **No** regression/progression chains or per-exercise difficulty tiers on exercises
  (SP-B / feedback #5). The bodyweight floor is plain exercise entries only.
- **No** client ability survey (SP-B / #6).
- **No** band / resistance-band equipment token or exercises (SP-B). A no-bar
  bodyweight-only client's pulling gap is surfaced + coach-flagged, not solved here.
- **No** interactive client↔coach thread (SP-C / #3). The coach "alternatives" message
  is a one-shot informational DM, not a negotiation.
- **No** change to `_resolve_split`, the autoregulator, or volume budgeting.

---

## Architecture overview

Six components, all additive. No new DB columns, no migration (`available_equipment`
is a JSON list column on `ClientProfile` since the initial schema,
`alembic/versions/0001_initial_schema.py:29`).

```
intake / profile-edit (bot.py)
  ├─ [C1] equipment survey  → writes ClientProfile.available_equipment (floored, never [])
  ├─ [C2] UPD_EQUIPMENT     → edit equipment after intake (new + existing clients)
  └─ [C3] back navigation   → computed _intake_back(context) + per-state key clearing

generation (generator.py)
  ├─ [C4] bodyweight floor  → 5 new exercises in exercise_db.py
  └─ [C5] pulling-gap guard → intake warn + plan note + coach flag for no-bar BW clients

coach review (bot.py + new validator)
  └─ [C6] validate_equipment(week, available_equipment)
         one validate_then_persist helper on ALL 3 PendingApproval write sites
         + /override set-time check
```

---

## C1 — Equipment survey at intake

New states inserted **after `ASK_DAYS`** (logistics question, like days):
`ASK_EQUIPMENT` (preset menu) and `ASK_EQUIPMENT_CUSTOM` (per-item checklist).

**The 16 real equipment tokens** (counted across `EXPANDED_EXERCISES_DATA`):
`barbell, bench, bodyweight, cable_machine, dip_station, dumbbells, ez_bar,
kettlebell, landmine, leg_curl_machine, leg_extension_machine, leg_press_machine,
pull_up_bar, smith_machine, squat_rack, trap_bar`.

`bodyweight` is always implicit (never shown). The remaining 15 are the checklist
universe. To honor "only the necessary ones," the checklist groups them; the niche
barbell-attachment tokens (`ez_bar`, `trap_bar`, `landmine`) are folded into the
"Commercial gym" preset rather than shown as standalone home checkboxes, but remain
individually selectable under **Custom** so granularity is preserved.

**Presets → tokens:**

| Preset | `available_equipment` |
|---|---|
| 🏢 Commercial gym | `["full_gym"]` (wildcard — matches everything) |
| 🏠 Home gym | opens checklist, **pre-checked** `dumbbells, bench, pull_up_bar` |
| 🧰 Minimal | `["bodyweight", "pull_up_bar"]` |
| 🧍 Bodyweight only | → **explicit pull-up-bar question** (see below) |
| ⚙️ Custom | opens checklist, **empty** (pull-up bar is one of the checkboxes) |

**Explicit pull-up-bar question (bodyweight path).** Because a pull-up bar is the single
highest-leverage item for a bodyweight trainee — it alone flips pattern coverage from
**5/7 to 7/7** by unlocking *all* pulling — picking 🧍 Bodyweight only does **not**
silently mean "no bar." It asks a one-tap follow-up:

> "Do you have a pull-up bar? It unlocks all your back/pull training."  [ ✅ Yes ]  [ ❌ No ]

→ Yes ⇒ `["bodyweight", "pull_up_bar"]` (complete 7/7 program); No ⇒ `["bodyweight"]`
(pushes/legs only + the C5 no-pull warning and coach flag). The pull-up bar is also a
standalone checkbox in the Custom checklist, so any custom build can include it.

**Checklist UX:** reuses the limitations multi-select toggle pattern
(`handle_limitations_toggle` + a Done button, `bot.py:1961-2005`,
`_build_limitations_keyboard`): each token renders `✓ name` when selected,
`callback_data=f"equip_toggle_{token}"`; a `✅ Done` (`equip_confirm`) advances.

**Empty-selection floor (blocking-bug fix):** if the client taps Done with nothing
checked, **do not persist `[]`** (verified: `[]` rejects every exercise → zero-exercise
plan). Floor to `["bodyweight"]` and confirm to the client ("No equipment selected —
we'll build a bodyweight-only plan").

**Persistence:** write `ClientProfile.available_equipment` from the survey, replacing
the hardcoded `["full_gym"]` at `bot.py:2138`. The update branch (`bot.py:2123`) keeps
its default-if-empty but the survey now always supplies a non-empty value.

**Hack-squat note:** the DB has a `leg_press_machine` token but **no `hack_squat`
exercise or token at all**, so "leg press but not hack squat" is automatically honored
(there is no hack-squat to exclude). We do **not** add a `hack_squat` token (no exercise
would use it). The checklist exposes exactly the equipment that maps to real exercises.

## C2 — Edit equipment after intake

`/update_profile`'s field picker (`UPD_PICK` → `UPD_AVATAR/DAYS/EXP/LIM/LIM_OTHER/EMAIL`,
`bot.py:5287-5296`) has **no equipment field** — so without this, a wrong pick is
permanent and the legacy `full_gym` rows can never be corrected.

Add **`UPD_EQUIPMENT`** to the picker, reusing the same preset + checklist handlers as
C1 (one shared implementation). On save, overwrite `available_equipment` (floored, never
`[]`). This is what actually delivers "the client checks/updates what he has."

## C3 — Intake back navigation

Every intake step **after the first** gets an inline `⬅️ Back` button on its prompt.
Free-text steps (`ASK_LIMITATIONS_OTHER`, `ASK_BASE_*`, `ASK_EMAIL`) are
`MessageHandler`-based, so their Back arrives as a `CallbackQuery` — each such state's
handler list gains an explicit `CallbackQueryHandler(handle_intake_back,
pattern="^intake_back$")`. (The `ASK_BASE_*` states already prove a `CallbackQuery`
Skip button co-existing with a `MessageHandler` works, `bot.py:5223-5231`.)

**Computed predecessor (not a static map).** Predecessors are conditional:
`ASK_BASE_SQUAT`'s predecessor is `ASK_LIMITATIONS_OTHER` *iff* "other" was chosen, else
`ASK_LIMITATIONS`; `ASK_EQUIPMENT_CUSTOM`'s predecessor is `ASK_EQUIPMENT`. A flat map
mis-navigates. `_intake_back(context)` derives the previous state from
`context.user_data` (e.g. `_ask_limitations_other` flag, which preset was tapped).

**Forward-replay model (v1).** Back moves to the previous step **only**; the client then
re-taps forward through the (pre-filled) remaining steps. This is the simple, robust v1 —
**not** a state-stack. Two invariants make it correct, and they replace any blanket
"clear the answer" logic (which would wipe the very selections we want to show):

1. **Committed answers are preserved, not cleared.** Re-entering a step re-seeds its
   editable view from the committed value: a multi-select step (`ASK_LIMITATIONS`,
   `ASK_EQUIPMENT_CUSTOM`) re-renders with prior toggles still checked; a single-choice
   step shows its prior pick. The client edits rather than restarts.
2. **Confirm handlers are idempotent on replay.** Each step's confirm handler **always**
   (re)writes its committed answer *and* recomputes any derived routing flag every time it
   runs, so a second pass never leaves stale derived state. Concretely:
   `handle_limitations_confirm` must **always** set `_ask_limitations_other` to True/False
   (not only when True) and clear `limitations_other` when "other" is deselected; the
   equipment confirm must always (re)write `available_equipment` from the current toggles
   (floored, never `[]`); the `ASK_BASE_*` handlers already tolerate replay via the
   existing `is not None` seed guard.

So there is **no** separate per-state clearing table — preservation + idempotent replay is
the model. The one thing the implementer must guarantee is invariant #2 for the two states
with derived/conditional routing (limitations-other and the equipment preset→custom
branch); everything else is naturally overwritten on the forward pass.

## C4 — Bodyweight floor (exercise DB)

Add **5** exercises to `EXPANDED_EXERCISES_DATA` (collision-checked against existing
ids; pike push-up, glute bridge, and pull-up/chin-up already exist and are **not**
re-added). Plain entries — **no** difficulty/regression metadata (that is SP-B).

| `exercise_id` | pattern | primary | fc | equipment | biomech | avatars |
|---|---|---|---|---|---|---|
| `bw_air_squat` | squat | quadriceps | 2 | `[bodyweight]` | lengthened | gen_pop, powerbuilder |
| `bw_reverse_lunge` | lunge | quadriceps | 3 | `[bodyweight]` | mid_range | gen_pop, powerbuilder |
| `bw_single_leg_rdl` | hinge | hamstrings | 2 | `[bodyweight]` | lengthened | gen_pop, powerbuilder |
| `bw_knee_push_up` | horizontal_push | chest | 1 | `[bodyweight]` | lengthened | gen_pop |
| `bw_inverted_row_bar` | horizontal_pull | mid_back | 2 | `[pull_up_bar, bodyweight]` | mid_range | gen_pop, powerbuilder |

Full secondary-muscle lists and sources in the Appendix. `bw_knee_push_up` is the
push-up **regression** so a beginner who cannot do a full push-up still has an on-pattern
movement (achieved via shorter lever, strictly `[bodyweight]` — not an incline, which
would need a surface).

**Fatigue-bound interaction (documented, not a bug).** `fatigue_cost` gates selection
via per-slot `min_fat`/`max_fat` bounds (`main_compound` wants 4-5,
`workout_constants.toml:44`; `generator.py:185-189, 315-316`). Bodyweight exercises are
fc 1-3, so they fill a `main_compound` slot only via the Tier-4 fallback that drops
fatigue bounds (`generator.py:358-359`). This is correct for a bodyweight client (there
is no high-fatigue bodyweight squat) — the spec records it so the implementer does not
"fix" the bound.

## C5 — Pulling-gap constraint (no-bar bodyweight client)

With these additions a bodyweight-only client covers:
- **With a pull-up bar** (`[bodyweight, pull_up_bar]`): **7/7 patterns** — complete.
- **No bar** (`[bodyweight]`): **5/7** — squat/hinge/lunge/push covered, but **zero
  horizontal or vertical pull** (every credible pull needs something to pull against).

A no-bar client's Pull/Upper day would otherwise **collapse** — and Tier-5 substitution
(`generator.py:370-377`) fires only for **injury** bans (`_banned_patterns`), **not**
equipment gaps, so nothing backfills it. This is an explicit constraint, not a "note":

1. **Steer at the survey:** the Minimal preset bundles `pull_up_bar`, and the
   Bodyweight-only preset **explicitly asks** the pull-up-bar question (C1) — so a client
   only lands in the no-pull state by answering "No" to a clear prompt. On "No," show the
   one-line warning: "Bodyweight-only means **no back/pull training** until you get a
   pull-up bar or your coach adds bands."
2. **Flag the coach:** `WorkoutWeek` has **no** `rationale`/`notes` field
   (`models.py:275-277` — only `week_number` + `days`), so the flag is **not** carried
   on the plan object. Instead, when a client's equipment yields no pulling pattern,
   append a prominent line to the **coach plan-approval DM** (the message that carries
   the Approve/Reject keyboard, composed near `_review_keyboard`, `bot.py:4459-4465`):
   `"⚠️ Equipment gap: no pulling movements available — recommend a pull-up bar or band."`
   This needs **no** model change. (Computed once at review time from
   `available_equipment` vs the patterns the generated week actually contains.)
3. Full band support + improvised pulling regressions are **SP-B**.

## C6 — Coach-edit equipment guard (one validator, every write site)

There are **three** ways a coach introduces an exercise; the guard must cover all:

| Path | Today | Fix |
|---|---|---|
| `apply_coach_edits` (free-text reject → LLM) | no equipment check | validate at re-present write |
| `/override` → `coach_overrides` → `_apply_override` (generation time) | DB-existence only | **set-time check** + generation-write validation |
| Add-core (`_core_choices_for_client`, `bot.py:4420-4434`) | already equipment-filtered | **no change** (note it's safe; defensive validation only) |

**New validator** `validate_equipment(week, available_equipment) -> list[Violation]`:
for each slot, resolve `slot.exercise_id` (the stable DB key, `models.py:254`) to its
exercise; flag if any `equipment_required` token is absent and `full_gym` is not present;
an exercise id **not in the DB** is also a violation.

**Convergence: there is NO single existing choke point** — `PendingApproval.workout_json`
is written at **three** independent sites (verified): initial generation
(`run_generation_and_dispatch`, `bot.py:519-523`), the post-LLM-edit reject re-present
(`bot.py:4166`), and post-add-core (`bot.py:4567`). The fix **creates** one: introduce a
single `validate_then_persist_pending(...)` helper that runs `validate_equipment` and only
then writes `workout_json`, and **route all three write sites through it**. This makes the
guard a real single choke point by refactor rather than by assumption.
- Site `:519-523` carries `coach_overrides` violations (overrides are applied during
  generation) → caught here.
- Site `:4166` is the LLM-edit path → the main newly-covered hole.
- Site `:4567` (add-core) is already equipment-safe → validation is defensive only.

On any violation: do **not** persist the plan; DM the coach a one-shot message — the
offending exercise(s), the missing gear, and a short list of **equipment-valid,
same-muscle/pattern alternatives** (via `_filter_exercises`). The coach re-instructs or
picks. (Stays a
single informational DM — not a thread; that is SP-C.)

**`/override` set-time check:** in `handle_override` (`bot.py:5053-5058`), before storing
the override, validate the target exercise's equipment against the client's; reject
immediately with the same reason + alternatives. This gives the coach instant feedback
rather than a deferred bounce.

**Empty-list generation defense:** at generation, treat an empty/None
`available_equipment` as `["full_gym"]` (preserves historical behavior for legacy rows
the survey never touched). The survey itself floors to `["bodyweight"]`, so the engine
never sees `[]` from a surveyed client; this defense only protects pre-existing/corrupt
rows from the zero-exercise bug.

---

## Data model / migrations

None. `available_equipment` already exists (JSON list, `models.py:47`). DB change is new
in-memory exercise entries only. No new `ClientProfile` field (no ability/difficulty
field — that is SP-B).

## Error handling

- Empty equipment selection → floored to `["bodyweight"]` + client confirmation (never `[]`).
- Legacy/empty `available_equipment` at generation → treated as `["full_gym"]`.
- No-pull equipment → the **coach plan-approval DM** carries an `⚠️ Equipment gap` line
  (the bodyweight path asks the pull-up-bar question explicitly first, so a no-pull plan
  only reaches the coach when the client genuinely has no bar).
- Coach guard violation → plan **not** persisted; coach DM'd reason + alternatives.
- Back pressed on first step → no-op (button absent on the first step).
- Back on a free-text step → handled by the explicit `CallbackQueryHandler`, never
  misread as a typed answer.

## Testing (TDD, one cluster per component)

- **C1:** preset→token mapping for all 5 presets; checklist toggle accumulation;
  Done-with-empty floors to `["bodyweight"]` (not `[]`); a new intake persists the
  surveyed value, **not** `["full_gym"]`; the engine produces a non-empty plan for each
  preset.
- **C1 end-to-end (the headline-bug guarantee).** This is the property the whole slice
  exists for. For a **dumbbell-only** client and a **bodyweight + pull-up-bar** client,
  generate a *full* plan and assert **every** slot's `exercise_id` resolves to an exercise
  whose `equipment_required` is satisfied by the client's `available_equipment` — i.e. a
  non-full-gym client never receives a barbell/leg-press exercise. (Exercises C1 + the
  existing `_filter_exercises` together, end-to-end, not the validator in isolation.)
- **C2:** `UPD_EQUIPMENT` round-trips — an existing `full_gym` client edits to a home set
  and the next plan respects it.
- **C3:** from each post-first state, Back re-enters the *correct* computed predecessor
  with prior selections preserved (multi-select toggles still checked); the "other"-branch
  and equipment-preset branch both navigate correctly; **idempotent replay** — going back,
  *deselecting* "other", then forward again leaves `_ask_limitations_other = False` and no
  stale `limitations_other` (the confirm handler always rewrites the flag), and re-running
  the equipment confirm never yields `[]`.
- **C4:** a `["bodyweight"]` client gets a complete squat+hinge+lunge+push day with **no
  collapsed slot**; the 5 new ids exist and validate against the `Exercise` schema.
- **C5:** a `["bodyweight"]` (no-bar) client's plan carries the `[equipment gap]` coach
  flag; a `["bodyweight","pull_up_bar"]` client trains all 7 patterns with **no** flag.
- **C6:** `validate_equipment` flags a slot needing absent equipment and passes a valid
  week; a `coach_overrides` pointing at an unavailable-equipment exercise is caught at
  the generation write (and rejected at `/override` set-time) with alternatives returned;
  an LLM-edited week with a bad-equipment exercise is caught at the reject re-present
  write; Add-core remains valid; an unknown exercise id is flagged.

---

## Appendix A — Bodyweight floor exercise entries (sourced)

Full entries to add to `EXPANDED_EXERCISES_DATA`. Classifications sourced from NSCA
*Essentials of Strength Training and Conditioning* (4th ed.) and the ACE/ACSM exercise
libraries (per-exercise source noted).

```python
{"exercise_id": "bw_air_squat", "name": "Bodyweight Air Squat",
 "movement_pattern": "squat", "primary_muscle": "quadriceps",
 "secondary_muscles": ["glutes", "adductors", "core"], "fatigue_cost": 2,
 "equipment_required": ["bodyweight"], "avatar_tags": ["gen_pop", "powerbuilder"],
 "biomechanical_focus": "lengthened_position"},
# NSCA: multi-joint knee-dominant; primary movers quadriceps/glute max, synergist adductor magnus. ACE Bodyweight Squat.

{"exercise_id": "bw_reverse_lunge", "name": "Bodyweight Reverse Lunge",
 "movement_pattern": "lunge", "primary_muscle": "quadriceps",
 "secondary_muscles": ["glutes", "hamstrings", "adductors", "core"], "fatigue_cost": 3,
 "equipment_required": ["bodyweight"], "avatar_tags": ["gen_pop", "powerbuilder"],
 "biomechanical_focus": "mid_range"},
# NSCA: single-leg multi-joint, quad/glute-max primary. Step-back chosen (floor-only, knee-friendly) over Bulgarian (needs a bench).

{"exercise_id": "bw_single_leg_rdl", "name": "Bodyweight Single-Leg Romanian Deadlift",
 "movement_pattern": "hinge", "primary_muscle": "hamstrings",
 "secondary_muscles": ["glutes", "lower_back", "core"], "fatigue_cost": 2,
 "equipment_required": ["bodyweight"], "avatar_tags": ["gen_pop", "powerbuilder"],
 "biomechanical_focus": "lengthened_position"},
# ACE Single-Leg RDL: hip-hinge, glute-max + hamstrings. Adds a lengthened-position hinge (glute bridge is shortened only).

{"exercise_id": "bw_knee_push_up", "name": "Knee (Modified) Push-Up",
 "movement_pattern": "horizontal_push", "primary_muscle": "chest",
 "secondary_muscles": ["triceps", "front_delts", "core"], "fatigue_cost": 1,
 "equipment_required": ["bodyweight"], "avatar_tags": ["gen_pop"],
 "biomechanical_focus": "lengthened_position"},
# ACSM/ACE: standard push-up regression (shorter lever), pec major primary, triceps/ant-delt synergists. Beginner path into pushing.

{"exercise_id": "bw_inverted_row_bar", "name": "Bar Inverted Row",
 "movement_pattern": "horizontal_pull", "primary_muscle": "mid_back",
 "secondary_muscles": ["lats", "biceps", "rear_delts", "core"], "fatigue_cost": 2,
 "equipment_required": ["pull_up_bar", "bodyweight"], "avatar_tags": ["gen_pop", "powerbuilder"],
 "biomechanical_focus": "mid_range"},
# NSCA: horizontal row, mid-trap/rhomboid + lat primary, biceps synergist. Bar-at-hip-height variant (only needs a bar; the existing
# inverted-row needs a bench). Bar-gated by design — does NOT serve a no-bar client (see C5).
```

## Appendix B — Verified grounding facts (file:line)

All confirmed by a 3-agent read of current code (corrections folded into the design above):

- Equipment filter: `generator.py:154-160` (subset test; `full_gym` wildcard).
- Hardcoded equipment: `bot.py:2138` (create, literal `["full_gym"]`), `bot.py:2123`
  (update, default-if-empty). Never collected from the client.
- Limitations toggle pattern (reuse target): `bot.py:1961-2005`,
  `_build_limitations_keyboard:1914-1928`.
- Add-core already equipment-safe: `_core_choices_for_client`, `bot.py:4420-4434`.
- Coach-edit no equipment check: `llm_service.py:123-136` (JSON + `WorkoutWeek` only).
- `/override` no equipment check: `_apply_override`, `generator.py:293-304` (DB-existence only).
- Slot identifies its exercise by `exercise_id` (+ `exercise_name`): `models.py:254-255`,
  built in `_construct_slot`, `generator.py:416-419`.
- `available_equipment` predates migration 0020: `0001_initial_schema.py:29`. No new migration.
- Tier-5 substitution is injury-only: `generator.py:370-377` keyed on `_banned_patterns`.
- `fatigue_cost` gates selection via slot `min_fat`/`max_fat`: `workout_constants.toml:44`,
  `generator.py:185-189, 315-316, 358-359`.
- No ability/difficulty field on `ClientProfile` (SP-B will add): `models.py:36-76`.
