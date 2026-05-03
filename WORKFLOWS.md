# Beyond Fit — Workflows reference

Every user-facing flow in the app, what backend endpoints it hits, what tables it writes, and what to look at if it's broken.

Use this as a checklist when verifying functionality. If a flow misbehaves, the "Watch points" section under each one tells you where to look first.

---

## 0. Roles at a glance

| Role | Can register themselves? | Granted by | Can do |
|---|---|---|---|
| **Client** | yes (open signup) | — | training plans + check-ins for self |
| **Coach** | NO — must be invited | admin | review / approve / reject / edit plans for assigned clients |
| **Admin** | NO — promoted from a registered user | super-admin | invite coaches, assign clients to coaches, view all clients |
| **Super-admin** | hardcoded `omarkshoaib@outlook.com` | self-healing at startup | everything an admin can do + promote / demote other admins |

Lifespan invariant: every server boot looks for the super-admin row by email and forces `is_admin = is_coach = True`. Cannot be revoked from the API.

---

## 1. Client sign-up + onboarding + first plan

**Mobile screens:** `/register` → `/onboarding` (4-step) → `/home`.

**Backend endpoints:**
1. `POST /api/v1/auth/register` — body `{email, password, name}`. Creates `ClientProfile` row with bcrypt password hash. **If a `CoachInvite` for this email exists, sets `is_coach=True` and stamps `accepted_at`.** Sends a verification email (best-effort). Returns `{access_token, refresh_token}`. Sets `httpOnly` cookies too.
2. `PUT /api/v1/profile` — body `{avatar, training_days, experience_level, limitations, available_equipment}`. Final step of onboarding posts these.
3. `POST /api/v1/plans/generate` — runs `WorkoutGenerator` against the now-complete profile. **If the user has a `coach_id`, creates a `PendingApproval` row and returns `{status: "pending_approval", approval_uuid}`.** Otherwise creates an active `WorkoutHistory` row immediately.
4. App routes to `/home`.

**Tables touched:** `clientprofile`, `coachinvite` (if invited), `workouthistory` or `pendingapproval`.

**Watch points:**
- 422 on register → body missing `name`. Check `register_screen.dart`.
- 401 on `/profile` after register → access token wasn't saved. Check `TokenStorage.saveTokens` + Dio interceptor.
- "Plan under review" after generate → user has a coach assigned. Expected.
- 500 on generate → look in `app/api/plans.py:generate_plan` log line. SafetyRefusalError = legit (e.g. cardiac history blocks plan).

---

## 2. Login / logout / refresh

**Login** (`POST /api/v1/auth/login`):
- Email + password. Verifies bcrypt hash. Returns access + refresh + sets cookies.
- Mobile then calls `/auth/me` to check `is_coach`. If true → routes to `/coach`. Else `/home`.

**Logout** (`POST /api/v1/auth/logout` + mobile clears tokens):
- Clears `access_token` + `refresh_token` cookies + secure storage.

**Refresh** (`POST /api/v1/auth/refresh`):
- Body `{refresh_token}` OR cookie `refresh_token`. Issues fresh access + refresh pair (rotation).
- Mobile Dio interceptor: on any 401, calls `/auth/refresh` once with the stored refresh token. If success → retries the original request with new access token. If fail → clears tokens, user lands on `/login`.

**Watch points:**
- Stuck on login screen after correct credentials → DevTools network tab. Check that `/auth/login` returned 200 + `access_token`.
- Logged out unexpectedly → access token expired (24h) and refresh failed. Check `/auth/refresh` response. Refresh tokens last 30 days.
- 403 from coach/admin endpoint immediately after login → role flag wasn't loaded fresh. Hit `GET /api/v1/auth/whoami` to confirm what server actually sees.

---

## 3. Forgot + reset password

**Forgot** (`POST /api/v1/auth/forgot`):
- Body `{email}`. Always returns 200 (account-enumeration safe).
- If email is registered: signs a JWT (`type=password_reset`, 30-min TTL), calls `EmailService.send_password_reset` which builds `{APP_BASE_URL}/reset?token=<jwt>` and sends via SMTP.

**Reset** (`POST /api/v1/auth/reset`):
- Body `{token, new_password}`. Decodes the reset token. Min 8 chars. Sets new bcrypt hash. Returns fresh tokens for auto-login.

**Mobile flow:** `/login` → "Forgot password?" → `/forgot` (enter email, see "Check your inbox") → email arrives → tap link → `/reset?token=…` → set new password → routed to `/home`.

