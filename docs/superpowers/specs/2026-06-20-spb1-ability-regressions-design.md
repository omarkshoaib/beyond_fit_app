# Design: SP-B1 — Ability-Appropriate Exercise Selection (regressions + ability survey)

**Date:** 2026-06-20
**Branch base:** `fix/audit-hardening`
**Status:** Approved design — pending implementation plan

Second of four sub-projects (SP-A shipped). **SP-B is split:** this is **B1** (give the client
the difficulty-appropriate variant from week 1). **B2** (auto-advance the variant over time
from check-in competence) is deferred. SP-C (client↔coach Q&A) and SP-D (pitch) are later.

## Problem (feedback this slice closes)

1. **#5 — exercise regressions from a trusted source.** A beginner told to do pull-ups
   can't do them. Today there is **no difficulty data** on exercises (`Exercise` has
   `exercise_id, name, movement_pattern, primary_muscle, secondary_muscles, fatigue_cost,
   equipment_required, avatar_tags, biomechanical_focus` — `models.py:10-19`; verified zero
   `difficulty`/`tier`/`regression` keys). `experience_level` affects **only volume**
   (`_budget_volume`, `generator.py:107-125,557`), never selection — so a beginner draws
   from the *same* pool as an advanced lifter. The main barbell lifts must be represented
   too (not only bodyweight moves).
2. **#6 — survey the client's ability so the plan is custom.** There is no exercise-ability
   field on `ClientProfile`. Selection can't know which variant the client can perform.

## Goals

- Add a **`difficulty_tier` (1–5)** to **every** exercise (skill+strength demand, *not*
  fatigue) and **6 explicit difficulty ladders** (ordered anchor variants per movement
  family, bodyweight → barbell → advanced), sourced from recognized references.
- Add a **per-family ability** field to `ClientProfile`, set by a **6-question intake
  survey** (or defaulted from `experience_level` when skipped).
- Make selection **ability-appropriate**: anchor compound slots pick the client's ladder
  rung; nothing ever exceeds the client's ability; a day is never emptied.

## Non-goals (deferred)

- **B2:** auto-advancing a client's rung over time (persisting `actual_reps` competence +
  an advancement rule). B1 sets ability **once** at intake and never updates it from check-in.
- No change to volume budgeting, the load autoregulator's math, RPE periodization, or the
  SP-A equipment/back-nav surfaces (beyond composing with them).

---

## Architecture overview

```
exercise_db.py
  ├─ [C1] difficulty_tier (1-5) on ALL 179 exercises   (sourced, rubric Appx C)
  ├─ [C2] LADDERS: 6 ordered anchor ladders            (Appx A)
  └─ [C6] +1 vertical-push bodyweight regression rung

models.py / alembic 0021
  └─ [C3] ClientProfile.exercise_ability (JSON per-family 1-5)

bot.py (intake)
  └─ [C4] ASK_ABILITY survey (6 families) — manual wiring into the SP-A back-nav

generator.py (selection)
  └─ [C5] anchor slots = ladder pick (ability governs); non-anchor = gate; ceiling never dropped

bot.py (check-in)
  └─ [C7] bodyweight-main guard: collect reps+RPE not weight; autoregulator skips
```

**`difficulty_tier` vs `fatigue_cost`** are independent axes. `fatigue_cost` = metabolic
cost (drives slot fatigue budget); `difficulty_tier` = skill/strength demand. A barbell
deadlift is fatigue 5 but difficulty 4 (a proficient full-ROM pull is the *standard*
barbell hinge); a Nordic curl is fatigue 3 but difficulty 5. **`fatigue_cost` must NOT be
used to derive `difficulty_tier`.**

---

## C1 — `difficulty_tier` on **all 179** exercises

Add `difficulty_tier: int` to the `Exercise` model and to every dict in
`EXPANDED_EXERCISES_DATA`. **All 179** get a tier (not just the 33 ladder rungs — see the
critical reason in C5: an untiered exercise can't be gated, so a beginner could still
receive a heavy untiered compound like `bb_front_squat`).

Tier definitions (the **rubric** — Appendix C):
- **1** regression: supported/lever-shortened, minimal strength/skill (knee push-up,
  machine-assisted pull-up, glute bridge, box/incline variants).
