# Beyond Fit — Project Roadmap

A deterministic coaching engine that generates personalised workout and nutrition plans, delivered via Telegram with a human-in-the-loop admin approval step before every plan reaches the client.

**Core architectural rule**: all math (calories, macros, loads, volumes, exercise selection) lives in `domain/` as pure Python. LLMs are only used for (a) extracting structured data from free text, (b) narrating deterministic output for the client, and (c) generating coach digests. LLMs never set a single number that affects a client's programme.

---

## Complete System Flow

### New Client — Workout Onboarding

```
Client /start
  → Bot: avatar? (powerlifter / powerbuilder / gen_pop)
  → Bot: training days? (3–6)
  → Bot: experience level? (beginner / intermediate / advanced)
  → Bot: injuries/limitations? (free text)
  → Bot: email?
  → ProfileSnapshot created
  → WorkoutGenerator.generate()
       _resolve_split()      → day names (Push/Pull/Legs etc.)
       _budget_volume()      → per-muscle set caps (MEV→MRV)
       _calculate_rpe()      → week target RPE (block cycle wk1–5)
       _check_safety()       → hard-refuse on BP/cardiac/pregnancy/neuro
       _fill_slots() ×days   → TOML template → 4-tier exercise selection
                               warmup ramp, rest, tempo, cues, slot_order
       AutoRegulator         → first week: sets weight from % 1RM estimate
  → PendingApproval saved (workout_json + coaching_message)
  → Admin receives Telegram: plan summary + [Approve] [Reject]
     ├── Reject → admin types changes → LLM mutates JSON → re-present
     └── Approve → render_plan_pdf() → EmailService → client Telegram notify
  → WorkoutHistory(status="active") saved
```

### Client Check-in (weekly)

```
Client /checkin
  → Bot: "tell me about your week" (open prompt)
  → Client types freely (multiple messages, 90s timeout or /done)
  → extract_checkin() [LLM: Gemini Flash via OpenRouter, Instructor]
       → CheckInExtraction: exercises[], pain_flags[], fatigue, sleep
       → If clarifying_questions: bot asks ≤3 Qs → client answers → re-extract
  → Telemetry write-back: actual_weight / actual_rpe on WorkoutHistory slots
  → derive_plan_delta():
       Rule 1: safety (severe pain → coach flag)
       Rule 2: adherence (<60% → volume hold)
       Rule 3: fatigue (fatigue≥7 + sleep<6 → reactive deload)
       Rule 3b: RPE overshoot (3+ lifts RPE ≥ target+2 → reactive deload)
       Rule 3c: severe pain → deload
       Rule 4: progression (load increment + rotation)
  → render_digest() → admin receives coach summary
  → client.week_number += 1
  → WorkoutGenerator.generate() with prior_week → new plan → HITL loop
```

### Nutrition Onboarding

```
Client /diet
  → 18-question ConversationHandler:
       weight, height, age, sex, body fat %, goal (cut/bulk/maintain),
       aggressiveness, activity level, target rate, diet style,
       allergies, dislikes, religious restrictions, meals/day,
       cooking skill, cooking time, budget, medical conditions
  → NutritionProfile saved
  → NutritionService.generate():
       energy.py → BMR (Mifflin / Katch-McArdle) → TDEE → kcal target
       macros.py → protein (BW-based) → fat (% kcal) → carbs (remainder)
       meal_builder.py → PuLP LP solver → 7-day meal plan (68 foods)
  → NutritionPlan(status="draft") saved
  → Admin receives Telegram: macros summary + [Approve] [Discard]
     └── Approve → render_plan_pdf(nutrition_plan=plan) → EmailService
                 → client Telegram: "Your nutrition plan is ready!"
```

### Admin Tools

```
/review         → lists all pending PendingApproval + NutritionPlan(draft)
                   with inline Approve/Reject/Discard buttons
form-check      → client sends video → admin receives forwarded video
                   → admin replies text → LLM generates tips → client notified
                   → admin can edit tips before sending
```