**Watch points:**
- No email arrives → SMTP credentials missing or wrong in `.env`. `EmailService` logs the failure; check uvicorn output.
- "Reset link is invalid or expired" → token TTL expired (>30 min) or wrong secret key. Generate fresh link.
- Account-enumeration: `/forgot` always returns 200 even for unknown emails. Confirm via uvicorn logs.

---

## 4. Email verification

**Auto-trigger on register:** `EmailService.send_verification` sends a `{APP_BASE_URL}/verify?token=<jwt>` link (48h TTL).

**Verify** (`POST /api/v1/auth/verify`): consumes the token, stamps `verified_at` on the row. Idempotent.

**Resend** (`POST /api/v1/auth/resend-verification`): authed; no-op if already verified.

**Mobile UX:** Home shows an amber "Verify your email" banner with **Resend** button while `verified_at == null`. `/auth/me` returns `verified_at`. Banner hides once stamped.

**Watch points:**
- Banner persists after clicking the link → mobile cached profile. Pull-to-refresh on home or hit `/auth/me` again.
- No critical action is gated on verification (deliberate — owner wanted users productive immediately).

---

## 5. Coach: review pending plans

**Trigger:** Sign in as someone with `is_coach=True` → app routes to `/coach`.

**Mobile screens:**
- `/coach` (CoachHomeScreen): two sections.
  - **Awaiting your review** — orange-badged list. Each card shows client name, week number, day count.
  - **Your clients** — assigned clients, each with a per-client pending count badge.
- `/coach/review/<approval_uuid>` (CoachReviewScreen): full plan inspection (every day, every exercise, sets × reps × weight × RPE), three actions.