- **2** basic bodyweight/machine: untrained-accessible (air squat, bar inverted row, leg
  press, seated machine press, goblet squat). **Default for all isolation.**
- **3** standard free-weight: DB/cable + competent bodyweight (DB bench, DB row, push-up,
  RDL, DB shoulder press, walking lunge).
- **4** barbell main / full bodyweight: proficiency required (barbell back squat, bench,
  conventional deadlift, OHP, barbell row, strict pull-up).
- **5** advanced/loaded-skill: high strength or skill ceiling (weighted pull-up/dip, pistol,
  Nordic curl, deficit deadlift, low-bar competition squat, deficit push-up).

**Deterministic rules for the non-ladder exercises:**
- **Isolation** (74, `movement_pattern == "isolation"`): flat **tier 2**, with an upward
  override table (only *up*-rating is safety-relevant): `bw_nordic_curl→5`, `bw_sissy_squat→4`,
  `bw_l_sit→4`, `bw_toes_to_bar→3`. (Isolation `fatigue_cost` is nearly flat — 28×1/45×2/1×3
  — so it gives no usable difficulty spread; flat-2 + overrides is the rule.)
- **Lunge** (14, non-anchor): treated as non-ladder, flat **tier 2**, with `bulgarian /
  cossack / single-leg / lateral` variants → **tier 3**.
- **Non-ladder compounds** (~58: `leg_press_standard`, `smith_hack_squat`, `bb_front_squat`,
  `bb_pause_back_squat`, hip thrusts, other rows/presses): tiered per the rubric (machine/
  guided → 2–3; barbell heavy/competition → 4–5). Assigned + reviewed in the sourcing task,
  cross-checked against the ladder anchors.

The full 179-exercise tier assignment is produced by a **sourcing+review task** (first task
of the plan), the way SP-A's bodyweight floor was sourced — every tier cited to the rubric.

## C2 — The 6 difficulty ladders

A module-level `LADDERS: dict[str, list[str]]` (family → ordered `exercise_id` list,
ascending `difficulty_tier`). Families: `squat, hinge, horizontal_push, vertical_push,
horizontal_pull, vertical_pull`. **Rungs are keyed by their `difficulty_tier`** (not list
index) so "highest rung ≤ ability" is length-agnostic. Full sourced ladders in **Appendix
A**; e.g.:

- `vertical_pull`: `machine_assisted_pull_up`(1) → `cable_wide_grip_lat_pulldown`(2) →
  `cable_neutral_grip_lat_pulldown`(3) → `bw_pull_up_pronated`(4) → `bw_weighted_pull_up`(5).
  *A beginner (ability 1–2) gets the assisted pull-up / pulldown, not a strict pull-up — the
  headline feedback case.*
- `horizontal_push`: `bw_knee_push_up`(1) → `machine_chest_press`(2) → `bw_push_up`(3)/
  `db_flat_bench_press`(3) → `bb_bench_press`(4) → `bw_weighted_dip`(5).

**Cross-family calibration (must be stated in the spec, not assumed):** tiers are **ordinal
within a family** (rung order), **not cardinal across families** (a tier-3 push-up is easier
than a tier-3 smith squat). The **only cross-family invariant is `tier 4 = the family's
barbell main lift`** (squat→back squat, hinge→deadlift, h-push→bench, v-push→OHP,
h-pull→barbell row). `vertical_pull` has **no barbell main** (none is biomechanically real —
the barbell back lift is the row, in `horizontal_pull`); its tier-4 is the **strict
pull-up**. So #5's "main barbell lifts represented" is satisfied **collectively across the 6
families**, not within each — this is intentional and documented.

## C3 — `exercise_ability` on `ClientProfile`

New JSON column (mirrors the existing `features`/`coach_overrides` JSON columns):
```python
exercise_ability: Optional[Dict] = Field(default=None, sa_column=Column(JSON))
# e.g. {"squat": 3, "hinge": 2, "horizontal_push": 2, "vertical_push": 2,
#       "horizontal_pull": 1, "vertical_pull": 1}
```
**Alembic migration 0021** (`revision="0021"`, `down_revision="0020"`), one nullable JSON
column. **No backfill is relied upon for correctness:** existing rows stay NULL; the
selection layer **coerces a missing/None family value to the experience-default** before any
comparison (so a NULL row never throws and behaves as its `experience_level`). Needs the
manual `docker compose run --rm bot alembic upgrade head` on deploy (like 0020).

