# Beyond Fit — Mobile App Status & Roadmap

**As of 2026-05-03.** Last commit: `483497b` (review-driven hardening).

This document inventories what's working end-to-end vs. what still needs to be built for the mobile app + coach/admin flow to be production-ready. The original Telegram-bot project roadmap is in `Plan.md`; the runtime instructions are in `RUN.md`.

---

## ✅ Implemented & working

### Backend (FastAPI, `/api/v1/*`)

| Endpoint | Method | Purpose |
|---|---|---|
| `/auth/register` | POST | Create account (email + password + name). Returns access + refresh JWTs. |
| `/auth/login` | POST | Email + password sign-in. Returns access + refresh JWTs. |
| `/auth/me` | GET | Current user profile incl. `is_coach`, `is_admin`, `coach_id`, `week_number`. |
| `/profile` | GET / PUT | Read or partial-update onboarding fields (avatar, days, experience, equipment, limitations, notes). |
| `/plans/generate` | POST | Run `WorkoutGenerator` on the authenticated user. Idempotent: if a `PendingApproval` already exists, returns its UUID instead of creating a duplicate. Routes to `PendingApproval` when client has `coach_id`, otherwise creates active `WorkoutHistory` directly. |
| `/plans/current` | GET | Latest active `WorkoutHistory`. |
| `/plans/today` | GET | Returns `{day, day_index, total_days, no_plan, pending_review, rejection_feedback}`. Day index derived from `plan_started_at` offset (modulo `total_days`). |
| `/plans/history` | GET | All `WorkoutHistory` rows for the user. |
| `/checkin/history` | GET | Past check-ins. |
| `/checkin` | POST | Submit per-slot actual weight + RPE. |
| `/progress` | GET | RPE trend + load trend arrays for charting. |
| `/nutrition/plan` | GET | Active nutrition plan (404 when feature disabled). |
| `/coach/clients` | GET | Coach's assigned clients with per-client `pending_count`. Single-batched query (no N+1). |
| `/coach/pending` | GET | All pending approvals across this coach's clients. |
| `/coach/pending/{uuid}` | GET | Detail incl. `edit_log`. |
| `/coach/approve/{uuid}` | POST | Move `PendingApproval` → active `WorkoutHistory`. Supersedes prior active. |
| `/coach/reject/{uuid}` | POST | Delete `PendingApproval`, persist `RejectionFeedback` row. Client sees feedback on next `/today`. |
| `/admin/clients` | GET | All users + their roles + assignment. |
| `/admin/coaches` | GET | Filtered list of `is_coach=True` users. |
| `/admin/promote` | POST | Flip `is_coach` (and optionally `is_admin`) on a user by email. |
| `/admin/assign` | POST | Set `client.coach_id = coach.client_id` by email pair. |

**Auth:** JWT (HS256, `python-jose`). Bcrypt password hashing (`passlib`). Bearer token in `Authorization` header. Access token 24h, refresh token 30d (refresh endpoint exists in `app/auth/jwt.py` but no `/auth/refresh` route is wired — see "Not yet implemented").

**Data model (new fields in this iteration):**
- `ClientProfile.is_coach: bool`, `is_admin: bool`, `coach_id: Optional[str]` (alembic 0011, batch_alter for SQLite compat).
- `RejectionFeedback` table (alembic 0012): `id, client_id, feedback, created_at, consumed`.
- `ClientProfile.password_hash` (alembic 0010).

**Cross-cutting:**
- CORS middleware. `cors_allowed_origins` setting (default `*` for dev, comma-list for prod). `allow_credentials=False` so wildcard is safe.
- All coach/admin endpoints gated by `_require_coach()` / `_require_admin()` (HTTP 403 otherwise).
- TOCTOU-safe enough for MVP: each coach/admin endpoint re-checks tenant on every call.

**Tests:** 113/113 passing. Includes:
- Full coach + admin flow (`test_coach_admin_full_flow`)
- Idempotent generate (`test_idempotent_generate_when_pending_exists`)
- Rejection feedback round-trip (`test_rejection_surfaces_feedback_to_client`)
- Fresh-user onboard → generate (`test_generate_plan_for_fresh_user`)
- Plus 93 inherited unit/integration tests for the deterministic engine.

### Mobile (Flutter — Web + iOS + Android sources, web currently verified)

**Screens implemented:**

