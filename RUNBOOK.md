# Beyond Fit — Runbook

Operational guide for setting up, running, and operating the Beyond Fit coaching bot.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Local Development Setup](#2-local-development-setup)
3. [Docker Deployment](#3-docker-deployment)
4. [First-Time Setup (New Server)](#4-first-time-setup-new-server)
5. [Running Migrations](#5-running-migrations)
6. [Admin Telegram Workflow](#6-admin-telegram-workflow)
7. [Client Telegram Workflow](#7-client-telegram-workflow)
8. [Database Inspection](#8-database-inspection)
9. [Monitoring & Health Checks](#9-monitoring--health-checks)
10. [Troubleshooting](#10-troubleshooting)
11. [Key File Locations](#11-key-file-locations)
12. [Backup & Recovery](#12-backup--recovery)
13. [Environment Variables](#13-environment-variables)

---

## 1. Prerequisites

### Software
- Python 3.11+
- Docker + docker-compose (for production deployment)
- `pip` or `uv` for dependency management

### If running without Docker (bare metal / dev)
WeasyPrint requires system libraries for PDF rendering:
```bash
# Ubuntu/Debian
sudo apt-get install -y \
  libcairo2 libpango-1.0-0 libpangocairo-1.0-0 \
  libgdk-pixbuf2.0-0 libffi-dev libxml2 libxslt1.1 \
  python3-cffi

# macOS
brew install cairo pango gdk-pixbuf libffi
```

### Required credentials
| Credential | Where to get it |
|---|---|
| `TELEGRAM_BOT_TOKEN` | BotFather on Telegram (`/newbot`) |
| `ADMIN_TELEGRAM_ID` | Your own Telegram chat ID (message @userinfobot) |
| `OPENROUTER_API_KEY` | openrouter.ai → Keys |
| SMTP credentials | Your email provider (Gmail, SendGrid, etc.) |

---

## 2. Local Development Setup

```bash
# 1. Clone and install
git clone <repo>
cd beyond_fit_app
pip install -e ".[dev]"

# 2. Create .env from template
cp .env.example .env
# Edit .env with your credentials

# 3. Apply all database migrations
alembic upgrade head

# 4. Start the Telegram bot
python -m app.bot

# 5. (Optional) Start the FastAPI server in another terminal
uvicorn app.main:app --reload

# 6. Run tests
pytest
pytest -q --tb=short          # quiet mode
pytest tests/test_bot_flow.py -v   # bot integration tests only
```

The bot starts polling immediately. Send `/start` to your bot on Telegram to verify.

---

## 3. Docker Deployment

```bash
# Build and start all services
docker compose up --build

# Run in background
docker compose up -d --build

# View bot logs
docker compose logs -f bot

# Restart bot only
docker compose restart bot

# Stop everything
docker compose down
```

**Services started by docker-compose:**
- `db` — PostgreSQL 16 with health check (bot waits until DB is ready)
- `bot` — Python bot process (`python -m app.bot`)

**Environment variables** go in a `.env` file at the project root (docker-compose reads it automatically) or in the `environment:` block in `docker-compose.yml`.

---

## 4. First-Time Setup (New Server)

```bash
# 1. Copy environment file
cp .env.example .env
nano .env   # fill in all required values

# 2. Start just the database first
docker compose up -d db

# 3. Wait for Postgres to be ready (check with)
docker compose logs db | grep "ready to accept connections"

# 4. Run all migrations
docker compose run --rm bot alembic upgrade head

# 5. Start the bot
docker compose up -d bot

# 6. Verify
docker compose logs -f bot   # should show "Application started" or polling message
```

Then send `/start` to your bot from Telegram. You should receive the avatar selection keyboard.

---

## 5. Running Migrations

```bash
# Check which revision is currently applied
alembic current

# Apply all pending migrations
alembic upgrade head

# Apply exactly one migration forward
alembic upgrade +1

# Roll back one migration
alembic downgrade -1

# Roll back to a specific revision
alembic downgrade 0007

# Show full migration history
alembic history --verbose

# Show pending (not-yet-applied) migrations
alembic history -r current:head
```

**Current migrations** (all additive, all nullable):

| ID | Description |
|---|---|
| 0001 | Initial schema (ClientProfile, WorkoutHistory, NutritionProfile, NutritionPlan) |
| 0002 | ProfileSnapshot table; status/block_number/version on WorkoutHistory |
| 0003 | Safety screening fields on ClientProfile |
| 0004 | CheckIn table |
| 0005 | Expanded nutrition fields (JSON arrays for allergies, dislikes, etc.) |
| 0006 | email on ClientProfile |
| 0007 | name on ClientProfile; created_at on PendingApproval |
| 0008 | coach_overrides (ClientProfile); edit_log, cancelled_at (PendingApproval); acknowledged_at (WorkoutHistory) |
| 0009 | limitations_notes, safety_override_note (ClientProfile); plan_started_at, generation_notes (WorkoutHistory); structured_progress (CheckIn) |

---

## 6. Admin Telegram Workflow

### Reviewing pending workout plans

1. Send `/review` to the bot
2. You receive an index card listing all pending plans with client name, avatar, days, and week number
3. Tap **[Open #N]** to expand that client's plan (full exercise breakdown + client summary card)
4. Tap **[✅ Approve]** or **[❌ Reject]**

**Smart confirmation**: if you've already rejected the plan 2+ times, or the client already has a very recent active plan (<3 days old), a confirmation step appears. Otherwise, approval is immediate.

### Rejecting with coach edits

1. Tap **[❌ Reject]** on any plan
2. Type your requested changes in plain text — e.g. "Swap RDLs for leg curls, client has hamstring strain"
3. The LLM mutates the plan JSON and regenerates the coaching message
4. The revised plan is re-presented with the last 2 edit history entries shown
5. Tap **[✅ Approve]** when satisfied, or **[❌ Reject again]** to iterate

### Switching to batch/grouped view

From the `/review` index card, tap **[🗂 Group by type]** at the bottom. Plans are grouped by (avatar, training_days) bucket — useful for reviewing similar clients together.

### Setting an exercise override

Permanently substitute an exercise for a specific client across all future plan generations:

```
/override <client_id> <from_exercise_id> <to_exercise_id>
```

Example:
```
/override 123456789 bb_back_squat_highbar goblet_squat_db
```

The substitution takes effect on the next plan generation. Exercise IDs are visible in the plan JSON or by inspecting the exercise database (`app/exercise_db.py`).

### Listing and removing overrides

```
/override 123456789
```

Returns a list of current overrides for that client with **[Remove]** buttons next to each one. Tap to remove.

Overrides are also shown in the client summary card sent with every plan notification.

### Clearing a safety gate

When a client's health screening triggers a hard-refuse (e.g. recent cardiac event), you receive:

```
⚠️ Safety gate triggered for [Name] (12345)
Condition: recent_cardiac_event
Reason: Cardiac event < 24 weeks ago — exercise is contraindicated
[✅ Mark cleared by physician]
```

Tap **[✅ Mark cleared by physician]** after verifying the client has medical clearance. This sets a note on their profile and future plan generations will bypass the safety gate.

### Error notifications

Bot errors are forwarded to you automatically. If the same error fires multiple times within 5 minutes, the message is edited to show a count (e.g. "⚠️ Bot error (×4):") rather than flooding your chat.

### Checking for inactive clients

The bottom of every `/review` response includes a **"🔇 Silent (no check-in >10d)"** section listing clients who haven't checked in recently. Use this to follow up.

---

## 7. Client Telegram Workflow

### New client onboarding

```
1. Send /start
2. Choose your training style: powerlifter / powerbuilder / gen_pop
3. Choose training days per week: 3 / 4 / 5 / 6
4. Choose experience level: beginner / intermediate / advanced
5. Select any limitations (multi-select keyboard):
   - lower_back_pain, knee_pain, shoulder_impingement,
     wrist_pain, hip_flexor_tightness, none, 📝 Other (describe)
   Tap [✅ Done] when finished
6. Enter your email address
```

Your first workout plan is generated immediately and sent to your coach for approval. You'll receive a Telegram notification + PDF once it's approved.

### Weekly check-in

```
1. Send /checkin
2. For each main lift in your plan:
   a. Enter your top-set weight (kg)
   b. Enter your top-set RPE (1–10)
   c. Tap a pain flag: ✅ No pain / ⚠️ Some discomfort / 🚨 Sharp pain
   d. Tap set adherence: ✅ All sets / ⚠️ Missed 1-2 / ❌ Cut short
3. Enter any general notes (sleep, energy, life stress) or type /skip
```

If you start a check-in but don't finish it, you can resume within 2 hours by running `/checkin` again and tapping **[▶️ Resume]**.

### Manual set logging

If you forgot to log a lift during check-in, or want to update a specific entry:

```
1. Send /log
2. Tap the training day
3. Tap the exercise
4. Enter the weight (or /skip)
5. Enter your RPE (or /skip)
```

### Viewing your current plan

```
/plan           → shows today's training session
/plan week      → shows the full week
```

On rest days you'll see "🛌 Today is a rest day." Tap **[📅 Full Week]** from today's view to see all training days.

### Nutrition intake

```
/diet           → full 18-question intake (takes ~3 minutes)
/diet quick     → skip biometric questions, use safe defaults
```

Your nutrition plan goes to your coach for approval before you receive it.

### Getting help

```
/help           → lists all available commands
/cancel         → cancel whatever you're currently doing
```

---

## 8. Database Inspection

### SQLite (development)

```bash
sqlite3 coaching_engine.db

.tables
# → checkin  clientprofile  nutritionplan  nutritionprofile  ...

# Active plans per client
SELECT c.name, w.week_number, w.status, w.plan_started_at
FROM workouthistory w JOIN clientprofile c ON w.client_id = c.client_id
WHERE w.status = 'active'
ORDER BY w.history_id DESC;

# Pending approvals
SELECT approval_uuid, client_id, client_name, created_at FROM pendingapproval;

# Recent check-ins
SELECT client_id, created_at, extraction_json IS NOT NULL as completed
FROM checkin ORDER BY created_at DESC LIMIT 20;

# Coach overrides
SELECT client_id, name, coach_overrides FROM clientprofile
WHERE coach_overrides IS NOT NULL;
```

### PostgreSQL (production)

```bash
psql $DATABASE_URL

\dt                          -- list tables
\d clientprofile             -- describe table

-- Same queries work; postgres-specific:
SELECT pg_database_size(current_database());   -- DB size
SELECT count(*) FROM pendingapproval;          -- pending queue depth
```

---

## 9. Monitoring & Health Checks

### Is the bot alive?

Send any message to the bot. If no response within 30 seconds:
```bash
docker compose logs bot | tail -50    # check for crash
docker compose restart bot            # restart
```

### Pending plan queue

Send `/review` as admin. The count is shown in the heading: `📋 Pending Plans (N)`. If N is growing, check if the bot process is running and can reach Telegram's API.

### Silent clients

Every `/review` shows clients who haven't checked in for >10 days at the bottom. Follow up manually or set up a reminder.

### Error log

Errors auto-forwarded to your Telegram. Also check:
```bash
docker compose logs bot | grep ERROR
docker compose logs bot | grep "Unhandled exception"
```

### Database disk usage

```bash
# SQLite
ls -lh coaching_engine.db

# Postgres
docker compose exec db psql -U $POSTGRES_USER -c "SELECT pg_size_pretty(pg_database_size('$POSTGRES_DB'));"
```

---

## 10. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Bot not responding to any message | Process crashed or token invalid | `docker compose logs bot`; check `TELEGRAM_BOT_TOKEN` |
| "No active plan found" on `/checkin` | Client's WorkoutHistory has no `status=active` row | Admin needs to approve their pending plan |
| "A plan is already waiting" on `/start` | PendingApproval exists for client | Admin approves or rejects via `/review` |
| Safety gate blocks plan generation | Health screening fields trigger hard-refuse | Admin taps [✅ Mark cleared by physician] on gate notification |
| PDF sent as fallback (plain markdown) | WeasyPrint render error | Check WeasyPrint system deps; `docker compose logs bot` for render error details |
| Email not delivered | SMTP vars missing or wrong | Check `.env` for `SMTP_HOST/PORT/USER/PASS/FROM`; email failure is non-fatal (plan is still sent via Telegram) |
| Duplicate error messages in admin chat | Same error firing repeatedly | Normal — message is edited to show count (×N); resolve the underlying error |
| `/checkin` doesn't detect structured mode | Plan has no `main_compound` slots | Check `workout_constants.toml` slot templates have `type = "main_compound"` |
| `/plan` shows wrong day | `plan_started_at` not set on old plans | Falls back to weekday heuristic; only plans approved after round-2 deploy have `plan_started_at` |
| `alembic upgrade head` fails | DB out of sync or conflicting revision | Run `alembic current` to see state; may need `alembic stamp head` to manually mark current |
| Check-in resume offer not showing | In-progress CheckIn row >2h old or already extracted | Expired; run `/checkin` for a fresh start |
| Override not applying | Replacement exercise_id not in exercise DB | Verify ID exists in `app/exercise_db.py`; override silently falls back to original if not found |
| 24h acknowledgment nudge fires mid-check-in | Conversation guard keys missing | Ensure `checkin_history_id` key is set in `user_data` at start of check-in |

---

## 11. Key File Locations

| File | Purpose |
|---|---|
| `app/bot.py` | All Telegram handlers (~3,000 lines) |
| `app/generator.py` | Workout generation engine |
| `app/models.py` | All DB table definitions (SQLModel) |
| `app/database.py` | Engine setup; switches SQLite ↔ Postgres on `DATABASE_URL` |
| `app/settings.py` | Pydantic-settings config loader |
| `app/config/workout_constants.toml` | Day templates, sets/reps, periodization constants |
| `app/domain/workout/constants.py` | MEV/MRV/MAV per muscle, safety gate conditions, rest/tempo/cues |
| `app/domain/workout/autoregulation.py` | PlanDelta derivation rules |
| `app/domain/nutrition/energy.py` | BMR, TDEE, calorie floor formulas |
| `app/domain/nutrition/meal_builder.py` | PuLP LP meal optimizer |
| `app/services/llm_service.py` | LLM calls (coaching message, edits, tips) |
| `app/adapters/llm/extractors.py` | `extract_checkin()`, `render_digest()` |
| `app/adapters/pdf/renderer.py` | `render_plan_pdf()` |
| `alembic/versions/` | All 9 migrations (0001–0009) |
| `prompts/checkin_extract.j2` | Jinja2 system prompt for check-in extraction |
| `tests/conftest.py` | Shared test fixtures (mock bot, test DB, rate-limit reset) |
| `tests/test_bot_flow.py` | 6 bot integration tests |
| `docker-compose.yml` | Production service definitions |
| `Dockerfile` | Build instructions (WeasyPrint deps + Python) |

---

## 12. Backup & Recovery

### SQLite (development)

```bash
# Manual backup
cp coaching_engine.db coaching_engine.db.bak.$(date +%Y%m%d)

# Restore
cp coaching_engine.db.bak.20260424 coaching_engine.db
```

### PostgreSQL (production)

```bash
# Backup
pg_dump $DATABASE_URL > backup_$(date +%Y%m%d_%H%M).sql

# Restore (to a fresh DB)
createdb $NEW_DB_NAME
psql $NEW_DB_NAME < backup_20260424_1200.sql

# Or with docker:
docker compose exec db pg_dump -U $POSTGRES_USER $POSTGRES_DB > backup.sql
docker compose exec -T db psql -U $POSTGRES_USER $POSTGRES_DB < backup.sql
```

### What to back up

| Data | Location | Frequency |
|---|---|---|
| Database | `coaching_engine.db` or Postgres | Daily |
| `.env` file | Project root | On change |
| `workout_constants.toml` | `app/config/` | On change |

**Note**: WorkoutHistory rows store the full `WorkoutWeek` JSON including all telemetry. No external files need to be backed up for plan data — everything is in the database.

---

## 13. Environment Variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | — | PTB bot token from BotFather |
| `ADMIN_TELEGRAM_ID` | ✅ | — | Your Telegram chat ID — receives all admin notifications |
| `DATABASE_URL` | ❌ | SQLite (`coaching_engine.db`) | PostgreSQL DSN: `postgresql+psycopg2://user:pass@host/db` |
| `OPENROUTER_API_KEY` | ✅ | — | API key for LLM calls (coaching messages, check-in extraction) |
| `OPENROUTER_BASE_URL` | ❌ | https://openrouter.ai/api/v1 | Override for self-hosted or alternative LLM proxy |
| `LLM_MODEL_ID` | ❌ | google/gemini-2.5-flash | Model used for all LLM calls |
| `SMTP_HOST` | ❌ | — | SMTP server hostname. If not set, email delivery is skipped (plans still sent via Telegram) |
| `SMTP_PORT` | ❌ | 587 | SMTP port |
| `SMTP_USER` | ❌ | — | SMTP username / login |
| `SMTP_PASS` | ❌ | — | SMTP password |
| `SMTP_FROM` | ❌ | — | From address for plan delivery emails |

### Minimal `.env` for local development

```env
TELEGRAM_BOT_TOKEN=1234567890:ABCdef...
ADMIN_TELEGRAM_ID=987654321
OPENROUTER_API_KEY=sk-or-v1-...
```

### Full `.env` for production

```env
TELEGRAM_BOT_TOKEN=1234567890:ABCdef...
ADMIN_TELEGRAM_ID=987654321
DATABASE_URL=postgresql+psycopg2://beyond:secret@db/beyond_fit
OPENROUTER_API_KEY=sk-or-v1-...
LLM_MODEL_ID=google/gemini-2.5-flash
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=coaching@yourdomain.com
SMTP_PASS=app-specific-password
SMTP_FROM=Coach Shoaib <coaching@yourdomain.com>
```
