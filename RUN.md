# How to Run Beyond Fit (Mobile + Backend)

## TL;DR

You need **two terminals** open at once:

- **Terminal 1** runs the FastAPI backend on `localhost:8000`
- **Terminal 2** runs the Flutter mobile app in Chrome

---

## Terminal 1 — Backend

```bash
cd /media/shoaib/NewVolume/beyond_fit_app

# Optional: start with a fresh database (for testing the full flow)
rm -f beyond_fit.db

# Start the API
DATABASE_URL=sqlite:///./beyond_fit.db uvicorn app.main:app --reload
```

You should see:
```
INFO: Uvicorn running on http://127.0.0.1:8000
INFO: Application startup complete.
```

Leave this running.

---

## Terminal 2 — Mobile App (Flutter on Chrome)

```bash
# One-time: add Flutter to your PATH (also add this line to ~/.bashrc to persist)
export PATH="$PATH:/media/shoaib/NewVolume/flutter/bin"

cd /media/shoaib/NewVolume/beyond_fit_app/mobile

# Run the app pointing at the local backend
flutter run -d chrome --dart-define=API_BASE_URL=http://localhost:8000/api/v1
```

Wait ~30 seconds for the first build. Chrome will open with the app.

---

## How to use the app (first time)

1. **Sign up** — click "Don't have an account? Sign up" on the login screen.
   Enter name, email, password (min 8 chars). Click **Create Account**.

