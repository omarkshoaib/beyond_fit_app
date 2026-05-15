# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Beyond Fit App** is a "Deterministic Coaching Engine" — a backend system that algorithmically generates personalized weekly workout plans and delivers them to clients via a Telegram bot with a human-in-the-loop (HITL) admin approval step before dispatch.

## Commands

### Install dependencies
```bash
pip install -e ".[dev]"
```

### Run the FastAPI server
```bash
uvicorn app.main:app --reload
```

### Run the Telegram bot
```bash
python -m app.bot
```

### Run all tests
```bash
pytest
```

### Run a single test
```bash
pytest tests/test_generator.py::test_generate_end_to_end
```

## Architecture

### Two entry points, one engine

The system has two separate entry points that share the core generation logic:

1. **FastAPI server** (`app/main.py` + `app/routes.py`) — REST API exposing `/generate` and `/generate_and_coach` endpoints. Used for testing/integration.
2. **Telegram bot** (`app/bot.py`) — The primary production interface. Runs as a standalone polling process (not mounted on FastAPI).

Both call `WorkoutGenerator` from `app/generator.py` directly.

### Core generation pipeline (`app/generator.py`)

`WorkoutGenerator.generate()` is the central engine. It is **entirely deterministic** (no randomness):

1. `_resolve_split()` — maps `(avatar, training_days)` to named day templates (e.g., `["Upper", "Lower", "Push", "Pull", "Legs"]`)
2. `_budget_volume()` — sets weekly set caps per muscle group based on `experience_level` (beginner/intermediate/advanced)
3. `_calculate_rpe()` — returns the target RPE for the week using a fixed 5-week block cycle (weeks 1–4 ascending, week 5 = deload at RPE 6)
4. `_fill_slots()` — builds each training day by filling 3 slots: main lift (highest fatigue, pattern-matched), primary accessory, isolation (with biomechanical synergy pairing). Respects a `MAX_FATIGUE = 12` per-day cap.
5. `AutoRegulator.calculate_next_load()` — when prior week telemetry exists (`actual_weight`, `actual_rpe`), computes the next week's `target_weight` using RPE error correction (4% per RPE point) + progressive overload increment.

Exercise selection uses `_filter_exercises()` which gates on: `avatar_tags`, `available_equipment`, `limitations` (currently only `lower_back_pain` is handled), and optional kwargs (`pattern`, `primary_muscle`, `muscle_group`, `bio_focus`, `fatigue_cost` range).

### Database (`app/database.py` + `app/models.py`)

Uses **SQLModel** (SQLAlchemy + Pydantic hybrid). Defaults to SQLite (`coaching_engine.db`) but switches to PostgreSQL if `DATABASE_URL` env var is set.

Persisted tables (post Phase A SaaS refactor):
- `ClientProfile` — one row per client. **Two parallel coach concepts coexist:**
  - **Bot:** `assigned_coach_id` (BigInteger) → `CoachProfile.telegram_user_id`. Drives plan-DM routing, /review scope, /override scope. Set when a paid client picks a coach.
  - **Web (FastAPI):** legacy `coach_id` (str) + `is_coach`/`is_admin` flags. Used by `app/api/*`. The bot does **not** consult these. Kept in parallel to preserve the FastAPI surface.
- `CoachProfile` — bot-side coach record (CV upload, status workflow, telegram_user_id PK).
- `Subscription` / `Payment` / `AccessCode` / `ChatBinding` / `ReminderLog` — paid-SaaS plumbing.
- `WorkoutHistory` — one row per completed week; `workout_json` stores the full `WorkoutWeek` as a JSON string (including `actual_weight`/`actual_rpe` filled in during check-in).
- `PendingApproval` — staging table for plans awaiting coach/admin review; deleted after approve/reject.

**`client_id`** is now an opaque `cl_<token>` string generated at pay_verify time — **not** a stringified Telegram user id. Chat → client resolution goes through `ChatBinding(chat_id BigInteger PK → client_id)`. See `auth_roles.get_authenticated_client(chat_id)`.

`WorkoutSlot`, `WorkoutDay`, `WorkoutWeek` are **not** database tables — they exist only as nested JSON inside `WorkoutHistory.workout_json`.

### Telegram bot flow (`app/bot.py`)

Three `ConversationHandler` state machines:

1. **Client intake** (`/start`): collects avatar → days → experience → limitations → email, creates `ClientProfile`, calls `run_generation_and_dispatch()`
2. **Check-in** (`/checkin`): iterates over unlogged `main_lift` slots in the latest `WorkoutHistory`, collects `actual_weight` + `actual_rpe` per slot; when all slots filled, increments `week_number` and re-runs generation with prior week as input
3. **Admin flow**: triggered by approve/reject inline keyboard callbacks sent to `ADMIN_TELEGRAM_ID`. Approve → PDF generation → email dispatch → move to `WorkoutHistory`. Reject → admin types free-text feedback → `FlashCommunicationService.apply_coach_edits()` mutates the JSON via LLM → re-presents for approval.

### Services (`app/services/`)

- **`llm_service.py`** — `FlashCommunicationService` wraps OpenRouter (via `openai` SDK with custom `base_url`). Uses `google/gemini-3.1-flash-lite-preview`. Two methods: `generate_coaching_message()` (formats workout as client email) and `apply_coach_edits()` (mutates workout JSON per admin feedback, must return raw JSON only).
- **`pdf_service.py`** — converts Markdown coaching message to PDF bytes via `markdown2` + `weasyprint`.
- **`email_service.py`** — SMTP dispatch of the PDF to the client's email.

### Exercise database (`app/exercise_db.py`)

A single large in-memory list of exercise dicts (`EXPANDED_EXERCISES_DATA`). Each entry has: `exercise_id`, `name`, `movement_pattern`, `primary_muscle`, `secondary_muscles`, `fatigue_cost` (1–5), `equipment_required`, `avatar_tags` (`powerlifter`/`powerbuilder`/`gen_pop`), `biomechanical_focus` (`lengthened_position`/`shortened_position`/`mid_range`).

## Key design constraints

- The workout plan is **always generated deterministically first** — the LLM only formats it into a readable email and optionally mutates it on admin rejection. The LLM never selects exercises.
- `slot_type = "main_lift"` is referenced in the check-in flow but is **not currently set** by `_fill_slots()` — this is a known gap.
- The `CoachedWorkoutResponse` model has a field `workout_data` but the route returns `workout=` — there is a field name mismatch between the Pydantic model and the route response.
- `WorkoutWeek` does not have a `client_id` field, but `test_api.py` asserts `data["workout"]["client_id"] == "999"` — this test will fail against the current model.

## Environment variables

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string (falls back to SQLite) |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token |
| `ADMIN_TELEGRAM_ID` | Telegram chat ID to receive plan approval requests |
| `OPENROUTER_API_KEY` | OpenRouter API key for LLM calls |
| SMTP vars | Used by `email_service.py` for plan dispatch |
