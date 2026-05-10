# Bot-Only Runbook — 95.111.247.88

Single-host, bot-only deployment. Use this for the test server. When you're ready to add the mobile/REST surface, switch to `RUNBOOK.md`.

## 0. SECURITY NOTE — DO THIS FIRST

The deploy private key was previously leaked in a chat transcript. As soon as practical:

```bash
# from your laptop, while the old key still works:
ssh ubuntu@95.111.247.88
ssh-keygen -t ed25519 -f ~/.ssh/beyond_fit_deploy -C "beyond-fit-deploy"
cat ~/.ssh/beyond_fit_deploy.pub  # paste this on the server
echo "<new pubkey>" >> ~/.ssh/authorized_keys
# then on the server, remove the old leaked pubkey from authorized_keys
# then test the new key works in a SECOND terminal before logging out
```

## 1. First-time host bootstrap

```bash
ssh ubuntu@95.111.247.88

# install minimal tools
sudo apt-get update
sudo apt-get install -y git curl

# clone
git clone <your-repo-url> beyond_fit_app
cd beyond_fit_app
git checkout bot-only-deploy   # or main once merged

# secrets
cp .env.example .env
nano .env   # fill in: POSTGRES_PASSWORD, TELEGRAM_BOT_TOKEN, ADMIN_CHAT_ID, OPENROUTER_API_KEY
chmod 600 .env

# bootstrap (installs docker if missing, builds, starts, runs migrations)
./scripts/deploy.sh
# if docker was just installed: log out, log back in, re-run.

# verify
./scripts/health_check.sh
docker compose logs -f bot
```

## 2. Required env vars

| Var | Required? | What it does |
|---|---|---|
| `POSTGRES_PASSWORD` | yes | Postgres password. **Use only `[A-Za-z0-9_-]`, 32+ chars.** It's interpolated raw into `DATABASE_URL=postgresql://coaching:<pwd>@db:5432/coaching`; `@`, `:`, `/`, `#`, `?`, `%` will break the URL. |
| `TELEGRAM_BOT_TOKEN` | yes | from BotFather |
| `SUPER_ADMIN_TELEGRAM_USER_ID` | yes | Numeric Telegram user id of the owner/super-admin. Receives payment-screenshot DMs, coach-application DMs, "needs assignment" DMs. Legacy `ADMIN_CHAT_ID` is still honoured as a fallback. |
| `OPENROUTER_API_KEY` | yes | openrouter.ai → Keys. Also powers the FAQ Q&A loop. |
| `INSTAPAY_PAYEE_HANDLE` | yes (paid flow) | Instapay handle shown during Subscribe (e.g. `@beyond.fit`). Empty → bot prints `(handle not configured)`. Set before going live. |
| `INSTAPAY_DISPLAY_NAME` | yes (paid flow) | Display name shown alongside the handle (e.g. `Beyond Fit`). |
| `SUBSCRIPTION_PRICE_1M_EGP` | no | 1-month tier price in EGP. Default `1500`. |
| `SUBSCRIPTION_PRICE_3M_EGP` | no | 3-month tier price in EGP. Default `3500`. |
| `FAQ_RATE_LIMIT_PER_HOUR` | no | LLM Q&A calls per chat per hour. Default `5`. |
| `OPENROUTER_BASE_URL` | no | default fine |
| `LLM_MODEL_ID` | no | default `google/gemini-3.1-flash-lite-preview` |
| `ADMIN_CHAT_ID` | legacy | Pre-Phase-A name for super-admin. Still works as a fallback. |
| SMTP* | no | unused in bot-only mode |
| `AUTH_SECRET_KEY` | no | unused in bot-only mode |

### Daily jobs (Phase F)

The bot's `JobQueue` runs two daily jobs at startup:
- **09:00 UTC** — `send_renewal_reminders`: DMs clients whose subscription ends in 7 / 3 / 1 days. Idempotent via `reminderlog(subscription_id, kind)`.
- **00:05 UTC** — `expire_subscriptions`: flips `subscription.status` from `active` → `expired` for any sub past `ends_at` and DMs the client.

Requires the `[job-queue]` extra of `python-telegram-bot` (already pinned in `pyproject.toml:20`). If the extra is missing the bot logs a warning and skips scheduling; everything else still works.

## 3. Day-to-day operations

```bash
# tail bot logs
docker compose logs -f bot

# tail db logs
docker compose logs -f db

# restart bot only (most common)
docker compose restart bot

# rebuild after code change
git pull
docker compose build bot
docker compose up -d bot

# stop everything (preserves data)
docker compose down

# nuke everything (DELETES DATA — only for clean reinstall)
docker compose down -v
```

## 4. Smoke test — full end-to-end on a fresh install

In Telegram, talk to your bot. Verify each step succeeds.

1. `/start` → answer avatar / days / experience / limitations / email
2. The admin chat (you) gets an "Approve / Reject" message
3. Hit ✅ Approve
4. The client chat receives a PDF + an inline summary message (📋 Week N — N day(s), per-day exercise lines)
5. Wait, then `/checkin` → log weights + RPEs for each main compound
6. Bot acknowledges, generates next week, returns to admin for approval
7. Repeat 3–4 for week 2

If anything sticks: `docker compose logs -f bot` while you re-trigger.

## 5. Backups

```bash
# one-time setup of the backup directory (host-side)
sudo mkdir -p /var/backups/beyond_fit
sudo chown ubuntu:ubuntu /var/backups/beyond_fit

# manual one-off
docker compose exec -T db pg_dump -U coaching coaching | gzip > /var/backups/beyond_fit/$(date -u +%Y%m%dT%H%M%SZ).sql.gz

# automate via cron (run on host, not inside container)
crontab -e
# add (runs daily at 03:00 UTC):
0 3 * * * cd /home/ubuntu/beyond_fit_app && docker compose exec -T db pg_dump -U coaching coaching | gzip > /var/backups/beyond_fit/$(date -u +\%Y\%m\%dT\%H\%M\%SZ).sql.gz
```

Restore:

```bash
gunzip -c /var/backups/beyond_fit/<file>.sql.gz | docker compose exec -T db psql -U coaching -d coaching
```

## 6. Common failures

| Symptom | First place to look |
|---|---|
| `docker compose up` errors `POSTGRES_PASSWORD must be set in .env` | env var missing or .env not in repo root |
| Bot doesn't reply to /start | `docker compose logs bot` — was the token rejected? |
| Admin doesn't get approval message | `ADMIN_CHAT_ID` correct? Right numeric id, not username? |
| PDF send fails | `docker compose logs bot` — WeasyPrint render errors usually mean missing system libs (already in Dockerfile, so impossible inside the container) |
| LLM call times out | OpenRouter rate-limited or wrong key — check the openrouter.ai dashboard |
| Postgres healthcheck flaps | Disk full? `df -h`. |

## 7. Updating the bot

```bash
cd beyond_fit_app
git pull
docker compose build bot
docker compose up -d bot
docker compose exec -T bot alembic upgrade head
./scripts/health_check.sh
```

## 8. Logs retention

`docker-compose.yml` sets each container to 10MB × 5 files = 50MB max. If you want long-term retention, ship to a remote sink (e.g. journald via `--log-driver=journald`).

## 9. Uptime check (optional)

```bash
crontab -e
# add: every 5 min, log unhealthy events to journalctl
*/5 * * * * /home/ubuntu/beyond_fit_app/scripts/health_check.sh >/dev/null || logger -t beyond_fit "bot stack unhealthy"
```

Inspect later with `journalctl -t beyond_fit --since "1 hour ago"`.