### Deployment

```
docker compose up
  → db (postgres:16-alpine, healthcheck)
  → bot (python -m app.bot)
       SIGTERM/SIGINT → app.stop_running() graceful shutdown
       PTB error handler → admin Telegram notification on crash
       Rate limiter: 5-min per-client cooldown on generation
alembic upgrade head   → apply migrations 0001–0007
```

---

## Status Legend

- ✅ Done
- 🔄 In Progress
- ⬜ Not Started

---

## Phase 0 — Bug Fixes + Foundations ✅

> Prerequisite for everything. Gets the existing code clean and gives all later phases a solid base to build on.

### 0.1 Fix Live Bugs ✅
- [x] `slot_type` was never assigned in `WorkoutGenerator._fill_slots()` — slots now correctly tagged `main_lift` / `primary_accessory` / `isolation`
- [x] `CoachedWorkoutResponse` field name mismatch between model (`workout_data`) and route (`workout`) — unified to `workout`
- [x] All tests referenced `slot.exercise.primary_muscle` which doesn't exist on `WorkoutSlot` — rewrote using an `exercise_map` fixture
- [x] RPE assertions compared int to float (`slot.rpe == 9.0`) — fixed to `== 9`
- [x] `test_api.py` asserted `workout.client_id` which doesn't exist on `WorkoutWeek` — fixed to assert `week_number`
- [x] Added `test_slot_types_assigned` to lock in the slot_type fix

### 0.2 Restructure into `domain / services / adapters` ✅

Hexagonal architecture with `domain/`, `services/`, `adapters/` layers.

### 0.3 Add Alembic ✅
- [x] `alembic init` + configure `env.py` to use `SQLModel.metadata`
- [x] Initial migration capturing existing tables
- [x] Migrations 0002–0007 applied (profile snapshot, versioning, safety fields, nutrition tables, name + created_at)

### 0.4 ProfileSnapshot + Plan Versioning ✅

Every plan generation creates a `ProfileSnapshot` first and stores `profile_snapshot_id` on the plan.

### 0.5 Dev Tooling ✅

---

## Phase 1 — Evidence-Based Workout Generator ✅

### 1.1 Volume Landmarks ✅
- [x] Per-muscle MEV / MAV / MRV encoded in `domain/workout/constants.py`
- [x] `_validate_volume()` logs warnings when MRV exceeded or MEV not met
- [ ] **MRV hard-block** — currently only logs; does not reduce sets to MRV ceiling *(P2 polish)*

### 1.2 Session Ordering ✅
- [x] `slot_order: int` on WorkoutSlot
- [x] Push/pull balance check within ±20% weekly

### 1.3 Warm-up Generator ✅
- [x] `domain/workout/warmup.py` with build_warmup()
- [x] Heavy compounds: bar×8 → 50%×5 → 70%×3 → 85%×1 ramp
- [x] Only first compound per session gets full ramp
- [x] Cap at 6 warm-up sets

### 1.4 Exercise Rotation ✅
- [x] Main lifts: stable across full block
- [x] Secondary compounds: rotate every 2 weeks
- [x] Accessories: rotate weekly

### 1.5 Rest, Tempo & Coaching Cues ✅
- [x] `REST_BY_FATIGUE`, `TEMPO_BY_PATTERN`, `CUES_BY_PATTERN` wired into slots

### 1.6 Deload Automation + Split Decision Tree ✅
- [x] 2d/3d/4d/5d/6d splits with avatar-aware routing
- [x] `force_deload` parameter wired through entire pipeline
- [x] Deload = 70% volume, 60% load, RPE capped at 6

### 1.7 Safety Gates ✅
- [x] Hard-refuse on SBP >160, recent cardiac event <24wk, pregnancy 1st/3rd trimester, unexplained weight loss, progressive neuro deficits
- [x] `SafetyRefusalError` exception with condition keys

---

## Phase 2 — Conversational Check-ins + Auto-Regulation ✅