**Ability scales:**
- **Per-family** ability (1–5) drives anchor-slot ladder picks.
- A **global scalar** (experience-derived: beginner→2, intermediate→3, advanced→4) gates
  **non-anchor** slots (isolation, lunge). Reserve tier-5 for B2 progression / coach
  override / an explicit per-family survey top level — **except** a powerlifter avatar's
  competition main lift is **exempt** from the ceiling (an advanced powerlifter gets their
  low-bar squat / competition bench even though those are tier 5).

## C4 — Ability survey at intake (6 families)

A new `ASK_ABILITY` step **after `ASK_EXPERIENCE`, before `ASK_LIMITATIONS`**. Six quick
questions (one per family), each phrased in terms of that family's **main lift** (not only
bodyweight), 3 levels → ability:
- "New / can't do it yet" → **2** (regression rungs)
- "I can do the standard version" → **3**
- "I'm strong — I do the barbell/loaded version" → **4**

(Tier-5 is not reachable from the survey by design — conservative; B2 / coach / powerlifter
exemption supply it.) **Skippable** — a "Skip, use my experience level" button defaults all
six families from `experience_level`. Reuses the SP-A button/keyboard pattern.

**Manual back-nav wiring (the SP-A back-nav is per-state, NOT automatic — verified):**
1. register `ASK_ABILITY` in `_intake_states` with its own `handle_intake_back` +
   `handle_ability` handler;
2. in `_intake_predecessor` add `ASK_ABILITY → ASK_EXPERIENCE` **and** change
   `ASK_LIMITATIONS`'s predecessor to `ASK_ABILITY`;
3. add an `ASK_ABILITY` render branch in `_render_intake_step`;
4. reroute `handle_experience` to return `ASK_ABILITY` (it currently returns
   `ASK_LIMITATIONS`).
Persist `exercise_ability` in `handle_email` (both create + update branches), like SP-A's
`available_equipment`.

## C5 — Ability-appropriate selection (the heart; 3 critical fixes)

Revised `_select_for_slot` flow:

1. **Injury first.** If the slot's `pattern` is injury-banned (`_banned_patterns`),
   substitute to a safe pattern (`_substitute_patterns`) **before** anything below. The
   ladder/gate then operate on the (possibly substituted) pattern.
2. **Anchor slot → LADDER PICK (ability governs; fatigue band does NOT gate here).** If the
   effective pattern has a ladder: pick the **highest rung with `difficulty_tier ≤
   ability[family]` that is equipment-valid**; tie-break within a tier by **ladder index**
   (lowest index = canonical), and among equipment-valid options at that tier prefer the
   valid one. **Floor:** if no rung ≤ ability is equipment-valid, take the **lowest
   equipment-valid rung** — **never** go above ability and **never** fall through to an
   untiered heavier compound. This is what fixes **CRITICAL #1** (the `main_compound` slots
   hard-code `min_fat=4,max_fat=5`, which is *mutually exclusive* with `tier ≤ 2` for a
   beginner — so the fatigue band must **not** gate an anchor slot; the ladder pick replaces
   it). Respects `used_ids` + rotation.
