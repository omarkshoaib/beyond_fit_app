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

## Coach + admin flow (full HITL approval)

The original Telegram-based admin flow is now fully on mobile too. Two new roles:

- **Coach** — reviews + approves clients' plans before they go active.
- **Admin** — promotes coaches and assigns clients to coaches.

### One-time setup: bootstrap your first admin

After you've registered an account in the app, promote it from the command line (admins can only be created by another admin, so the first one needs the bootstrap script):

```bash
cd /media/shoaib/NewVolume/beyond_fit_app
DATABASE_URL=sqlite:///./beyond_fit.db python scripts/promote_admin.py you@example.com
```

That account is now admin + coach. Sign out and sign in again — the app will route you to the Coach dashboard.

### Admin: promote coaches and assign clients

1. Profile → **Admin Panel** (purple icon, admins only).
2. Tap **Promote Coach** → enter their email → optionally tick "Also grant admin".
3. Tap **Assign Client** → enter client email + coach email.

You'll see all users with COACH / ADMIN / ASSIGNED pills.

### Coach: review + approve plans

1. Sign in as a coach → automatically routed to **Coach Dashboard**.
2. **Awaiting your review** section lists pending plans (with orange badge counts on client tiles).
3. Tap a pending card → see full week (every day, every exercise, sets × reps × weight × RPE).
4. **Approve** (green) → plan becomes the client's active plan.
5. **Reject** (red) → bottom sheet for feedback message → logged to the plan's edit history; client must regenerate.

### Client (with assigned coach)

When a client with a coach generates a plan, the home screen shows:

> **Plan under review** — Your coach is reviewing your plan. You will see it here as soon as it is approved.

Once approved, the home screen flips to the regular Today's Session card. No coach assigned? Plans go straight to active (no approval needed) — useful for solo users.

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