### 2.1 CheckIn Table ✅
### 2.2 Extraction Schema ✅
### 2.3 Extraction Pipeline ✅
- [x] OpenRouter → Gemini Flash with Instructor validation
- [x] `needs_coach_review` derived server-side

### 2.4 Prompt Templates ✅
### 2.5 Telegram UX ✅
- [x] Free-form `/checkin` with `CHECKIN_COLLECTING` / `CHECKIN_CLARIFYING` states
- [x] 90-second inactivity timeout

### 2.6 Auto-Regulation Rules ✅
- [x] `derive_plan_delta()` with safety → adherence → fatigue → progression priority
- [x] Reactive deload triggers (fatigue+sleep, RPE overshoot, severe pain)

### 2.7 CheckInService ✅

---

## Phase 3 — Deterministic Nutrition Engine ✅

### 3.1 Tables ✅
- [x] `NutritionProfile`, `NutritionPlan` tables with migrations

### 3.2 Energy Formulas ✅
- [x] `domain/nutrition/energy.py` — Mifflin-St Jeor / Katch-McArdle BMR, TDEE with bias-down, calorie floor

### 3.3 Macro Formulas ✅
- [x] `domain/nutrition/macros.py` — goal-based protein/fat/carb split with fiber and water

### 3.4 Meal Plan Builder ✅
- [x] `domain/nutrition/meal_builder.py` — PuLP-optimised 7-day meal plans
- [x] `domain/nutrition/food_db.py` — 68 curated foods
- [x] Cascade filtering: allergens → religious → diet type → dislikes → medical → budget → skill

### 3.5 Calibration Loop ✅
- [x] `NutritionService.calibrate_from_checkin()` — shifts kcal ±100-150 on BW trend divergence

### 3.6 Nutrition Intake Questionnaire ✅
- [x] 18-state `/diet` ConversationHandler
- [x] Feature gate removed — nutrition is a standard feature

---

## Phase 4 — WeasyPrint PDF ✅

- [x] Full template system with Jinja2
- [x] Workout + nutrition PDF rendering
- [x] `render_plan_pdf()` with draft watermark support
- [ ] **Studio design polish** — apply premium color palette, typography, exercise card anatomy *(P3 enhancement)*

---

## Phase 5 — Telegram Integration + HITL Pipeline ✅

### 5.1 Command Surface ✅
| Command | Status |
|---|---|
| `/start` — client intake | ✅ |
| `/diet` — nutrition questionnaire | ✅ |
| `/checkin` — free-form check-in | ✅ |
| `/plan` — view current active plan | ✅ |
| `/update_profile` — update profile mid-block | ✅ |
| `/review` — admin find pending approvals | ✅ |

### 5.2 HITL Approval Pipeline ✅
- [x] Workout plans: generate → admin approval → PDF → email dispatch
- [x] Nutrition plans: generate → admin approval → PDF → email dispatch
- [x] Approve/reject with inline keyboards
- [x] Status lifecycle: draft → pending → approved → active (prior → superseded)

### 5.3 Production Hardening ✅
- [x] `Dockerfile` with WeasyPrint system deps
- [x] `docker-compose.yml` with Postgres + bot services
- [x] Global PTB error handler → admin notification
- [x] Graceful SIGTERM/SIGINT shutdown
- [x] 5-minute per-client rate limiting

---

## Phase 6 — Template-Driven Training Days ✅

### 6.1 TOML Day Templates ✅
- [x] 12 day-type templates in `workout_constants.toml`
- [x] Push, Pull, Legs, Upper, Lower, Full Body A/B, Squat/Bench/Deadlift Day, Accessory/GPP, Upper/Lower Power/Hypertrophy

### 6.2 Template-Driven `_fill_slots()` ✅
- [x] 4-tier fallback: (pattern+muscle) → muscle → (pattern+group) → skip
- [x] `max_fatigue` raised to 20 (was 12)
- [x] Volume budgets raised: beginner=12, intermediate=16, advanced=20