3. **Non-anchor slot → existing tiered fallback + difficulty ceiling.** For isolation/lunge
   slots (no ladder), run the existing Tier 1–4 fallback but thread `max_difficulty =
   global_scalar` into **every** `_filter_exercises` call, **including the Tier-4
   last-resort — the ceiling is NEVER dropped** (this fixes **CRITICAL #2**: the original
   design dropped the ceiling in the fallback, which handed a beginner `bb_back_squat_highbar`
   via "any quadriceps exercise"). Because **all** exercises are tiered (C1 — fixes
   **CRITICAL #3**), the gate actually excludes heavy untiered compounds.

`_filter_exercises` gains a `max_difficulty` kwarg (same shape as the existing
`max_fatigue`): `if "max_difficulty" in kwargs and ex.difficulty_tier > kwargs["max_difficulty"]: continue`.

**Never-harmful invariant (the property the slice exists for):** for any client and any
generated plan, **no slot's exercise has `difficulty_tier > the client's ability for that
slot's family`** — unless it is the family's *floor* rung (lowest available, when the client
is below the ladder) or a powerlifter competition-main exemption. This is the headline test.

## C6 — One new bodyweight regression rung

The `vertical_push` ladder's lowest **bodyweight** rung is `bw_pike_push_up` at **tier 3** —
so a bodyweight-only **beginner** (ability 2) has no equipment-valid rung ≤ 2 and would be
floored *up* to a tier-3 pike (above ability). Add **one** exercise — `bw_incline_pike_push_up`
("Incline (Hands-Elevated) Pike Push-Up", `vertical_push`, primary `front_delts`/shoulders,
tier **2**, `fatigue_cost` 1, `["bodyweight"]`, `[gen_pop]`), the supported regression below
the full pike — sourced like SP-A's floor. (`horizontal_pull`'s `bw_inverted_row_bar`
self-scales by torso angle and is tagged tier 2, covering tier 1–2 for that family; note it
needs a `pull_up_bar`, so a *no-bar* client still has the SP-A pulling gap, already
coach-flagged — not re-solved here.)

## C7 — Bodyweight-main check-in guard

B1 places a **bodyweight** exercise (air squat fc2, knee push-up fc1) in a `main_compound`
slot for the first time (pre-B1 mains were always externally loaded). The check-in keys off
`slot_type == "main_compound"` to collect `actual_weight`, and `AutoRegulator` progresses
from weight — meaningless for a bodyweight lift. **Guard:** a slot whose exercise is
bodyweight (its `equipment_required == ["bodyweight"]`, or `target_weight is None`) →
check-in collects **reps + RPE, not weight**; the autoregulator **skips** it (no
`actual_weight` → already no-ops, stays `target_weight=None`). Rep-based auto-progression of
bodyweight mains is **B2**. B1's obligation is only: don't ask for a weight that doesn't
exist, don't crash, don't feed garbage to the autoregulator.

---

## Data model / migrations

- `Exercise.difficulty_tier: int` (in-memory DB; no migration for exercises).
- `ClientProfile.exercise_ability` JSON column → **Alembic 0021**. NULL-safe via
  selection-layer coercion (no backfill dependency).

## Error handling

- Missing/None `exercise_ability[family]` → experience-default (coerced in selection).
- Ability below a ladder's lowest rung, or equipment strips everything ≤ ability → **floor**
  rung (lowest equipment-valid); never above ability, never an untiered compound.
- No equipment-valid rung at all (e.g. no-bar client, horizontal_pull) → slot skips (existing
  SP-A behavior; coach already flagged).
- Bodyweight main → reps+RPE check-in, autoregulator skip.

## Testing (TDD, per component)

- **C1:** every exercise has a `difficulty_tier` in 1–5; the isolation/lunge override tables
  are exact; the 33 ladder rungs carry their Appendix-A tiers.
- **C2:** each `LADDERS` family is non-empty, strictly non-decreasing in `difficulty_tier`,
  every id exists, tier-4 rung is the family's barbell main (or strict pull-up for
  vertical_pull).
- **C3:** new client persists `exercise_ability`; a NULL legacy row selects as its
  `experience_level` without error; migration 0021 up/down.
- **C4:** survey level→ability mapping for all 6 families; skip → experience defaults; back
  from `ASK_ABILITY` lands on `ASK_EXPERIENCE`, and back from `ASK_LIMITATIONS` lands on
  `ASK_ABILITY`.
- **C5 — the headline guarantee:** for a **beginner** client (ability 2, various equipment),
  a fully generated plan has **no exercise with `difficulty_tier > 2`** in any anchor family
  (except a documented floor/powerlifter case); a "can't pull-up" client (vertical_pull
  ability 1) receives `machine_assisted_pull_up`/pulldown, **never** `bw_pull_up_pronated`;
  an advanced client still gets the barbell mains; **no day is emptied**.
- **C6:** a bodyweight-only beginner's vertical-push slot is ≤ tier 2 (gets the new incline
  pike, not the tier-3 pike).