| Route | Screen | Function |
|---|---|---|
| `/login` | LoginScreen | Email + password, password-reveal toggle, error card, gradient hero logo. |
| `/register` | RegisterScreen | Name + email + password, validation, error card. |
| `/onboarding` | OnboardingScreen | 4-step PageView: avatar → days → experience → limitations. Animated step dots. Final step PUTs profile + POSTs `/plans/generate` then routes to `/home`. |
| `/home` | HomeScreen | Greeting, today's session card, quick-action grid (Progress / Check-in / Plan / Nutrition). Empty states for: no plan / pending review / coach feedback / connection error. |
| `/workout` | WorkoutScreen | Per-slot card: name, sets × reps × weight, RPE, slot-type badge. Handles both int and string-range reps. |
| `/plan` | PlanScreen | Full week, expandable day cards with all exercises. |
| `/plan/history` | PlanHistoryScreen | Past plans list. |
| `/checkin` | CheckinScreen | Iterates main lifts, validates weight > 0 + RPE ∈ [1,10] before submit. |
| `/progress` | ProgressScreen | RPE trend + load trend line charts (`fl_chart`). |
| `/profile` | ProfileScreen | User card + roles. Conditional Coach Dashboard / Admin Panel entries. Generate New Plan, Plan History, Sign out. |
| `/profile/edit` | EditProfileScreen | Slider for days, chips for experience, filter chips for limitations. |
| `/nutrition` | NutritionScreen | Macro chips + meal accordion. Friendly fallback if backend 404s. |
| `/coach` | CoachHomeScreen | Pending queue + clients list with badges. |
| `/coach/review/:uuid` | CoachReviewScreen | Full plan inspection + Approve (green) / Reject (red, opens feedback bottom sheet). |
| `/admin` | AdminScreen | Promote-coach + Assign-client modals. Full client list with COACH / ADMIN / ASSIGNED pills. |

**Cross-cutting:**
- `core/api/api_client.dart`: Dio with interceptor that injects `Authorization: Bearer …` and clears tokens on 401.
- `core/storage/token_storage.dart`: branches on `kIsWeb` — `SharedPreferences` (localStorage) on web, `flutter_secure_storage` (Keychain / Keystore) on native.
- `core/router.dart`: GoRouter with `CustomTransitionPage` fade transitions and a redirect that bounces unauthenticated routes back to `/login`.
- `core/widgets/friendly_error.dart`: Reusable empty/error card with icon + title + message + retry button.
- API base URL via `--dart-define=API_BASE_URL=…` (defaults to `http://localhost:8000/api/v1`).
- Material 3 dark theme.

**Verified builds:** `flutter analyze` (0 errors, 19 deprecation infos), `flutter build web` (succeeds, ~52s).

### Tooling

- `scripts/promote_admin.py` — bootstrap CLI for the first admin (since `/admin/promote` itself requires an existing admin).
- `RUN.md` — how to run both halves + the coach/admin flow.

---

## 🟡 Partial / known MVP-acceptable limitations