### 6.3 Exercise Database Expansion ✅
- [x] Expanded from 100 → 179 exercises across 8 movement patterns
- [x] Pattern breakdown: isolation 79, hinge 16, horizontal_push 18, horizontal_pull 14, squat 14, vertical_pull 13, lunge 13, vertical_push 12
- [x] Critical gaps filled: vertical_pull (5→13), vertical_push (8→12), horizontal_pull (9→14), side_delts (2→6+), rear_delts (3→5+), biceps/triceps (4→8+ each), core (4→13), calves (4→7)

---

## Phase 7 — Round-1 Production Usability (18 issues) ✅

> 18 client/admin UX issues addressed. Migration 0008 added. All 93 tests green throughout.

### 7.1 Check-in & Logging ✅
- [x] **#1** Structured check-in: per-exercise weight → RPE → pain → general notes (`CHECKIN_EX_WEIGHT/RPE/PAIN/GENERAL` states)
- [x] **#3** `/log` command: manual set logging ConversationHandler (day → exercise → weight → RPE)

### 7.2 Client UX ✅
- [x] **#2** `/plan` shows today's session by default + [📅 Full Week] button
- [x] **#4** Limitations multi-select keyboard replaces free-text entry
- [x] **#6** 24h plan acknowledgment nudge (universal handler, group=-1)
- [x] **#8** Nutrition onboarding step counter ("Step X of 18:" on all questions)

### 7.3 Admin Flow ✅
- [x] **#5** Email delivery on plan approval (secondary to Telegram; non-fatal failure)
- [x] **#7** Form-check only from active plan — already implemented (no change needed)
- [x] **#9** `/review` index card with [Open #N] buttons per pending plan
- [x] **#10** `/review` sorted by `created_at` ASC (oldest plans first)
- [x] **#13** Admin approve confirmation step before PDF delivery
- [x] **#14** `/review_batch` command — group pending plans by (avatar, training_days)
- [x] **#15** `SafetyRefusalError` caught and routed to admin with condition key + reason

### 7.4 Admin Visibility ✅
- [x] **#11** Trend delta symbols (▲/▬/▼) in `_build_client_summary` history table
- [x] **#12** `edit_log` on PendingApproval — appended on each rejection/feedback cycle
- [x] **#16** Action badge (🟢/🟡/🔴) on check-in admin notification

### 7.5 Operations ✅
- [x] **#17** `/override` command — set coach exercise substitutions; stored in `ClientProfile.coach_overrides`; applied by `_apply_override()` in generator
- [x] **#18** Error deduplication in `handle_error` — MD5 hash, 5-minute window

**Schema** (migration 0008):
- `clientprofile.coach_overrides` (JSON)
- `pendingapproval.edit_log` (JSON), `cancelled_at` (DateTime)
- `workouthistory.acknowledged_at` (DateTime)

---

## Phase 8 — Round-2 Production Usability (20 issues) ✅

> 20 further refinements. Migration 0009 added. All 93 tests green throughout.

### 8.1 Check-in Refinements ✅
- [x] **#1** "Top-set weight" / "top-set RPE" wording (replaces ambiguous "what weight did you use")
- [x] **#2** "Hit all sets?" adherence keyboard after pain button (`CHECKIN_EX_SETS` state + `handle_structured_sets`)
- [x] **#3** Resumable structured check-in — `CHECKIN_RESUME` state; `CheckIn.structured_progress` persisted after each RPE entry; `handle_checkin_resume` restores state
- [x] **#4** Pre-skip already-logged slots on `/checkin`; client directed to `/log` to edit

### 8.2 Client UX ✅
- [x] **#5** `/plan today` uses `WorkoutHistory.plan_started_at` offset; rest-day detection
- [x] **#6** "📝 Other (describe)" option in limitations keyboard → `ClientProfile.limitations_notes` → shown in `_build_client_summary`
- [x] **#8** `/help` command with client and admin command sections