- **C7:** a bodyweight main → check-in path collects reps+RPE (not weight); autoregulator
  leaves it untouched.

---

## Appendix A — The 6 sourced ladders (DB-verified ids, cited)

Sources per family: NSCA *Essentials of S&C* (3rd/4th), Rippetoe *Starting Strength*, Steven
Low *Overcoming Gravity* (2nd), ACSM *Guidelines*, Helms *Muscle & Strength Pyramid*,
Contreras *Glute Lab*. (Full per-rung rationale + citations live in the workflow record;
summarized here.)

```
squat:           bw_air_squat(2) → db_goblet_squat(2) → smith_back_squat(3)
                 → bb_back_squat_highbar(4) → bb_back_squat_lowbar(5)
hinge:           bw_glute_bridge(1) → cable_pull_through(2) → db_romanian_deadlift(3)
                 → bb_romanian_deadlift(4) → bb_deadlift_conventional(4) → bb_deficit_deadlift(5)
horizontal_push: bw_knee_push_up(1) → machine_chest_press(2) → bw_push_up(3)
                 → db_flat_bench_press(3) → bb_bench_press(4) → bw_weighted_dip(5)
vertical_push:   bw_incline_pike_push_up(2,NEW) → smith_shoulder_press(2) → bw_pike_push_up(3)
                 → db_seated_shoulder_press(3) → bb_overhead_press(4) → bb_push_press(5)
horizontal_pull: bw_inverted_row_bar(2) → db_single_arm_row(3) → db_chest_supported_row(3)
                 → bb_bent_over_row_pronated(4) → bb_pendlay_row(4) → bw_inverted_row_feet_elevated(5)
vertical_pull:   machine_assisted_pull_up(1) → cable_wide_grip_lat_pulldown(2)
                 → cable_neutral_grip_lat_pulldown(3) → bw_pull_up_pronated(4) → bw_weighted_pull_up(5)
```

Tier-4 barbell mains (cross-family invariant): squat=`bb_back_squat_highbar`,
hinge=`bb_deadlift_conventional`, h-push=`bb_bench_press`, v-push=`bb_overhead_press`,
h-pull=`bb_bent_over_row_pronated`. v-pull tier-4 = `bw_pull_up_pronated` (no barbell exists).

## Appendix B — Verified grounding (file:line)

- No difficulty field today; `Exercise` fields — `models.py:10-19`; `exercise_db.py` keys.
- `ClientProfile` has no ability field; JSON-column pattern = `features`/`coach_overrides`
  (`models.py:57,59`). Latest migration **0020** → new **0021**, `down_revision="0020"`.
- `experience_level` only in `_budget_volume` (`generator.py:107-125,557`); never in
  `_filter_exercises`/`_select_for_slot` — ability is a new, independent selection axis.
- `_filter_exercises(**kwargs)` guard block `generator.py:172-191` — `max_difficulty` slots
  in like `max_fatigue`. SP-A equipment filter at `generator.py:154-161` (compose for
  step-down).
- **Intake wiring is manual, not auto:** `handle_experience` returns `ASK_LIMITATIONS`
  (`bot.py:2086`); `_intake_predecessor` (`bot.py:2164-2190`) and `_render_intake_step`
  (`bot.py:2193-2232`) are per-state `if` dispatches; `_intake_states` (`bot.py:5531-5583`).
  All four edits in C4 are required.

## Appendix C — Non-ladder tiering rule (summary)

Isolation → flat 2 + {nordic_curl 5, sissy_squat 4, l_sit 4, toes_to_bar 3}. Lunge → flat 2
+ {bulgarian/cossack/single-leg/lateral 3}. Non-ladder compounds → rubric (guided/machine
2–3, barbell heavy/competition 4–5), assigned + reviewed in the C1 sourcing task. Non-anchor
slots gate against the **global** experience-derived scalar (beginner 2 / intermediate 3 /
advanced 4); per-family ability governs only the anchor ladders.

## Deferred to B2

Auto-advance a client's per-family ability/rung from check-in competence (persist
`actual_reps` vs prescribed; advance when the client masters the current rung at target RPE).
B1 deliberately sets ability once and reads it; it never writes `exercise_ability` from
telemetry.
