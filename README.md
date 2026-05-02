# Beyond Fit

Deterministic coaching engine. Generates personalized weekly strength programs and delivers them via Telegram with human-in-the-loop admin approval.

## How it works

1. Client onboards via `/start` → workout plan generated deterministically
2. Admin reviews + approves in Telegram → PDF emailed to client
3. Client checks in weekly (`/checkin`) → telemetry auto-regulates next week's load
4. LLM only formats the plan into readable prose and applies admin edits — never selects exercises

## Quick start

```bash
pip install -e ".[dev]"
cp .env.example .env   # fill in required values
alembic upgrade head
python -m app.bot
```

## Run tests

```bash
pytest
```

## Docker

```bash
docker compose up --build
```

## Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Yes | — | Bot token from @BotFather |
| `ADMIN_CHAT_ID` | Yes | — | Telegram chat ID for admin approval |
| `OPENROUTER_API_KEY` | Yes | — | LLM for plan formatting + edits |
| `DATABASE_URL` | No | SQLite | Postgres connection string |
| `SMTP_HOST` | Yes | — | Email delivery host |
| `SMTP_PORT` | No | 587 | SMTP port |
| `SMTP_USER` | Yes | — | SMTP username |
| `SMTP_PASSWORD` | Yes | — | SMTP password |
| `FEATURE_NUTRITION_ENABLED` | No | false | Enable nutrition planning flow |

See `.env.example` for all variables including optional LLM overrides.

## Documentation

- [RUNBOOK.md](RUNBOOK.md) — how to run, operate, and debug
- [PIPELINE_REPORT.md](PIPELINE_REPORT.md) — full architecture, DB models, handler reference