| Area | Current state | Why acceptable for MVP |
|---|---|---|
| **Web token storage** | `SharedPreferences` = `localStorage` — readable by any XSS. | iOS/Android builds use Keychain/Keystore automatically. Web is dev/preview only for now. |
| **Refresh token rotation** | `create_refresh_token()` exists, no `/auth/refresh` route. On 401, mobile clears tokens and forces re-login. | 24h access window is workable for early users. |
| **Bootstrap admin script** | Anyone with shell access to the host can flip `is_admin`. | Bootstrap-only. Should be removed from prod images. |
| **TOCTOU on coach approve** | If admin de-assigns a client between `/coach/pending` view and `/coach/approve`, the coach can still approve a stale plan. | Requires admin action *during* the seconds a coach reviews — extremely unlikely. |
| **Telegram bot ↔ mobile coexistence** | The bot still runs and writes to the same `PendingApproval` table. Telegram admin can approve a plan that originated from mobile, and vice versa. | Intentional — gives admins flexibility. |
| **No migration runner in CI/CD** | SQLite dev uses `SQLModel.metadata.create_all()` on lifespan start, which only creates missing tables (won't ALTER). Postgres deployments need `alembic upgrade head` run by hand. | Documented; Postgres prod will get a CI job. |
| **No nutrition write endpoints on mobile** | The deterministic nutrition engine + display flow exists; setting macros / goals is still Telegram-only. | Workout flow is the priority. |
| **Localization** | English-only strings hard-coded. | Single market for now. |
| **Push notifications** | None — clients have to refresh `/today` to learn that their coach approved. | Pull-to-refresh is good enough; push is a follow-up. |
| **Forgot password** | No `/auth/forgot` endpoint. | Will pair with email-templated reset when SMTP credentials stabilise. |
| **Session expiry UX** | Hard 401 → token cleared → user lands on login with no toast. | Good enough; will smooth out with refresh-token flow. |

---

## ❌ Not yet implemented — to make this "work perfectly"

### P0 — required before App Store / Play Store submission

1. ~~**Refresh token endpoint + rotation.**~~ ✅ Done. `POST /auth/refresh` rotates both access + refresh. Mobile interceptor retries the original request once after refreshing on 401, only clears tokens if refresh itself fails. Tests: `test_refresh_returns_new_pair`, `test_refresh_rejects_access_token`, `test_refresh_rejects_garbage`.
2. **`httpOnly` cookie or secure mobile-only storage on web.** Replace `localStorage` with backend-set `httpOnly; Secure; SameSite=Strict` cookies for the web build. Keep `flutter_secure_storage` for native.
3. **Forgot-password flow.** `POST /auth/forgot` (sends signed reset link via SMTP) + `POST /auth/reset` (consumes token + sets new password) + UI screens.
4. **Email verification at registration.** Currently anyone can register with any email. Add `verified_at` field + verify-link flow + gate critical actions on it.
5. ~~**Strong `AUTH_SECRET_KEY` in deployment.**~~ ✅ Done. `scripts/generate_secret.py` generates a base64url 64-char secret. Backend logs a `⚠️` warning at startup if the default placeholder is still in use. Same warning fires for `CORS_ALLOWED_ORIGINS=*`.
6. ~~**CORS lockdown.**~~ ✅ Done — settings-driven, startup warning when wide-open.
7. **CI/CD pipeline.** Run `pytest`, `flutter analyze`, `flutter build apk`, `flutter build ios`, `alembic upgrade head` on every push.
8. **App icons + splash screens.** `flutter_launcher_icons` + `flutter_native_splash` configs aren't set; current icons are the Flutter default.
9. **Deep links / universal links** for iOS + `intent-filter`s for Android (so password-reset emails open the app).
10. **App-store metadata.** Privacy policy URL, screenshots, app description, in-app purchase model (if any).

### P1 — UX polish to feel like a real app

11. **Push notifications via FCM/APNs** for "Coach approved your plan", "New feedback from coach", "Time for your weekly check-in".
12. **Workout-in-progress logger.** Currently `/workout` is read-only. Add per-set tap-to-log so clients can record actual reps + weight as they go (front-loads the check-in step).
13. **Rest-timer overlay** between sets.
14. **Exercise demo videos / form cues.** Hook into existing `cues_by_pattern` strings, embed YouTube IDs.
15. **Coach can edit a plan before approving.** Currently approve takes the LLM-untouched generator output; reject deletes it. Add a "Tweak" mode that calls the existing `FlashCommunicationService.apply_coach_edits()` (already used by Telegram bot) and saves the mutated JSON.
16. **Coach can broadcast a message to a client.** Plain text inbox per assigned coach-client pair.
17. **In-app feedback / bug-report.** "Shake to send feedback" or a Profile entry that ships a logs bundle to Sentry.
18. **Pull-to-refresh + skeleton loaders** on more screens (only home has one).
19. **Localised numbers.** kg vs lb, RPE vs RIR. Profile setting + display formatter.
20. **Onboarding back button.** Currently next-only; can't go back inside the PageView.

### P2 — operational maturity

21. **Sentry / error reporting.** Both backend (`sentry-sdk[fastapi]`) and Flutter (`sentry_flutter`).
22. **Structured logging on the backend.** Replace `logging.basicConfig` with `structlog` JSON output.
23. **Rate limiting** on `/auth/*` endpoints (`slowapi`).
24. **Backup script** for the SQLite/Postgres DB.
25. **Audit log** of admin actions (promote, assign, role changes).
26. **Health-check endpoint** richer than `/` — DB connectivity + LLM availability.
27. **Multi-coach support** per client (currently 1:1 client→coach). Add `coach_assignments` table if needed.
28. **Coach dashboard analytics** — week-over-week RPE / load trends across all assigned clients.
29. **Soft delete + GDPR export endpoints.** Right-to-be-forgotten requires a deletion job that also wipes WorkoutHistory + ProfileSnapshot rows.
30. **Telegram bot deprecation plan or hand-off.** Decide whether bot stays for power-users or sunset once mobile coach UI is feature-complete.

### P3 — speculative / nice-to-have

31. **Apple Health / Google Fit integration** for body weight, heart rate, sleep.
32. **Strava-style social feed** — share completed workouts.
33. **Coach billing / subscription** layer (Stripe).
34. **Web admin dashboard** as a separate React/Next app (currently admin uses the Flutter web build, which is fine but cramped on big screens).
35. **AI-generated form-check from uploaded video.** Out of scope unless a strong vision model becomes cheap.

---

## Quick reference — directory map

```
beyond_fit_app/
├── app/                            # FastAPI backend
│   ├── api/                        # Mobile REST API
│   │   ├── auth.py                 # Register / login / me
│   │   ├── plans.py                # generate / current / today / history
│   │   ├── profile.py              # GET / PUT
│   │   ├── checkin.py              # POST / history
│   │   ├── progress.py             # RPE + load trends
│   │   ├── nutrition.py            # Active nutrition plan
│   │   ├── coach.py                # ⭐ NEW — coach endpoints
│   │   └── admin.py                # ⭐ NEW — admin endpoints
│   ├── auth/
│   │   ├── jwt.py                  # python-jose helpers
│   │   ├── deps.py                 # get_current_user, get_db
│   │   └── schemas.py              # Pydantic auth bodies
│   ├── domain/                     # Pure-Python deterministic engine
│   ├── services/                   # LLM / PDF / SMTP
│   ├── bot.py                      # Telegram polling process (still runs)
│   ├── generator.py                # WorkoutGenerator entry
│   ├── main.py                     # FastAPI app factory + CORS
│   ├── models.py                   # SQLModel tables (+ RejectionFeedback)
│   └── settings.py                 # Pydantic settings
├── alembic/versions/
│   ├── 0010_add_password_hash.py
│   ├── 0011_coach_role.py          # ⭐ NEW
│   └── 0012_rejection_feedback.py  # ⭐ NEW
├── mobile/                         # Flutter app
│   ├── lib/
│   │   ├── core/                   # api/, models/, storage/, theme/, widgets/, router
│   │   └── features/
│   │       ├── auth/               # login + register
│   │       ├── onboarding/         # ⭐ NEW
│   │       ├── home/
│   │       ├── workout/            # workout, plan, plan_history
│   │       ├── checkin/
│   │       ├── progress/
│   │       ├── profile/            # profile + edit_profile
│   │       ├── nutrition/
│   │       ├── coach/              # ⭐ NEW — home + review
│   │       └── admin/              # ⭐ NEW — admin panel
│   ├── android/  ios/  web/
│   └── pubspec.yaml
├── scripts/
│   └── promote_admin.py            # ⭐ NEW — bootstrap first admin
├── tests/                          # 113 passing
│   ├── test_api.py
│   ├── test_bot_flow.py
│   ├── test_checkin.py
│   ├── test_generator.py
│   ├── test_mobile_api.py          # ⭐ NEW — mobile + coach + admin
│   ├── test_nutrition.py
│   └── test_pdf.py
├── Plan.md                         # Original Telegram-bot roadmap
├── PLAN.md                         # ← this file
├── README.md
├── RUN.md                          # Run + use instructions
├── PIPELINE_REPORT.md
├── RUNBOOK.md
└── CLAUDE.md
```

---

## Verification commands

```bash
# Backend tests
cd /media/shoaib/NewVolume/beyond_fit_app
DATABASE_URL=sqlite:///./beyond_fit_test.db python -m pytest -q
# Expected: 113 passed

# Flutter analyze
export PATH="$PATH:/media/shoaib/NewVolume/flutter/bin"
cd mobile && flutter analyze
# Expected: 0 errors

# Flutter web build
flutter build web --dart-define=API_BASE_URL=http://localhost:8000/api/v1
# Expected: ✓ Built build/web

# End-to-end smoke
rm -f beyond_fit.db
DATABASE_URL=sqlite:///./beyond_fit.db uvicorn app.main:app --reload &
flutter run -d chrome --dart-define=API_BASE_URL=http://localhost:8000/api/v1
# Browser opens → register → onboard → today's session renders
```

---

## What "perfectly" means

If we walked through every P0 item above (`/auth/refresh`, `httpOnly` web cookies, password reset, email verification, strong secret + locked-down CORS, CI, app icons + splash, deep links, store metadata), the app would be ready for App Store / Play Store submission and could be safely opened to public sign-ups.

Items in P1 are what the *user* will notice ("why doesn't it tell me when my coach approves?"). Items in P2/P3 are what the *operator* will need at scale.