### 8.3 Admin Flow ✅
- [x] **#7** `check_plan_acknowledgment` skips when user has active conversation keys
- [x] **#9** `/review` + `/review_batch` merged — "🗂 Group by type" toggle at bottom of index card
- [x] **#10** Smart confirmation step — only shows when 2+ edits OR superseding plan <3 days old
- [x] **#12** Last 2 `edit_log` entries shown in rejection card ("Previous edits:")
- [x] **#19** Transaction safety — PDF rendered first (outside transaction), then atomic DB write block in `_do_approve_confirmed`

### 8.4 Admin Visibility ✅
- [x] **#11** Weighted trend delta — main_compound ×2.0, secondary_compound/accessory ×1.0, isolation ×0.5; min 3.0 weight-units before emitting
- [x] **#13** Badge priority fix — pain/adherence 🔴 > deload 🟢 > RPE jump 🔴 > normal 🟡
- [x] **#15** `/override <client_id>` lists overrides with [Remove] buttons; overrides shown in client summary
- [x] **#18** Silent clients section in `/review` (no check-in >10 days)
- [x] **#20** `WorkoutGenerator.last_generation_notes` — records deload trigger, override applied, safety gate skip; shown in admin approval card

### 8.5 Operations ✅
- [x] **#14** Idempotency tightened — blocks only if PendingApproval <60s old with coaching_message; deletes stale rows
- [x] **#16** Safety clearance button on gate notification → `handle_safety_clear` → `ClientProfile.safety_override_note`; generator bypasses gate when set
- [x] **#17** Error dedup with count-editing — existing admin message edited to show "×N" instead of silent suppression

**Schema** (migration 0009):
- `clientprofile.limitations_notes` (String), `safety_override_note` (String)
- `workouthistory.plan_started_at` (DateTime), `generation_notes` (JSON)
- `checkin.structured_progress` (JSON)

---

## What Remains

| # | Item | Priority | Effort | Notes |
|---|---|---|---|---|
| 1 | **Live end-to-end test** | P0 | Manual | Real Telegram: `/start` → approve → `/checkin` → week 2 |
| 2 | **`alembic upgrade head`** | P0 | 5 min | Applies all 9 migrations (0001–0009) |
| 3 | **MRV hard-block** | P2 | ~1h | `_validate_volume()` only logs; should cap sets at MRV ceiling |
| 4 | **Food DB expansion** | P3 | ~2h | Expand 68 → 150+ curated foods |
| 5 | **PDF design polish** | P3 | ~3h | Typography, colour palette, exercise card anatomy |
| 6 | **Scheduling & reminders** | P4 | ~2h | Automated check-in reminders on training days |
| 7 | **Analytics dashboard** | P4 | ~4h | Admin web: load trends, adherence heatmap |

---

## Data Model Summary

| Table | Migrations | Notes |
|---|---|---|
| `ClientProfile` | 0001–0003, 0006–0009 | Health screening + coach_overrides + limitations_notes + safety_override_note |
| `PendingApproval` | 0001, 0007–0008 | edit_log, cancelled_at |
| `WorkoutHistory` | 0001–0002, 0008–0009 | Status lifecycle + acknowledged_at + plan_started_at + generation_notes |
| `ProfileSnapshot` | 0002 | Immutable; every plan FKs to a snapshot |
| `CheckIn` | 0004, 0009 | raw_text + extraction_json + structured_progress |
| `NutritionProfile` | 0001, 0005 | 1-1 with ClientProfile, nullable |
| `NutritionPlan` | 0001, 0005 | Immutable, versioned, with PDF dispatch |

All migrations (0001–0009) are additive and nullable.

---

## What Must Never Happen

- An LLM call ever sets a calorie target, macro gram, training load, volume, exercise, or deload timing
- A plan is generated without first creating a `ProfileSnapshot` (reproducibility guarantee)
- An approved plan is mutated in-place — always version and supersede
- Pregnancy, cardiac, or acute-LBP clients receive a plan without coach-review routing
- An OpenRouter call is made without schema-enforced structured output + Instructor validation retries