2. **Onboarding** (4 quick steps — built specifically so you don't have to type anything):
   - **Goal**: tap Powerlifter / **Powerbuilder** / General Fitness. → Continue
   - **Frequency**: tap a number 3–6. → Continue
   - **Experience**: Beginner / Intermediate / Advanced. → Continue
   - **Injuries**: tap any that apply, or none. → **Generate My Plan**

3. **Home screen** — you now see Today's Session card with the day name and "Start Workout" button. Quick-action cards at the bottom: Progress, Check-in, Full Plan, Nutrition.

4. **Start Workout** — see your sets, reps, target weight, RPE, slot type (Main / Secondary / Isolation) for every exercise.

5. **Profile menu** (avatar in top-right) — Edit Profile, Plan History, Generate New Plan, Sign out.

---

## Roles, super-admin, invite-only coaches

Three roles with strict invariants:

- **Super-admin** — hardcoded as `omarkshoaib@outlook.com` in `app/settings.py`. Cannot be demoted. Only role that can promote other admins. Auto-healed on every server boot (if the row exists, `is_admin` and `is_coach` are forced to True).
- **Admin** — appointed by the super-admin. Can invite coaches, withdraw invites, assign clients to coaches.
- **Coach** — cannot self-register. An admin must `Invite coach` with their email *first*; when that email registers via the regular `/register` flow, they're flagged `is_coach=True` automatically.
- **Client** — public self-registration. No admin involvement.

### Bootstrap (first time)

1. Register `omarkshoaib@outlook.com` in the app (Sign up).
2. Restart the backend — lifespan auto-promotes that row to `is_admin=True, is_coach=True`. (Or run `python scripts/promote_admin.py omarkshoaib@outlook.com` once.)
3. Sign in. App routes you to the Coach Dashboard.

### Super-admin → promote another admin

1. Profile → Admin Panel → **Admins** tab (only visible to super-admin).
2. Tap "Promote admin" → enter the email of an already-registered user.
3. They now see the Admins tab too on next sign-in. Demote with the red icon (super-admin row is protected).

### Admin → invite a coach

1. Profile → Admin Panel → **Coaches** tab → "Invite coach" → enter email.
2. The invitee receives an email (if SMTP is set up) and registers normally.
3. On registration, their account is flagged `is_coach=True` automatically and the invite is marked accepted.

### Admin → assign a client to a coach

Profile → Admin Panel → **Clients** tab → "Assign client" → client email + coach email.

### Client (with an assigned coach)

Generates a plan → home shows **"Plan under review"**. Coach approves → home flips to today's session card. Coach rejects → home shows the feedback as an amber card with "Generate New Plan" CTA.

### Coach edit-via-LLM (new)

In the coach review screen, tap **"Edit plan via LLM before approving"** → bottom sheet → describe the change → backend calls `FlashCommunicationService.apply_coach_edits()` (same path Telegram uses) → re-loads the mutated plan for re-review.

---

## Workout flow with set logger

Today's session card → tap each exercise → "Set 1 / Set 2 / Set 3" chips along the bottom of each slot card.

Tap a chip → bottom sheet → enter actual reps + weight (in your unit, kg or lb — switch in Profile) + optional RPE → Save. Chip flips to a green check.

The autoregulator reads these `SetLog` rows on the next check-in to adjust loads.

---

## Privacy: export + delete

- **Export** — `GET /api/v1/profile/export` (Bearer auth) returns a JSON dump of every row associated with you. Wire to a "Download my data" button later, or `curl` it directly.
- **Delete** — `DELETE /api/v1/profile` anonymises your row (clears email, name, password hash, role flags). Workout history rows stay for aggregate analytics. Super-admin can't delete themselves.

---

## Operations

- **Health check**: `GET /healthz` → `{status, db, smtp, llm, telegram_bot, sentry, version}`.
- **Rate limiting**: 10 requests / minute / IP on `/auth/login|register|forgot|reset`. Disable in tests / dev with `DISABLE_RATELIMIT=true`.
- **Sentry**: set `SENTRY_DSN` to enable error reporting (server-side). No-op when unset.
- **Structured logging**: `STRUCTLOG_JSON=true` switches to JSON output for log aggregators.
- **Audit log**: every admin action (promote, demote, invite coach) writes an `AuditEvent` row. Inspect with `sqlite3 beyond_fit.db "SELECT * FROM auditevent ORDER BY id DESC LIMIT 20"`.
- **Backups**: `./scripts/backup_db.sh ./backups` snapshots SQLite or runs `pg_dump` based on `DATABASE_URL`.
- **Diagnostic auth**: `GET /api/v1/auth/whoami` returns roles + which auth source (Bearer vs cookie) the server saw. Use this when a 403 is mysterious.

---

## Testing the next-week flow

After completing your week:

1. From Home → **Check-in** card → fill in actual weight + RPE for each main lift → **Submit Check-in**.
2. Or use **Profile → Generate New Plan** to instantly regenerate.

The autoregulator adjusts next week's loads based on RPE error (overshot → drop ~4% per RPE point; undershot → bump up).

---

## Resetting

To wipe everything and start fresh:

```bash
# Stop the backend (Ctrl-C in Terminal 1)
rm /media/shoaib/NewVolume/beyond_fit_app/beyond_fit.db
# Restart the backend
```

In Chrome, open DevTools → Application → Local Storage → clear `localhost:port`. Then refresh the page.

---

## Common issues

| Symptom | Fix |
|---|---|
| `Command 'flutter' not found` | `export PATH="$PATH:/media/shoaib/NewVolume/flutter/bin"` |
| `Connection refused localhost:5432` | The `.env` file has `DATABASE_URL` pointing at Postgres. Either start Postgres or change `.env` to `DATABASE_URL=sqlite:///./beyond_fit.db`. |
| `OPTIONS /api/v1/... 405` | Restart the backend — the CORS middleware was just added, the running server needs to reload. |
| Old DB has wrong schema | `rm beyond_fit.db` and restart backend. |
| Login page shows blank in Chrome | Hard refresh (Ctrl-Shift-R). The hot-restart caches old token state. |
| `No supported devices` | You're missing Android emulator / iPhone simulator. Use `-d chrome` to run on the web instead. |

---

## Mobile platforms (not just web)

The Flutter project supports Android + iOS too — when you have an emulator:

```bash
# Android emulator (uses 10.0.2.2 to reach host's localhost)
flutter run -d emulator-5554 --dart-define=API_BASE_URL=http://10.0.2.2:8000/api/v1

# iOS simulator (Mac only)
flutter run -d "iPhone 15" --dart-define=API_BASE_URL=http://localhost:8000/api/v1
```

For App Store / Play Store releases you'd build with a production API URL, e.g.:

```bash
flutter build apk --dart-define=API_BASE_URL=https://api.beyondfit.example.com/api/v1
flutter build ios --dart-define=API_BASE_URL=https://api.beyondfit.example.com/api/v1
```

---

## What's in the repo

- `app/` — FastAPI backend, deterministic workout engine, JWT auth, REST API at `/api/v1/*`.
- `mobile/` — Flutter mobile app (iOS + Android + Web).
- `tests/` — 109 backend tests. Run with `pytest -q`.
- `mobile/test/` — Flutter widget test (basic).
- `RUN.md` — this file.
- `README.md` — project overview.
- `CLAUDE.md` — architecture notes.
