# Beyond Fit App — Full Pipeline Report

> **Vision**: A deterministic, evidence-based coaching engine that generates personalized weekly workout and nutrition plans, routes every plan through a human-in-the-loop (HITL) admin approval step, and delivers the final package to the client via Telegram and email. The LLM never sets loads, calories, or exercise selections — it only narrates, extracts free-form text, and applies coach edits.

---

## Table of Contents

1. [Project Vision & Philosophy](#1-project-vision--philosophy)
2. [Project Structure](#2-project-structure)
3. [Architecture Overview](#3-architecture-overview)
4. [Database Models](#4-database-models)
5. [Client Workflow](#5-client-workflow)
6. [Admin Workflow](#6-admin-workflow)
7. [Core Modules](#7-core-modules)
8. [Services Layer](#8-services-layer)
9. [Adapters Layer](#9-adapters-layer)
10. [Exercise Database](#10-exercise-database)
11. [Configuration](#11-configuration)
12. [Database Migrations](#12-database-migrations)
13. [Test Suite](#13-test-suite)
14. [Deployment](#14-deployment)
15. [Environment Variables](#15-environment-variables)
16. [Command Surface](#16-command-surface)
17. [What the LLM Is and Is Not Allowed to Do](#17-what-the-llm-is-and-is-not-allowed-to-do)
18. [Handler Reference](#18-handler-reference)
19. [Pending Roadmap Items](#19-pending-roadmap-items)

---

## 1. Project Vision & Philosophy

**Beyond Fit** is a personal coaching platform that delivers:

- **Algorithmically generated, evidence-based workout plans** — 5-week periodization blocks, avatar-aware splits, MEV→MRV volume budgets, per-session RPE targets, and automatic deload weeks.
- **Weekly check-in processing** — structured per-lift logging (weight → RPE → pain → adherence) plus free-form fallback; parsed into structured telemetry then fed into an auto-regulation engine that adjusts next week's plan.
- **Deterministic nutrition plans** — BMR/TDEE calculation, goal-based macro splits, and a linear-programming meal optimizer over a curated food database.
- **Human-in-the-loop approval** — every generated plan (workout or nutrition) is staged in a `PendingApproval` record and sent to the admin via Telegram before any client receives it. The admin can approve or reject with free-text feedback that gets applied to the JSON via LLM before re-presenting.
- **PDF delivery** — approved plans are rendered to PDF (WeasyPrint + Jinja2) and sent to the client via both Telegram and email.

**Core constraint**: deterministic math lives in `app/domain/`. LLMs only:
- narrate a generated plan as a coaching email,
- extract structured data from free-form check-in text,
- apply admin-provided edits to an already-generated JSON plan.

---

## 2. Project Structure

```
beyond_fit_app/
├── app/
│   ├── bot.py                         # Telegram bot — all handler logic (~3,000 lines)
│   ├── models.py                      # SQLModel ORM models (all DB tables)
│   ├── generator.py                   # WorkoutGenerator engine (~550 lines)
│   ├── exercise_db.py                 # 179-exercise in-memory database
│   ├── database.py                    # SQLAlchemy engine setup (SQLite/Postgres)
│   ├── settings.py                    # Pydantic-settings config loader
│   ├── main.py                        # FastAPI entry point
│   ├── routes.py                      # FastAPI route definitions
│   ├── container.py                   # Dependency injection container
│   │
│   ├── config/
│   │   └── workout_constants.toml     # Periodization, sets/reps, day templates
│   │
│   ├── domain/                        # Pure business logic — no framework deps
│   │   ├── workout/
│   │   │   ├── constants.py           # MEV/MAV/MRV, rest, tempo, cues, safety gates
│   │   │   ├── warmup.py              # Warmup set builder
│   │   │   └── autoregulation.py     # PlanDelta derivation + application rules
│   │   ├── checkin/
│   │   │   └── schema.py              # CheckInExtraction, ExerciseFeedback, PainFlag, PR
│   │   └── nutrition/
│   │       ├── energy.py              # BMR (Mifflin/Katch-McArdle), TDEE, goal adjustments
│   │       ├── macros.py              # Protein/fat/carb/fiber/water formulas
│   │       ├── meal_builder.py        # PuLP LP meal optimizer
│   │       └── food_db.py             # 68+ curated foods
│   │
│   ├── services/                      # Application layer — orchestration
│   │   ├── llm_service.py             # FlashCommunicationService
│   │   ├── email_service.py           # SMTP dispatch
│   │   ├── pdf_service.py             # PDF fallback (markdown → weasyprint)
│   │   ├── checkin_service.py         # CheckIn persistence + extraction pipeline
│   │   └── nutrition_service.py       # BMR→TDEE→macros→meal plan orchestration
│   │
│   └── adapters/                      # External integrations
│       ├── llm/
│       │   ├── openrouter.py          # OpenRouterClient (OpenAI-compatible)
│       │   └── extractors.py          # extract_checkin(), render_digest()
│       └── pdf/
│           ├── renderer.py            # render_plan_pdf() (WeasyPrint + Jinja2)
│           ├── css/                   # base, page, components, workout, nutrition CSS
│           └── templates/             # HTML Jinja2 templates
│
├── alembic/
│   ├── env.py
│   └── versions/
│       ├── 0001_initial_schema.py
│       ├── 0002_profile_snapshot_and_plan_versioning.py
│       ├── 0003_safety_fields.py
│       ├── 0004_checkin_table.py
│       ├── 0005_nutrition_tables.py
│       ├── 0006_clientprofile_email.py
│       ├── 0007_clientprofile_name_pending_created_at.py
│       ├── 0008_production_usability.py      ← round-1 new fields
│       └── 0009_round2_usability.py          ← round-2 new fields
│
├── tests/
│   ├── conftest.py                    # Shared fixtures (test DB, mock bot, rate-limit reset)
│   ├── test_bot_flow.py               # 6 bot integration tests (handler → DB → assertions)
│   ├── test_generator.py              # WorkoutGenerator unit tests
│   ├── test_api.py                    # FastAPI route tests
│   ├── test_pdf.py                    # PDF rendering tests
│   ├── test_checkin.py                # CheckIn extraction/schema tests
│   └── test_nutrition.py              # Nutrition math + meal builder tests
│
├── prompts/
│   └── checkin_extract.j2             # Jinja2 system prompt for check-in extraction
│
├── Plan.md                            # Project roadmap (phases + status)
├── PIPELINE_REPORT.md                 # This document
├── RUNBOOK.md                         # Operational guide
├── CLAUDE.md                          # Claude Code codebase guidance
├── pyproject.toml                     # Build system + dev dependencies
├── docker-compose.yml                 # Postgres + bot services
└── Dockerfile                         # WeasyPrint system deps + Python
```

---

## 3. Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│                     Telegram Bot (PTB)                       │
│  ConversationHandlers: intake / checkin / diet / log         │
│  Admin callbacks: approve / reject / review / override       │
└──────────────┬───────────────────────────────────────────────┘
               │
   ┌───────────▼───────────┐       ┌──────────────────────────┐
   │   WorkoutGenerator     │       │    NutritionService       │
   │  (app/generator.py)    │       │  (app/services/)          │
   │  Fully deterministic   │       │  BMR→TDEE→macros→meals    │
   └───────────┬───────────┘       └──────────┬───────────────┘
               │                              │
   ┌───────────▼──────────────────────────────▼───────────────┐
   │                    app/domain/                            │
   │  workout/: MEV/MRV, warmup, autoregulation, constants     │
   │  nutrition/: energy, macros, meal_builder, food_db        │
   │  checkin/: extraction schema (Pydantic)                   │
   └───────────────────────────────────────────────────────────┘
               │
   ┌───────────▼──────────────────────────────────────────────┐
   │                  app/adapters/                            │
   │  llm/: OpenRouterClient, extract_checkin, render_digest  │
   │  pdf/: render_plan_pdf (WeasyPrint + Jinja2)             │
   └───────────────────────────────────────────────────────────┘
               │
   ┌───────────▼──────────────────────────────────────────────┐
   │               PostgreSQL (or SQLite in dev)              │
   │  ClientProfile · WorkoutHistory · PendingApproval        │
   │  NutritionProfile · NutritionPlan · CheckIn · Snapshot   │
   └───────────────────────────────────────────────────────────┘
```

**Hexagonal layers**:
- `domain/` — pure Python business logic; no imports from services, adapters, or bot
- `services/` — orchestrates domain logic with persistence and external calls
- `adapters/` — wraps external systems (LLM API, PDF renderer)
- `bot.py` — Telegram presentation layer; calls services + adapters directly

---

## 4. Database Models

All models are SQLModel (SQLAlchemy + Pydantic hybrid). Migration history: `alembic/versions/`.

### ClientProfile
Primary key: `client_id: str` (Telegram user ID as string)

| Field | Type | Added | Description |
|---|---|---|---|
| `avatar` | str | 0001 | powerlifter / powerbuilder / gen_pop |
| `training_days` | int | 0001 | 2–6 days per week |
| `experience_level` | str | 0001 | beginner / intermediate / advanced |
| `limitations` | list[str] | 0001 | JSON — e.g. ["lower_back_pain"] |
| `available_equipment` | list[str] | 0001 | JSON — e.g. ["full_gym"] |
| `week_number` | int | 0001 | Current training week (increments at each check-in) |
| `active_workout_id` | Optional[int] | 0001 | Deprecated; use WorkoutHistory.status |
| `email` | Optional[str] | 0006 | For plan delivery |
| `name` | Optional[str] | 0007 | First name from Telegram |
| `features` | Optional[dict] | 0001 | Feature flags (JSON) |
| `coach_overrides` | Optional[dict] | 0008 | Exercise substitution map: {from_id: to_id} |
| `limitations_notes` | Optional[str] | 0009 | Free-text "Other" limitation description |
| `safety_override_note` | Optional[str] | 0009 | Physician clearance note; skips safety gate when set |
| **Health screening** | | 0003 | |
| `hypertension` | Optional[bool] | 0003 | |
| `systolic_bp` | Optional[int] | 0003 | mmHg — hard-refuse if >160 |
| `cardiac_history` | Optional[bool] | 0003 | |
| `cardiac_event_weeks_ago` | Optional[int] | 0003 | Hard-refuse if < 24 weeks |
| `osteoporosis` | Optional[bool] | 0003 | |
| `pregnancy_status` | Optional[str] | 0003 | none / 1st / 2nd / 3rd |
| `postpartum_weeks` | Optional[int] | 0003 | |
| `unexplained_weight_loss` | Optional[bool] | 0003 | Hard-refuse |
| `progressive_neuro_deficits` | Optional[bool] | 0003 | Hard-refuse |

### WorkoutHistory
Primary key: `history_id: int` (auto)

| Field | Type | Added | Description |
|---|---|---|---|
| `client_id` | str | 0001 | FK → ClientProfile |
| `week_number` | int | 0001 | |
| `workout_json` | str | 0001 | Serialised WorkoutWeek (includes actual_weight/rpe telemetry) |
| `status` | str | 0002 | draft / pending / approved / active / superseded |
| `block_number` | int | 0002 | Periodization block (1–N) |
| `version` | int | 0002 | Plan version counter |
| `profile_snapshot_id` | Optional[int] | 0002 | FK → ProfileSnapshot |
| `acknowledged_at` | Optional[datetime] | 0008 | Set when client responds to 24h nudge |
| `plan_started_at` | Optional[datetime] | 0009 | Set at approval time; used for `/plan today` offset |
| `generation_notes` | Optional[list] | 0009 | JSON list of generator audit notes (deload trigger, overrides applied) |

### PendingApproval
Primary key: `approval_uuid: str` (UUID4)

| Field | Type | Added | Description |
|---|---|---|---|
| `client_id` | str | 0001 | |
| `client_chat_id` | int | 0001 | BigInteger — Telegram chat ID |
| `client_name` | str | 0001 | |
| `client_email` | str | 0001 | |
| `workout_json` | str | 0001 | Plan awaiting review |
| `coaching_message` | str | 0001 | LLM-generated email draft |
| `created_at` | Optional[datetime] | 0007 | Used for idempotency window check |
| `edit_log` | Optional[list] | 0008 | JSON list of `{ts, feedback}` dicts — appended on each rejection |
| `cancelled_at` | Optional[datetime] | 0008 | Reserved for future cancellation flow |

*Deleted on approve or reject.*

### NutritionProfile
Primary key: `id: int`; unique index on `client_id`

| Field | Type | Description |
|---|---|---|
| `weight_kg, height_cm, age` | Optional[float/int] | Biometrics |
| `sex` | Optional[str] | male / female |
| `body_fat_pct` | Optional[float] | For Katch-McArdle BMR |
| `goal` | Optional[str] | fat_loss / lean_bulk / bulk / recomp / maintain |
| `aggressiveness` | Optional[str] | conservative / moderate / aggressive |
| `activity_level` | Optional[str] | sedentary / lightly_active / … |
| `target_rate_pct_per_week` | Optional[float] | e.g. 0.5% |
| `diet_style` | Optional[str] | omnivore / vegetarian / vegan / pescatarian / keto |
| `allergies, dislikes, religious_restrictions` | list[str] | JSON arrays |
| `meals_per_day` | int | Default 3 |
| `cooking_skill` | int | 1–4 |
| `cooking_time_min` | int | Default 30 |
| `budget_tier` | int | 1–3 |
| `medical_conditions` | list[str] | JSON |
| `updated_at` | Optional[datetime] | Last biometric update |

### NutritionPlan
Primary key: `id: int`

| Field | Type | Description |
|---|---|---|
| `client_id` | str | |
| `status` | str | draft / pending / approved / active / superseded |
| `kcal_target` | Optional[float] | |
| `protein_g, fat_g, carb_g, fiber_g, water_ml` | Optional[float] | Daily targets |
| `plan_json` | Optional[str] | 7-day meal plan (JSON) |
| `plan_markdown` | Optional[str] | Formatted for display |
| `rationale` | Optional[str] | Coach explanation |
| `approved_at` | Optional[datetime] | |
| `pdf_path` | Optional[str] | Path on disk |
| `created_at` | Optional[datetime] | |

### CheckIn
Primary key: `id: int`

| Field | Type | Added | Description |
|---|---|---|---|
| `client_id` | str | 0004 | |
| `raw_text` | str | 0004 | Combined free-form messages |
| `extraction_json` | Optional[str] | 0004 | CheckInExtraction (JSON); NULL while in-progress |
| `digest_markdown` | Optional[str] | 0004 | ≤6-line coach summary |
| `active_workout_plan_id` | Optional[int] | 0004 | FK → WorkoutHistory |
| `resulting_workout_plan_id` | Optional[int] | 0004 | FK → WorkoutHistory |
| `needs_coach_review` | bool | 0004 | Flagged for manual review |
| `created_at` | Optional[datetime] | 0004 | |
| `structured_progress` | Optional[dict] | 0009 | In-progress structured check-in state (slots, results, index) for resumable sessions |

### ProfileSnapshot
Primary key: `id: int`. Immutable snapshot of ClientProfile at plan-generation time. Linked from WorkoutHistory for full audit trail.

### Value Objects (nested JSON inside WorkoutHistory)

```
WorkoutWeek
  └── days: List[WorkoutDay]
        └── slots: List[WorkoutSlot]
              ├── slot_order, slot_type (main_compound/secondary_compound/accessory/isolation)
              ├── exercise_id, exercise_name, sets, reps, rpe
              ├── rest_seconds, tempo, coaching_cues
              ├── warmup_sets: List[WarmupSet]
              ├── target_weight         ← set at generation via AutoRegulator
              ├── actual_weight         ← written during check-in
              └── actual_rpe            ← written during check-in
```

---

## 5. Client Workflow

### 5.1 New Client Onboarding (`/start`)

```
Client sends /start
  │
  ├─ Existing profile found? → show active plan + /checkin prompt
  │
  └─ New client →
       ASK_AVATAR          (inline keyboard: powerlifter / powerbuilder / gen_pop)
         │
       ASK_DAYS            (inline keyboard: 3 / 4 / 5 / 6)
         │
       ASK_EXPERIENCE      (inline keyboard: beginner / intermediate / advanced)
         │
       ASK_LIMITATIONS     (multi-select inline keyboard)
         │  Options: lower_back_pain, knee_pain, shoulder_impingement,
         │           wrist_pain, hip_flexor_tightness, none, 📝 Other (describe)
         │  Toggle with [lim_toggle_*] callbacks; [✅ Done] to confirm
         │
         ├─ "Other" selected → ASK_LIMITATIONS_OTHER
         │     Client types free text → stored in ClientProfile.limitations_notes
         │
       ASK_EMAIL           (free text — validated format)
         │
         └─ handle_email()
               ├─ Creates ClientProfile (keyed to Telegram user ID)
               │     Stores: avatar, training_days, experience_level, limitations,
               │             email, name, limitations_notes (if set)
               ├─ Creates ProfileSnapshot
               └─ Calls run_generation_and_dispatch()
                     ├─ Idempotency check: if PendingApproval exists <60s with
                     │   coaching_message → block; else delete stale row
                     ├─ Rate limit check (60s per client)
                     ├─ WorkoutGenerator.generate(profile)
                     │     last_generation_notes reset on each call
                     │     safety gate: reads safety_override_note before hard-refuse
                     ├─ FlashCommunicationService.generate_coaching_message()
                     ├─ Inserts PendingApproval (workout_json + coaching_message)
                     └─ Sends plan + generator notes + approve/reject buttons to ADMIN
```

### 5.2 Weekly Check-in (`/checkin`)

```
Client sends /checkin
  │
  start_checkin()
    │
    ├─ Check for resumable CheckIn row (<2h old, extraction_json IS NULL)
    │   → CHECKIN_RESUME: offer [▶️ Resume] or [🔄 Start over]
    │      Resume: restores context.user_data from CheckIn.structured_progress
    │      Start over: clear and re-run /checkin
    │
    ├─ Load most recent WorkoutHistory (any status — pending OK for check-in)
    │
    ├─ Build main_compound slot list; filter out already-logged slots
    │   (actual_rpe IS NOT NULL → skip, notify client to use /log if needed)
    │
    ├─ Structured mode (main_compound slots present):
    │   For each unlogged main_compound slot:
    │     CHECKIN_EX_WEIGHT  → "What was your top-set weight? (kg)"
    │     CHECKIN_EX_RPE     → "What was your top-set RPE? (1–10)"
    │     CHECKIN_EX_PAIN    → keyboard: ✅ No pain / ⚠️ Discomfort / 🚨 Sharp pain
    │     CHECKIN_EX_SETS    → keyboard: ✅ All sets / ⚠️ Missed 1-2 / ❌ Cut short
    │     After each RPE: _persist_checkin_progress() → CheckIn.structured_progress
    │   CHECKIN_GENERAL → "Any other notes? (or /skip)"
    │   → _process_checkin()
    │
    └─ Fallback: free-text mode (no main_compound slots)
          CHECKIN_COLLECTING: accumulate messages (90s timeout or /done)
          → CHECKIN_CLARIFYING (if LLM has questions)
          → _process_checkin()

_process_checkin()
  ├─ extract_checkin(llm, raw_text, lift_catalog, prior_profile)
  │     → CheckInExtraction (Pydantic-validated)
  │     → ≤3 clarifying questions if needed → CHECKIN_CLARIFYING
  │
  ├─ Write telemetry back to WorkoutHistory.workout_json
  │     (actual_weight, actual_rpe per slot by exercise_id match)
  │
  ├─ derive_plan_delta(extraction, current_plan, prior_plan)
  │     → PlanDelta (load adjustments, deload flag, notes)
  │
  ├─ Badge logic (priority order):
  │     🔴 if pain_flags OR sets_cut
  │     🟢 if deload week (week % 5 == 0 or force_deload)
  │     🔴 if RPE jumped >1.5 from last week
  │     🟡 otherwise
  │
  ├─ Increment ClientProfile.week_number
  ├─ WorkoutGenerator.generate(profile, prior_week=current_week)
  ├─ FlashCommunicationService.generate_coaching_message()
  ├─ render_digest(llm, raw_text, extraction)  → ≤6-line summary
  ├─ Inserts new PendingApproval
  └─ Sends admin message: {badge} + client summary + digest + auto-regulation notes

  → POST_MENU state:
      ✅ Done
      💬 Send Update to Coach  → UPDATES_TEXT → free text to admin
      🎥 Form Check Request    → FORMCHECK_EXERCISE → FORMCHECK_MODE
                                   Tips: LLM generates → admin reviews → send
                                   Video: upload → forward to admin → reply → client
```

### 5.3 Manual Set Logging (`/log`)

```
Client sends /log
  │
  start_log() → loads active WorkoutHistory
    │
    LOG_SELECT_DAY       → inline keyboard of training days
    LOG_SELECT_EXERCISE  → inline keyboard of exercises in that day
    LOG_WEIGHT           → "What weight did you use? (or /skip)"
    LOG_RPE              → "What was your RPE? (or /skip)"
    │
    → Updates workout_json in place (actual_weight, actual_rpe on matched slot)
    → Saves WorkoutHistory
    → "✅ Logged."
```

### 5.4 View Active Plan (`/plan`)

```
Client sends /plan
  │
  client_plan()
    ├─ Loads active WorkoutHistory
    ├─ Compute today's day index:
    │     If plan_started_at set: day_offset = (now - plan_started_at).days % len(days)
    │     Else: fallback to datetime.now().weekday() % len(days)
    │
    ├─ If today_idx < len(week.days):
    │     Show today's session: "Today's Session — {day_name} (Week N)"
    │     Each slot: order. name — sets×reps @ RPE → Xkg
    │     [📅 Full Week] button → handle_plan_full_week()
    │
    └─ If rest day: "🛌 Today is a rest day. /plan week to see full schedule."
```

### 5.5 Profile Update (`/update_profile`)

Reuses the same intake ConversationHandler with `context.user_data['update_profile_mode'] = True`. Existing values shown as defaults; client can skip or change each field.

### 5.6 Nutrition Intake (`/diet`)

```
Client sends /diet  (or /diet quick for defaults)
  │
  ├─ /diet quick: skip biometric questions, use safe defaults (2000 kcal, moderate)
  │
  └─ Full intake (18 questions, each prefixed "Step X of 18:"):
       DN_WEIGHT → DN_HEIGHT → DN_AGE → DN_SEX → DN_BODYFAT →
       DN_GOAL → DN_AGGRESSIVENESS → DN_ACTIVITY → DN_TARGET_RATE →
       DN_DIET_STYLE → DN_ALLERGIES → DN_DISLIKES → DN_RELIGIOUS →
       DN_MEALS → DN_COOKING_SKILL → DN_COOKING_TIME → DN_BUDGET → DN_MEDICAL
     │
     _submit_nutrition()
       ├─ Saves NutritionProfile
       ├─ NutritionService.generate(client_id)
       │     energy.py → BMR → TDEE → kcal target
       │     macros.py → protein/fat/carb/fiber/water
       │     meal_builder.py → PuLP LP solver → 7-day plan
       ├─ Saves NutritionPlan(status='draft')
       └─ Sends macros summary to ADMIN for approval
```

### 5.7 Help (`/help`)

Returns static command list. Clients see client commands; admin sees both client and admin sections.

### 5.8 24h Plan Acknowledgment

On every client message, `check_plan_acknowledgment()` (group=-1 universal handler) runs:
- Skips if user has active conversation keys (`checkin_history_id`, `log_history_id`, `avatar`, `dn_weight`)
- Queries active WorkoutHistory where `acknowledged_at IS NULL` and `plan_started_at` > 24h ago
- If found: sets `acknowledged_at = now()` immediately, sends "👋 Quick check-in on your new plan — how's it feeling so far?" with [👍 Good] [😐 OK] [❓ Question] buttons

---

## 6. Admin Workflow

### 6.1 Plan Review Dashboard (`/review`)

```
Admin sends /review
  │
  admin_review()
    ├─ Queries PendingApproval (ORDER BY created_at ASC — oldest first)
    ├─ Queries NutritionPlan(draft)
    ├─ Queries silent clients (no CheckIn in >10 days) → shown at bottom
    │
    └─ Sends index card:
          📋 Pending Plans (N)
          ━━━━━━━━━━━━━━━━━
          1. Name  ·  avatar  ·  Xd  ·  Week N
          2. ...
          [Open #1]  [Open #2]  ...
          🔇 Silent (no check-in >10d): Client1, Client2
          [🗂 Group by type]    ← toggle to batch view
```

Each [Open #N] button → `handle_open_pending_item()`:
- Fetches that single PendingApproval
- Sends full plan card: client summary + programme (day/exercise/sets/reps/RPE/load)
- Buttons: [✅ Approve] [❌ Reject]

[🗂 Group by type] → `handle_review_toggle()` → `admin_review_batch()`:
- Groups by (avatar, training_days)
- One message per bucket with [Open] buttons per client

`_build_client_summary(client_id)` includes:
- Name, email, today's date, avatar, experience, training days, week number
- Limitations (structured list + free-text notes if set)
- Coach overrides (if any): "original_id→replacement_id"
- Biometrics (from NutritionProfile): weight, height, age, sex, BF% — date logged
- Nutrition goal and aggressiveness
- Last 4 weeks: week#, status, trend delta (▲/▬/▼), top compound lifts with actual weight + RPE

**Weighted trend delta** in history: `main_compound × 2.0`, `secondary_compound × 1.0`, `accessory × 1.0`, `isolation × 0.5`; requires ≥3.0 total weight-units before emitting delta symbol.

### 6.2 Approve Plan

```
Admin taps "✅ Approve"
  │
  handle_admin_approve()
    ├─ Load PendingApproval
    ├─ Smart confirmation check:
    │     edit_count = len(pending.edit_log or [])
    │     superseding_recent = active plan exists with plan_started_at < 3 days ago
    │     needs_confirm = edit_count >= 2 OR superseding_recent
    │
    ├─ If NOT needs_confirm → _do_approve_confirmed() directly (no extra tap needed)
    └─ If needs_confirm → show "⚠️ Confirm approval for {name} — Week N? ({reason})"
                          [✅ Yes, send it]  [↩️ Go back]
                          Tap Yes → approve_confirmed: callback → _do_approve_confirmed()

_do_approve_confirmed(query, approval_id, context)
  ├─ 1. Render PDF (outside transaction — safe to fail)
  │     render_plan_pdf(client, out_path, workout_history, draft_watermark=False)
  │     Fallback: PdfService.generate_pdf(coaching_message) on render error
  │
  ├─ 2. Deliver to client (outside transaction)
  │     bot.send_document(client_chat_id, pdf_bytes)  ← primary delivery
  │     EmailService.send_plan(email, pdf_bytes)       ← secondary (failure is non-fatal)
  │
  └─ 3. Single atomic DB transaction:
        ├─ Mark existing active WorkoutHistory rows → "superseded"
        ├─ Insert WorkoutHistory(status="active", plan_started_at=now())
        ├─ Delete PendingApproval row
        └─ commit()
```

### 6.3 Reject Plan (with Coach Edits)

```
Admin taps "❌ Reject"
  │
  handle_admin_reject() → ADMIN_FEEDBACK state
    │
    Admin types free-text feedback:
    e.g. "Replace deadlifts with trap bar — client has lower back history"
    │
    handle_admin_feedback()
      ├─ FlashCommunicationService.apply_coach_edits(workout_json, feedback)
      │     LLM mutates JSON, returns raw JSON only (temperature 0.1)
      ├─ Re-generate coaching message for mutated plan
      ├─ Append to edit_log: {ts: ISO8601, feedback: text}
      ├─ Update PendingApproval.workout_json + coaching_message
      └─ Re-present plan with last 2 edit_log entries shown + [Approve] [Reject] buttons
```

### 6.4 Exercise Overrides (`/override`)

```
/override <client_id> <from_id> <to_id>   → set substitution; takes effect next generation
/override <client_id>                      → list current overrides with [Remove] buttons
callback override_remove:<client_id>:<from_id> → remove that override
```

Stored in `ClientProfile.coach_overrides: {original_exercise_id: replacement_exercise_id}`.
Applied in `WorkoutGenerator._apply_override()` after each tier selection.
Shown in `_build_client_summary` if set.

### 6.5 Safety Gate Management

When `run_generation_and_dispatch` catches a `SafetyRefusalError`:
- Admin receives: "⚠️ Safety gate triggered for {name} — Condition: {key}" + [✅ Mark cleared by physician] button
- Client receives: "Your coach needs to review your profile before we can generate a plan."

`handle_safety_clear(callback: safety_clear:<client_id>:<condition_key>)`:
- Sets `ClientProfile.safety_override_note = "Cleared by physician for {condition} — {date}"`
- Next generation: `_check_safety()` returns immediately if `safety_override_note` is set

### 6.6 Error Notifications

`handle_error()` catches all unhandled PTB exceptions:
- MD5 hash of error string (first 200 chars) → 5-minute dedup window
- First occurrence: sends message to admin, stores `message_id` in `_error_message_ids`
- Repeat within window: edits the existing message to append count (e.g. "⚠️ Bot error (×3):")
- Fully unique errors: always sent immediately

### 6.7 Nutrition Approval

Same flow as workout approval:
- Approve → render nutrition PDF → email → Telegram → NutritionPlan status → "active"
- Reject (Discard) → NutritionPlan deleted

### 6.8 Form Check Review

```
Client selects exercise → Tips or Video

Tips path:
  → generate_exercise_tips(exercise_name, experience, avatar)
  → Admin: [tips draft] [Send ✅] [Edit ✏️]
  → Send → forwarded to client
  → Edit → admin types revised text → sent to client

Video path:
  → Client uploads video → forwarded to admin with caption
  → Admin replies → reply forwarded to client
```

---

## 7. Core Modules

### 7.1 `app/generator.py` — WorkoutGenerator

The central engine. Fully deterministic (no randomness). New: `last_generation_notes` instance attribute accumulates audit notes on every `generate()` call.

```
generate(client, prior_week=None, force_deload=False)
  │
  ├─ self.last_generation_notes = []   ← reset on every call
  ├─ _check_safety(client)
  │     If client.safety_override_note → append "safety_gate_skipped: ..." and return
  │     Else: hard-refuse on cardiac/pregnancy/neuro conditions → SafetyRefusalError
  │
  ├─ _resolve_split(avatar, days)      → ["Upper", "Lower", "Push", "Pull", "Legs"]
  ├─ _budget_volume(experience)        → {muscle_group: max_sets}
  ├─ _calculate_rpe(week_number)       → float (5-week block cycle)
  │
  ├─ deload = force_deload OR _is_deload(week_number)
  │   If deload: reduce budget × 0.7, cap RPE at 6
  │   Append: "deload_week: RPE=X trigger=..."
  │
  └─ For each day_name in split:
       _fill_slots(day_name, client, budget, rpe, prior_week, force_deload=deload)
         │
         ├─ Load day template from workout_constants.toml
         └─ For each slot_spec in template:
              ├─ _filter_exercises(client, pattern, muscle, ...)
              ├─ _rotation_idx(week_number, slot_type, pool_size)
              ├─ _select_for_slot(spec, client, used_ids)  — 4-tier fallback:
              │     Tier 1: (pattern + muscle) match
              │     Tier 2: muscle only
              │     Tier 3: (pattern + group)
              │     Tier 4: skip slot
              │     Each tier result passes through _apply_override(ex, client)
              ├─ _apply_override(ex, client)
              │     Reads ClientProfile.coach_overrides
              │     If substitution found: append "override_applied: X → Y"
              ├─ build_warmup(working_load, ...)
              ├─ Assign sets / reps / rest / tempo / cues from constants
              └─ AutoRegulator.calculate_next_load(...)  if prior_week
```

`last_generation_notes` is read by `run_generation_and_dispatch` after `generate()` returns and displayed in the admin approval card.

**Split routing by avatar + days**:

| Days | powerlifter | powerbuilder | gen_pop |
|---|---|---|---|
| 2 | Full A / Full B | Full A / Full B | Full A / Full B |
| 3 | Squat / Bench / Deadlift | Upper / Lower / Full | Full A / Full B / Full A |
| 4 | Squat / Bench / Deadlift / Accessory | Upper Power / Lower Power / Upper Hyp / Lower Hyp | Upper / Lower / Upper / Lower |
| 5 | Upper / Lower / Push / Pull / Legs | Upper / Lower / Push / Pull / Legs | Upper / Lower / Push / Pull / Legs |
| 6 | Push / Pull / Legs × 2 | Push / Pull / Legs × 2 | Push / Pull / Legs × 2 |

**RPE periodization** (5-week block):

| Week | RPE | Note |
|---|---|---|
| 1 | 7.0 | Accumulation start |
| 2 | 7.5 | |
| 3 | 8.0 | |
| 4 | 9.0 | Peak |
| 5 | 6.0 | Deload |

**AutoRegulator** (RPE error correction):
```
rpe_error = actual_rpe - target_rpe
load_delta = rpe_error × 4% × current_load
next_load = current_load - load_delta + progressive_overload_increment
```

**Safety gate** — `SafetyRefusalError` raised on:
- SBP > 160 mmHg
- Cardiac event < 24 weeks ago
- Pregnancy 1st or 3rd trimester
- Unexplained weight loss
- Progressive neurological deficits
- Bypass: `safety_override_note` set on ClientProfile

### 7.2 `app/domain/workout/autoregulation.py`

`derive_plan_delta(extraction, current_plan, prior_plan) → PlanDelta`

Rule priority (first match wins):

| Priority | Trigger | Action |
|---|---|---|
| 1 | Pain flag (any severity) | Lower RPE/sets on affected exercises; flag for coach |
| 2 | Adherence < 50% | Hold volume (no progression) |
| 3 | Fatigue ≥ 8 + sleep ≤ 4 | Trigger deload |
| 3b | 3+ lifts with RPE ≥ target + 2 | Trigger deload |
| 3c | Severe pain flag | Trigger deload |
| 4 | RPE feedback (normal range) | Adjust load ±4% per lift |
| 5 | Personal record logged | Add note for coach |

### 7.3 `app/domain/nutrition/`

**Energy pipeline**:
```
calculate_bmr(weight, height, age, sex, body_fat_pct)
  → Mifflin-St Jeor (no BF%) or Katch-McArdle (with LBM)

calculate_tdee(bmr, activity_level)
  → BMR × multiplier (1.2–1.9), with 10% conservative bias

apply_goal_adjustment(tdee, goal, aggressiveness)
  → fat_loss: −250 to −500 kcal
  → lean_bulk: +250 to +500 kcal
  → bulk: +500 to +1000 kcal

apply_calorie_floor(target, bmr, weight_kg, sex)
  → Ensures target ≥ BMR × 0.95
```

**Macro split**: Protein 2.0–2.4 g/kg, Fat 30–35% kcal, Carbs remainder, Fiber 14–21 g/day, Water 30–35 mL/kg/day.

**Meal optimizer** (`meal_builder.py`): PuLP LP, 7-day plan, cascade filter: allergens → religious → diet_type → dislikes → medical → budget → cooking_skill.

---

## 8. Services Layer

### `FlashCommunicationService` (`app/services/llm_service.py`)

| Method | Temperature | Purpose |
|---|---|---|
| `generate_coaching_message(profile, workout)` | 0.4 | Format workout JSON as motivating client email |
| `generate_exercise_tips(exercise, experience, avatar)` | 0.3 | Technique breakdown (setup / execution / errors) |
| `apply_coach_edits(workout_json, feedback)` | 0.1 | Mutate workout JSON per admin text; return raw JSON only |

All methods call OpenRouter (`google/gemini-2.5-flash`) via the OpenAI SDK.

### `NutritionService` (`app/services/nutrition_service.py`)

| Method | Purpose |
|---|---|
| `generate(client_id)` | Full pipeline: load NutritionProfile → BMR → TDEE → kcal → macros → 7-day meal plan → NutritionPlan(draft) |
| `calibrate_from_checkin(extraction)` | Adjust kcal ±100–150 if weight trend diverges from target |

### `EmailService` (`app/services/email_service.py`)

SMTP dispatch of PDF attachment to client email. Called as secondary delivery after Telegram; failure is logged but non-fatal.

### `CheckInService` (`app/services/checkin_service.py`)

Persists CheckIn records; orchestrates `extract_checkin()` → `render_digest()` pipeline.

---

## 9. Adapters Layer

### `OpenRouterClient` (`app/adapters/llm/openrouter.py`)

```python
class OpenRouterClient:
    def complete(system: str, user: str, temperature: float) -> str
```

Reads `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, `LLM_MODEL_ID` from env. Default: `google/gemini-2.5-flash`.

### `extract_checkin` / `render_digest` (`app/adapters/llm/extractors.py`)

- `extract_checkin(llm, raw_text, lift_catalog, prior_profile) → CheckInExtraction`
  - Retry loop (3 attempts, exponential backoff)
  - Jinja2 prompt template from `prompts/checkin_extract.j2`
  - Pydantic validation on response JSON
  - Sets `needs_coach_review` flag

- `render_digest(llm, raw_text, extraction, client_name, week_number) → str`
  - ≤6-line bullet summary for admin card

### `render_plan_pdf` (`app/adapters/pdf/renderer.py`)

```python
render_plan_pdf(client, out_path, workout_history=None, nutrition_plan=None, draft_watermark=False)
```

- Jinja2 → HTML → WeasyPrint → PDF bytes
- CSS: base, page, components, workout, nutrition
- Inline charts (matplotlib)
- `plan_started_at` written to `WorkoutHistory` at approval time

---

## 10. Exercise Database

**179 exercises** across 8 movement patterns (`app/exercise_db.py`).

Each entry schema:

| Field | Type | Example |
|---|---|---|
| `exercise_id` | str | "bb_back_squat_highbar" |
| `name` | str | "Barbell High-Bar Back Squat" |
| `movement_pattern` | str | squat / hinge / horizontal_push / vertical_push / horizontal_pull / vertical_pull / lunge / isolation |
| `primary_muscle` | str | quadriceps / hamstrings / glutes / chest / lats / shoulders / biceps / triceps / calves / core |
| `secondary_muscles` | list[str] | |
| `fatigue_cost` | int | 1–5 (5 = heavy compound) |
| `equipment_required` | list[str] | barbell / dumbbells / cable_machine / bodyweight / smith_machine |
| `avatar_tags` | list[str] | powerlifter / powerbuilder / gen_pop |
| `biomechanical_focus` | Optional[str] | lengthened_position / mid_range / shortened_position |

**Pattern distribution**:

| Pattern | Count |
|---|---|
| isolation | 79 |
| hinge | 16 |
| horizontal_push | 18 |
| horizontal_pull | 14 |
| squat | 14 |
| vertical_pull | 13 |
| lunge | 13 |
| vertical_push | 12 |
| **Total** | **179** |

**Coach overrides** apply after exercise selection, substituting any exercise with the coach-specified replacement (stored in `ClientProfile.coach_overrides`). If the replacement ID doesn't exist in the DB, the original is returned unchanged.

---

## 11. Configuration

### `app/config/workout_constants.toml`

**[volume_budget]**: beginner 12 sets, intermediate 16, advanced 20; deload_factor 0.7.

**[periodization]**: rpe_map [7.0, 7.5, 8.0, 9.0, 6.0], block_length 5, deload_week 5.

**[session]**: max_fatigue 20.

**[day_templates.*]** — 15 templates (Push, Pull, Legs, Upper, Lower, Full Body A/B, Squat/Bench/Deadlift Day, Accessory/GPP, Upper/Lower Power/Hypertrophy).

Each template defines 3–6 slot specs with `type` (main_compound/secondary_compound/accessory/isolation), `pattern`, `muscle`, `min_fat`, `max_fat`, `sets`, `reps`.

### `app/domain/workout/constants.py`

Volume landmarks per muscle group:

| Muscle | MEV | MAV | MRV |
|---|---|---|---|
| chest | 8 | 12–20 | 22 |
| back | 10 | 14–22 | 25 |
| shoulders | 8 | 12–20 | 26 |
| arms | 4 | 10–18 | 26 |
| quadriceps | 8 | 12–18 | 20 |
| hamstrings | 6 | 10–16 | 20 |
| glutes | 6 | 10–18 | 22 |
| calves | 8 | 12–16 | 20 |

---

## 12. Database Migrations

All migrations are additive and nullable — no data loss on upgrade or downgrade.

| Migration | Key Changes |
|---|---|
| `0001_initial_schema` | ClientProfile, WorkoutHistory, NutritionProfile, NutritionPlan |
| `0002_profile_snapshot_and_plan_versioning` | ProfileSnapshot table; add status/block_number/version to WorkoutHistory |
| `0003_safety_fields` | Health screening columns on ClientProfile |
| `0004_checkin_table` | CheckIn table |
| `0005_nutrition_tables` | Expanded nutrition fields (JSON arrays) |
| `0006_clientprofile_email` | email column on ClientProfile |
| `0007_clientprofile_name_pending_created_at` | name on ClientProfile; created_at on PendingApproval |
| `0008_production_usability` | coach_overrides (ClientProfile); edit_log, cancelled_at (PendingApproval); acknowledged_at (WorkoutHistory) |
| `0009_round2_usability` | limitations_notes, safety_override_note (ClientProfile); plan_started_at, generation_notes (WorkoutHistory); structured_progress (CheckIn) |

Run all pending: `alembic upgrade head`

---

## 13. Test Suite

**93 tests** across 6 files. `asyncio_mode = "auto"` in `pyproject.toml`.

| File | Tests | What it covers |
|---|---|---|
| `test_generator.py` | ~40 | WorkoutGenerator unit tests (splits, RPE, volume, autoregulator, safety gate, overrides) |
| `test_api.py` | ~15 | FastAPI `/generate` and `/generate_and_coach` routes |
| `test_pdf.py` | ~10 | PDF rendering (workout + nutrition) |
| `test_checkin.py` | ~12 | CheckInExtraction schema + autoregulation rules |
| `test_nutrition.py` | ~10 | BMR, TDEE, macro math, meal builder |
| `test_bot_flow.py` | 6 | Bot handler integration (real SQLite, mocked Telegram/LLM/email) |

**Bot integration test approach**:
- Call handler coroutines directly (`await handle_email(update, ctx)`)
- Real in-memory SQLite via `test_engine(tmp_path)` fixture
- `patch_engine` monkeypatches `app.bot.engine` to the test DB
- All external services mocked: LLM, email, PDF, Telegram API

**Bot integration test cases**:
1. `test_intake_creates_profile` — intake creates ClientProfile in DB
2. `test_intake_creates_pending_approval` — intake creates PendingApproval + notifies admin
3. `test_admin_approves_workout_activates_history` — calls `handle_admin_approve_confirmed` with `approve_confirmed:<uuid>`; verifies WorkoutHistory(active), PendingApproval deleted, send_document called
4. `test_checkin_writes_telemetry` — check-in writes actual_weight + actual_rpe back to WorkoutHistory
5. `test_checkin_increments_week_and_generates_plan` — check-in increments week_number, creates new PendingApproval
6. `test_rate_limit_blocks_second_call` — second immediate generation is rate-limited (1 plan created, "please wait" sent)

---

## 14. Deployment

### `docker-compose.yml`

```yaml
services:
  db:
    image: postgres:16
    environment: POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD
    volumes: postgres_data:/var/lib/postgresql/data

  bot:
    build: .
    depends_on: [db]
    environment: TELEGRAM_BOT_TOKEN, DATABASE_URL, OPENROUTER_API_KEY, ...
    command: python -m app.bot
```

### `Dockerfile`

```dockerfile
FROM python:3.11-slim
# WeasyPrint system dependencies (Cairo, Pango, libffi)
RUN apt-get install -y libcairo2 libpango-1.0-0 ...
COPY . /app
RUN pip install -e ".[dev]"
```

### Running locally

```bash
pip install -e ".[dev]"
alembic upgrade head
python -m app.bot
uvicorn app.main:app --reload  # optional FastAPI
pytest
```

---

## 15. Environment Variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | — | Telegram bot token |
| `ADMIN_TELEGRAM_ID` | ✅ | — | Telegram chat ID for admin messages + approval flow |
| `DATABASE_URL` | ❌ | SQLite | PostgreSQL connection string |
| `OPENROUTER_API_KEY` | ✅ | — | API key for OpenRouter LLM calls |
| `OPENROUTER_BASE_URL` | ❌ | https://openrouter.ai/api/v1 | Override for self-hosted |
| `LLM_MODEL_ID` | ❌ | google/gemini-2.5-flash | Model for all LLM calls |
| `SMTP_HOST` | ❌ | — | SMTP server hostname (plan email delivery) |
| `SMTP_PORT` | ❌ | 587 | |
| `SMTP_USER` | ❌ | — | |
| `SMTP_PASS` | ❌ | — | |
| `SMTP_FROM` | ❌ | — | From address for plan emails |

---

## 16. Command Surface

| Command | Available to | Handler | Description |
|---|---|---|---|
| `/start` | Client | `start_conversation` | Intake: avatar → days → experience → limitations → email → generate plan |
| `/update_profile` | Client | `start_update_profile` | Re-runs intake with pre-filled values |
| `/checkin` | Client | `start_checkin` | Structured check-in (weight/RPE/pain/adherence per lift); resumable |
| `/log` | Client | `start_log` | Manual set logging: select day → exercise → weight → RPE |
| `/plan` | Client | `client_plan` | Show today's session (uses plan_started_at offset); [Full Week] button |
| `/diet` | Client | `start_diet` | 18-question nutrition intake; `/diet quick` for fast defaults |
| `/help` | Both | `handle_help` | Static command list; admin sees admin commands too |
| `/cancel` | Both | `cancel` | Cancel any active conversation |
| `/review` | Admin | `admin_review` | Index card of pending plans + silent clients; [Open] per plan; [Group by type] toggle |
| `/review_batch` | Admin | `admin_review_batch` | Same plans grouped by (avatar, training_days) |
| `/override` | Admin | `handle_override` | `/override <id> <from> <to>` to set; `/override <id>` to list with [Remove] buttons |

**Inline callback patterns**:

| Pattern | Handler | Purpose |
|---|---|---|
| `^approve:` | `handle_admin_approve` | Show confirmation step (or bypass if no edits/recent plan) |
| `^approve_confirmed:` | `handle_admin_approve_confirmed` | Execute approval |
| `^reject:` | `handle_admin_reject` | Enter ADMIN_FEEDBACK state |
| `^open_pending:` | `handle_open_pending_item` | Expand single plan card |
| `^review_toggle_batch$` | `handle_review_toggle` | Switch to batch view |
| `^safety_clear:` | `handle_safety_clear` | Set safety_override_note on client profile |
| `^override_remove:` | `handle_override_remove` | Remove one coach override |
| `^ack_` | `handle_plan_ack` | Handle 24h plan acknowledgment response |
| `^plan_full_week$` | `handle_plan_full_week` | Show full week plan |
| `^ci_resume:\|^ci_restart$` | `handle_checkin_resume` | Resume or restart in-progress check-in |
| `^pain_` | `handle_structured_pain` | Accept pain flag in structured check-in |
| `^sets_` | `handle_structured_sets` | Accept set adherence in structured check-in |

---

## 17. What the LLM Is and Is Not Allowed to Do

| Allowed | Not allowed |
|---|---|
| Narrate a generated workout as a coaching email | Select exercises |
| Extract structured data from free-form check-in text | Set load, volume, or RPE |
| Generate technique tips for a given exercise | Modify the plan without an explicit admin instruction |
| Apply admin-provided free-text edits to an existing plan JSON | Generate calorie or macro targets |
| Produce a ≤6-line check-in digest for the admin | Override safety gates |

---

## 18. Handler Reference

Complete map of all handlers in `app/bot.py`:

### Client Intake Flow

| Function | State / Entry | Purpose |
|---|---|---|
| `start_conversation` | `/start` | Entry point; routes to plan if profile exists |
| `handle_avatar` | `ASK_AVATAR` | Store avatar selection |
| `handle_days` | `ASK_DAYS` | Store training days |
| `handle_experience` | `ASK_EXPERIENCE` | Store experience level; show limitations keyboard |
| `handle_limitations_toggle` | `ASK_LIMITATIONS` (callback `lim_toggle_*`) | Toggle limitation on/off |
| `handle_limitations_confirm` | `ASK_LIMITATIONS` (callback `lim_confirm`) | Finalize limitations; branch to "Other" if selected |
| `handle_limitations_other` | `ASK_LIMITATIONS_OTHER` | Store free-text limitation note |
| `handle_limitations` | `ASK_LIMITATIONS` (text fallback) | Legacy free-text entry |
| `handle_email` | `ASK_EMAIL` | Validate email; create ClientProfile; run generation |
| `start_update_profile` | `/update_profile` | Re-enter intake in update mode |
| `cancel` | `/cancel` | End any conversation |

### Check-in Flow

| Function | State | Purpose |
|---|---|---|
| `start_checkin` | `/checkin` | Check for resumable session; load plan; branch to structured or free-text |
| `handle_checkin_resume` | `CHECKIN_RESUME` | Resume from `CheckIn.structured_progress` or restart |
| `_persist_checkin_progress` | — (helper) | Upsert CheckIn row with current structured state |
| `handle_checkin_collecting` | `CHECKIN_COLLECTING` | Accumulate free-text messages |
| `handle_checkin_done` | `/done` command | Trigger processing |
| `handle_checkin_timeout` | `TIMEOUT` | Process after 90s inactivity |
| `handle_checkin_clarifying` | `CHECKIN_CLARIFYING` | Handle LLM clarifying question answer |
| `_structured_advance` | — (helper) | Move to next structured slot; returns None when done |
| `handle_structured_weight` | `CHECKIN_EX_WEIGHT` | Accept top-set weight |
| `handle_structured_rpe` | `CHECKIN_EX_RPE` | Accept top-set RPE; persist progress checkpoint |
| `handle_structured_pain` | `CHECKIN_EX_PAIN` | Accept pain flag; show adherence keyboard |
| `handle_structured_sets` | `CHECKIN_EX_SETS` | Accept set adherence; advance or go to general |
| `handle_structured_general` | `CHECKIN_GENERAL` | Accept general notes; finalize |
| `_process_checkin` | — (shared) | Extract, write telemetry, generate next plan, notify admin |

### Log Flow

| Function | State | Purpose |
|---|---|---|
| `start_log` | `/log` | Load active plan; show day picker |
| `handle_log_select_day` | `LOG_SELECT_DAY` | Store day; show exercise picker |
| `handle_log_select_exercise` | `LOG_SELECT_EXERCISE` | Store exercise; ask weight |
| `handle_log_weight` | `LOG_WEIGHT` | Store weight; ask RPE |
| `handle_log_rpe` | `LOG_RPE` | Store RPE; write back to WorkoutHistory |

### Plan View

| Function | Trigger | Purpose |
|---|---|---|
| `client_plan` | `/plan` | Show today's session using plan_started_at offset |
| `handle_plan_full_week` | callback `plan_full_week` | Show all days |

### Admin Approval Flow

| Function | Trigger | Purpose |
|---|---|---|
| `handle_admin_approve` | callback `^approve:` | Smart confirmation (bypass if safe) or confirmation step |
| `_do_approve_confirmed` | — (shared helper) | PDF render → Telegram → email → atomic DB write |
| `handle_admin_approve_confirmed` | callback `^approve_confirmed:` | Calls `_do_approve_confirmed` |
| `handle_admin_reject` | callback `^reject:` | Enter ADMIN_FEEDBACK state |
| `handle_admin_feedback` | `ADMIN_FEEDBACK` | Apply LLM edits; append edit_log; re-present |
| `cancel_admin` | `/cancel` (admin) | End admin feedback state |

### Review Flow

| Function | Trigger | Purpose |
|---|---|---|
| `admin_review` | `/review` | Index card + silent clients + Group-by toggle |
| `handle_open_pending_item` | callback `^open_pending:` | Full plan card for one item |
| `admin_review_batch` | `/review_batch` | Plans grouped by (avatar, days) |
| `handle_review_toggle` | callback `review_toggle_batch` | Calls admin_review_batch |

### Override Flow

| Function | Trigger | Purpose |
|---|---|---|
| `handle_override` | `/override` | Set (3 args) or list (1 arg) coach overrides |
| `handle_override_remove` | callback `^override_remove:` | Remove a single override |

### Safety / Acknowledgment

| Function | Trigger | Purpose |
|---|---|---|
| `handle_safety_clear` | callback `^safety_clear:` | Set safety_override_note on profile |
| `check_plan_acknowledgment` | universal MessageHandler (group=-1) | 24h nudge if plan not acknowledged |
| `handle_plan_ack` | callback `^ack_` | Acknowledge plan; dismiss nudge |

### Utility

| Function | Trigger | Purpose |
|---|---|---|
| `_build_client_summary` | — | One-card status for admin messages |
| `_format_past_week` | — | Compact results summary |
| `run_generation_and_dispatch` | — | Idempotency + rate limit + generate + notify admin |
| `_check_rate_limit` | — | 60s per-client cooldown |
| `handle_error` | PTB error handler | Log + deduplicated admin notification with count editing |
| `handle_help` | `/help` | Static command list |
| `safe_send_markdown` | — | Try Markdown; fall back to plain text |

---

## 19. Pending Roadmap Items

| Priority | Item | Notes |
|---|---|---|
| P0 | `alembic upgrade head` on live DB | Applies migrations 0001–0009 |
| P0 | Live end-to-end Telegram test | Manual: `/start` → approve → `/checkin` → week 2 |
| P2 | MRV hard-block | `_validate_volume()` only logs; should cap sets at MRV ceiling |
| P3 | Food database expansion | 68 → 150+ foods for meal variety |
| P3 | PDF design polish | Typography refinements, chart improvements |
| P4 | Scheduling & reminders | Cron-style check-in reminders on training days |
| P4 | Analytics dashboard | Admin view: load trends, adherence heatmap |