**Backend endpoints:**
- `GET /api/v1/coach/clients` — list of `ClientProfile` rows where `coach_id == me.client_id`. Returns per-client pending count via a single batched query (no N+1).
- `GET /api/v1/coach/pending` — all `PendingApproval` rows whose `client_id` is in your assigned set.
- `GET /api/v1/coach/pending/<uuid>` — full detail incl. `edit_log`.
- `POST /api/v1/coach/approve/<uuid>` — moves the plan to active `WorkoutHistory`, marks prior active as `superseded`, deletes `PendingApproval`, updates `client.week_number`.
- `POST /api/v1/coach/reject/<uuid>` — body `{feedback}`. Deletes `PendingApproval`, persists feedback to `RejectionFeedback`. Client sees feedback on next `/today` call.
- `POST /api/v1/coach/edit/<uuid>` — body `{feedback}`. Calls `FlashCommunicationService.apply_coach_edits` (LLM mutates the workout JSON per the coach's instructions), saves back to the same `PendingApproval`, leaves it pending for re-review.

**Tables touched:** `pendingapproval`, `workouthistory`, `rejectionfeedback`, `auditevent`.

**Watch points:**
- 403 on `/coach/clients` → `is_coach` is False on your row. Confirm with `/auth/whoami`. If you're the super-admin, restart the server (lifespan self-heals).
- "Not your client" 403 → `client.coach_id != your.client_id`. Re-assign via Admin Panel.
- LLM edit failed → `OPENROUTER_API_KEY` missing/wrong, or model returned non-JSON. Check uvicorn log for `Coach edit failed for <uuid>`.

---

## 6. Admin: invite coaches + assign clients

**Mobile screens:** Profile → **Admin Panel** → TabBar.
- **Coaches tab:** active coaches + pending invites. Floating action: "Invite coach" → bottom sheet with email field. Withdraw invites with the X icon.
- **Clients tab:** all users with COACH / ADMIN / SUPER / ASSIGNED pills. Floating action: "Assign client" → bottom sheet with client + coach emails.

**Backend endpoints:**
- `GET /admin/clients` — every `ClientProfile`.
- `GET /admin/coaches` — `ClientProfile` where `is_coach=True`.
- `GET /admin/coaches/invites` — `CoachInvite` rows where `accepted_at IS NULL`.
- `POST /admin/coaches/invite` — body `{email}`. Idempotent (refreshes existing row). Sends `EmailService.send_coach_invite`. Audit log: `coach.invite`.
- `DELETE /admin/coaches/invite/<email>` — deletes the invite if not yet accepted.
- `POST /admin/assign` — body `{client_email, coach_email}`. Sets `client.coach_id`.

**Tables touched:** `coachinvite`, `clientprofile`, `auditevent`.

**Workflow:**
1. Admin invites `coach@example.com`.
2. That email signs up via the regular `/register` flow.
3. Register endpoint sees the matching `CoachInvite`, sets `is_coach=True`, stamps `accepted_at`.
4. Admin then assigns `client@example.com` to `coach@example.com`. Now any plan generated by the client routes to that coach's queue.

**Watch points:**
- "Coach not found or not a coach yet" 400 on assign → coach hasn't registered yet (only invited). Wait for them to sign up.
- Invite email never arrives → SMTP not configured. The invite row still exists; the coach can register without seeing the email.

---

## 7. Super-admin: promote / demote admins

**Mobile screens:** Profile → Admin Panel → **Admins** tab (only visible if `is_super_admin`). FAB "Promote admin" → bottom sheet with email. Each admin row has a red Demote icon (super-admin row shows SUPER pill instead — protected).

**Backend endpoints:**
- `GET /admin/admins` — super-admin only.
- `POST /admin/admins/promote` — body `{email}`. Target user must already be registered. Sets `is_admin=True, is_coach=True`. Audit: `admin.promote`.
- `POST /admin/admins/demote` — body `{email}`. Refuses to touch `super_admin_email` (400). Audit: `admin.demote`.

**Watch points:**
- Admins tab missing → you're not the super-admin. Verify via `/auth/whoami`. Only `omarkshoaib@outlook.com` is super-admin.
- "Cannot demote the super-admin" 400 → expected; super-admin is hardcoded immortal.

---

## 8. Client: workout flow with set logger

**Mobile screens:** Home → "Start Workout" → `/workout`.

For each exercise card:
- Header: slot type badge (Main / Secondary / Isolation), RPE
- Stat chips: sets, reps, target weight (in user's chosen unit)
- Inline cue card: form-cue text mirrored from `app/domain/workout/constants.py:CUES_BY_PATTERN`
- "Set 1 / Set 2 / Set 3" chips at the bottom — tap any → bottom sheet → enter actual reps + weight + optional RPE → Save → chip flips to green checkmark

**Backend endpoints:**
- `POST /api/v1/sets` — body `{history_id, day_index, slot_index, set_index, actual_reps, actual_weight, rpe?}`. Persists a `SetLog` row.
- `GET /api/v1/sets/by-history/<history_id>` — list of all set logs for that workout history.

**Units:**
- `lib/core/utils/units.dart` reads/writes `weight_unit` in SharedPreferences (kg | lb). Profile screen has a SegmentedButton.
- Display always uses `Units.format(kg)`. Input is always converted back to kg via `Units.toKg()` before persisting.

**Tables touched:** `setlog`.

**Watch points:**
- "Could not save (offline?)" snackbar → `/sets` returned non-200. Check uvicorn log + auth token.
- Chip doesn't flip green → bottom sheet returned without saving. Check log for missing required field.

---

## 9. Client: weekly check-in (legacy)

The original Telegram-bot check-in flow is preserved. On mobile it's a separate Check-in card on home.

**Mobile screens:** Home → Check-in → `/checkin`. Iterates over main lifts in the current active plan; for each, asks for actual weight + RPE.

**Backend endpoints:**
- `GET /api/v1/checkin/history` — past check-ins.
- `POST /api/v1/checkin` — body `{history_id, slots: [{exercise_name, actual_weight, actual_rpe}]}`. Validates each slot then writes back into `WorkoutHistory.workout_json`.

**What happens next:**
- Backend autoregulator (`app/domain/workout/autoregulation.py`) reads the `actual_rpe` next time a plan is generated and adjusts each main-lift's `target_weight` (`AutoRegulator.calculate_next_load`).

**Tables touched:** `workouthistory` (mutated in place).

**Watch points:**
- "Fill in weight and RPE for every lift" — validation prevents partial submits.
- Set-logger (#8) writes to `setlog` separately. Currently the autoregulator doesn't read `setlog` directly — the official bridge to the next week's load is still the check-in form. Future: switch autoregulator to read `setlog` instead.

---

## 10. Privacy: export + delete

**Export** (`GET /api/v1/profile/export`): returns a JSON dump of every row associated with the user. Profile, workout history, pending approvals, rejection feedback, set logs, feedback, profile snapshots, coach invite, audit events. Use a `curl` for now; UI button is on the roadmap.

**Delete** (`DELETE /api/v1/profile`): anonymises the row in place. Clears `name`, `email`, `password_hash`, `is_admin`, `is_coach`, `coach_id`, `verified_at`, plus notes. Drops pending approvals. Workout history rows stay (anonymous, useful for aggregate analytics). Refuses to delete the super-admin.

**Watch points:**
- Trying to delete the super-admin → 400 expected.
- After delete, the same `client_id` still exists; it just has no identifying info.

---

## 11. Diagnostics

| Endpoint | Auth | Returns |
|---|---|---|
| `GET /healthz` | none | `{status, db, smtp, llm, telegram_bot, sentry, version}` |
| `GET /api/v1/auth/whoami` | yes | `{client_id, email, is_coach, is_admin, is_super_admin, coach_id, verified_at, auth_source: {has_bearer_header, has_access_token_cookie}}` |
| `GET /api/v1/auth/me` | yes | the same flags + name + avatar + week_number |

**When something's wrong, run:**

```bash
# Roles loaded server-side
curl -H "Authorization: Bearer <token>" http://localhost:8000/api/v1/auth/whoami | python -m json.tool

# Health
curl http://localhost:8000/healthz | python -m json.tool

# DB direct inspection (SQLite)
sqlite3 beyond_fit.db "SELECT email, is_admin, is_coach, coach_id FROM clientprofile;"

# Audit trail of admin actions
sqlite3 beyond_fit.db "SELECT actor_email, action, target, created_at FROM auditevent ORDER BY id DESC LIMIT 20;"
```

---

## 12. Operational protections

- **Rate limiting:** 10 req/min/IP on `/auth/login|register|forgot|reset`. Returns 429 with friendly message. `DISABLE_RATELIMIT=true` to turn off (already set in tests).
- **CORS:** `allow_origins=*` in dev. Set `CORS_ALLOWED_ORIGINS=https://your.domain` for prod. `allow_credentials=False` while wildcard.
- **Auth secret:** `AUTH_SECRET_KEY=<random>` is required for prod. Lifespan logs a `⚠️` warning if still on the default placeholder. Generate with `python scripts/generate_secret.py --append-to .env`.
- **Cookies:** `httpOnly` on `access_token` + `refresh_token`. `COOKIE_SECURE=true` in prod flips Secure + SameSite=Strict.
- **Audit log:** every admin role change writes an `AuditEvent` row.
- **Backup:** `./scripts/backup_db.sh ./backups`.

---

## 13. Telegram bot (still alive)

The original Telegram bot at `app/bot.py` continues to work. It reads + writes the same `PendingApproval` table. So:
- A plan generated from mobile by a client with a coach lands in the coach's mobile queue **and** triggers a Telegram notification to `ADMIN_TELEGRAM_ID` (legacy: only one admin).
- Either side can approve / reject. Whichever approves first wins; the other side's row vanishes.

**Watch points:**
- If both sides approve simultaneously, second approve gets 404 "Approval not found". Idempotent enough.
- If you don't want the Telegram path, don't run `python -m app.bot`. The mobile coach flow is fully self-sufficient.

---

## What's deliberately NOT built (yet)

- **Push notifications.** Coach approves your plan → mobile app doesn't get a push. You learn on next pull-to-refresh. Adding requires a Firebase project + APNs cert.
- **Coach broadcast / inbox.** Coach can't message a client outside of the reject feedback. Roadmap.
- **Rest-timer overlay** between sets. Roadmap.
- **Skeleton loaders** on more screens. Spinners only for now.
- **Apple Health / Google Fit.** Out of scope.
- **Stripe billing.** Out of scope.
- **Multi-coach per client.** 1:1 only.
- **Coach analytics dashboard.** Roadmap, blocked on usage data.
- **AI form-check from video.** Out of scope.

See `PLAN.md` for the full roadmap with effort tags.

---

## Sanity checklist before reporting "broken"

1. Backend running? `curl http://localhost:8000/healthz` → `{"status": "ok", "db": "ok"}`.
2. DB has the right schema? `sqlite3 beyond_fit.db ".schema clientprofile"` should include `is_coach`, `is_admin`, `coach_id`, `verified_at`. Lifespan auto-rebuilds on drift but only on SQLite.
3. Token used by mobile? Open Chrome DevTools → Application → Local Storage → `localhost:port` → `access_token`. Decode at https://jwt.io. The `sub` claim is your `client_id`.
4. Server-side role state? `curl -H "Authorization: Bearer <token>" .../auth/whoami`. Confirms what the server actually thinks about you.
5. Audit trail? `sqlite3 beyond_fit.db "SELECT * FROM auditevent ORDER BY id DESC LIMIT 5;"`.

If those four match what you expect and a flow still misbehaves, the bug is real. File via Profile → Send feedback (lands in `feedback` table) or open a ticket.
