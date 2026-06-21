# Changelog

## [1.7.0] — 2026-06-21 — SP-D: pre-payment pitch

### Added
- A compelling static pitch ("Why Beyond Fit?") is now shown before the plan prices in the
  subscribe funnel (and via a root-menu button), so prospects know what they're paying for —
  human-approved plans, weekly auto-regulation, ability/equipment/injury-aware programming,
  halal nutrition, and a direct line to their coach. No model/migration.

## [1.6.0] — 2026-06-21 — SP-C: client↔coach Q&A

### Added
- Clients can ask their coach a question (`/ask` or the now-live plan "❓ Question" button);
  routed to the coach with an LLM-drafted answer + client background; coach Sends / Edits /
  Dismisses; the answer is DM'd back. New `ClientQuestion` table (Alembic 0022). Max 3 pending
  questions/client; the LLM draft is always coach-reviewed, never auto-sent. The dead-end
  "Question" button (which promised a coach reply that never came) now actually delivers.

## [1.5.0] — 2026-06-20 — SP-B1: ability-appropriate exercise selection

First half of SP-B (B2 = auto-progression, deferred).
See `docs/superpowers/plans/2026-06-20-spb1-ability-regressions.md`.

### Added
- `difficulty_tier` on every exercise + 6 sourced difficulty ladders
  (`app/domain/workout/ability.py`); a beginner who can't do a pull-up now gets the
  assisted pull-up / pulldown, an advanced client gets the barbell mains.
- `ClientProfile.exercise_ability` (Alembic 0021) set by a 6-family intake survey,
  defaulting from experience level (beginner 2 / intermediate 4 / advanced 4) when skipped.
- Ability-governed selection: a compound anchor slot picks the client's ladder rung; no
  exercise exceeds the client's family ability; the difficulty ceiling is never dropped in
  fallback; the ladder pick re-validates injury/avatar safety.
- `bw_incline_pike_push_up` regression rung; bodyweight-main check-in collects RPE not weight.

### Safety
- `_default_tier` forces every free-bar compound (barbell / trap_bar / ez_bar) to tier ≥4
  so a beginner is never handed a heavy loaded lift through the fallback.

### Deferred
- SP-B2: auto-advancing the variant over time from check-in competence.

## [1.4.0] — 2026-06-20 — SP-A: equipment-aware plans + intake back button

First of four sub-projects (SP-A..D) from client-test feedback.
See `docs/superpowers/plans/2026-06-20-spa-equipment-back-button.md`.

### Added
- Equipment survey at intake (preset menu + 15-item checklist + an explicit
  pull-up-bar question on the bodyweight path), replacing the hardcoded `full_gym` —
  non-gym clients no longer receive impossible exercises (C1).
- `/update_profile` → Equipment to edit equipment after intake; unfreezes legacy
  `full_gym` clients (C2).
- Intake back navigation (forward-replay) so a wrong answer can be corrected mid-flow,
  with idempotent confirm handlers (C3).
- Bodyweight floor: `bw_air_squat`, `bw_reverse_lunge`, `bw_single_leg_rdl`,
  `bw_knee_push_up`, `bw_inverted_row_bar` — a no-gym client now gets a complete
  legs+push day (full 7/7 patterns with a pull-up bar) (C4).
- Coach approval DM flags a no-pulling equipment gap (C5).
- Equipment guard (`validate_equipment`) on all three plan-write paths: `/override`
  set-time check, reject LLM-edit block, and a generation-write coach flag — each with
  the reason + equipment-valid alternatives (C6).

### Internal
- New pure module `app/domain/workout/equipment.py` (vocabulary, presets, floor,
  validator, alternatives, reachability). The generator treats an empty
  `available_equipment` as `full_gym` (legacy-safe).

## [1.3.0] — 2026-06-13 — Usability + safety cluster

Four independent deterministic slices wired into the coaching engine.
See `docs/superpowers/plans/2026-06-13-usability-safety-cluster.md`.

### Safety
- Declared injuries now gate exercise selection, not just collected.
  `knee_pain` bans squat/lunge; `shoulder_impingement` bans overhead/upright-row
  movements; `lower_back_pain` bans hinge and back-loaded squat (expanded from
  hinge-only — clinically intended). A Tier-5 last-resort substitution in
  `_select_for_slot` ensures no training day is ever left empty.
  `wrist_pain`/`hip_flexor_tightness` add a coaching cue on affected slots
  without restricting the exercise pool.

### Usability
- Week-1 plans now seed starting loads from optional squat/bench/deadlift
  baselines entered at intake (Brzycki e1RM → Tuchscherer RPE/%1RM table,
  rounded down to 2.5 kg). Three skippable intake questions added to the bot.
  The prior-week autoregulator takes over from week 2; skipped baselines fall
  back to rep+RPE guidance strings.
- Meal plans now vary day-to-day: `build_day_plan` accepts `day_index` and
  rotates food selection so a 7-day plan draws different foods each day.
  The >5×/week cap still applies on top.

### Accuracy
- Each generated nutrition day is validated (kcal ±10%, protein ±5%, fat ≤ AMDR
  35%, fiber floor). Residual drift is non-blocking — the plan still persists —
  but is surfaced to the coach in the plan `rationale` as "[macro drift]".

### Schema
- Migration `0020_client_baseline_e1rm`: 3 nullable `DOUBLE PRECISION` columns
  added to `clientprofile` (`squat_e1rm`, `bench_e1rm`, `deadlift_e1rm`).

### Tests
- 324 passing (was 288). New test files: `test_loadseed.py`,
  `test_injury_substitution.py`, `test_meal_rotation.py`,
  `test_nutrition_validation_gate.py`. New tests in `test_bot_flow.py` and
  `test_generator_hardening.py`.

## [1.2.0] — 2026-06-06 — Audit hardening

Full multi-module audit (43-agent read-only sweep) + fixes for the 29 confirmed
bugs. See `AUDIT_REPORT.md` and `docs/superpowers/plans/2026-06-06-audit-hardening.md`.

### Security
- Production refuses to boot on the insecure default `auth_secret_key`.
- Access-token verifier rejects refresh/reset/verify tokens (token-type confusion).
- `/generate` + `/generate_and_coach` now require authentication.
- Bot nutrition approve/discard gated to assigned coach or super-admin; medical
  safety-clear restricted to super-admin.
- Account deletion scrubs PII from `ProfileSnapshot` snapshots and `Feedback`.

### Nutrition
- Halal-only catalog (pork removed); inert religious filter dropped; junk `egan`
  diet tag fixed. Single balanced diet style; low-carb is goal-integrated.
- Medical filter degrades gracefully (never empties the pool); the service refuses
  to persist a degenerate ~0-kcal plan.

### Workout engine
- Powerlifter accessory slots draw from the powerbuilder pool (no more thin days).
- Per-day volume budget (symmetric repeated day-types); AutoRegulator capped to ±10%.
- Tier-4 selection fallback eliminates empty/1-slot days.

### Delivery + data
- Nutrition PDF meal-card + shopping-list render bugs fixed (was never delivering).
- Mobile coach-review exercise names fixed (were rendering `?`).
- Check-in: extraction failure no longer discards telemetry / advances the week;
  the lift catalog now carries canonical exercise_ids; coach-edit LLM output is
  validated as a `WorkoutWeek` before it can overwrite a plan.
- 5 clone exercises removed (179 → 174) + contradictory fatigue costs resolved.

## [1.1.0] — 2026-05-03

### Added — role/auth model
- **Super-admin** role (hardcoded `omarkshoaib@outlook.com`). Lifespan self-heals
  the row's `is_admin` + `is_coach` flags on every server boot.
- **Invite-only coaches**: `CoachInvite` table + `POST /admin/coaches/invite`,
  `DELETE /admin/coaches/invite/<email>`, `GET /admin/coaches/invites`. New
  registrants whose email is in `coach_invite` automatically get `is_coach=True`.
- **Promote / demote admins** (super-admin only): `POST /admin/admins/promote`,
  `POST /admin/admins/demote`. Refuses to demote the super-admin.
- New `is_super_admin` flag in `/auth/me`.
- New diagnostic `GET /auth/whoami` returning roles + auth-source flags
  (Bearer header vs cookie). Eliminates blind 403 debugging.

### Added — workout flow
- **Per-set logger**: `SetLog` table + `POST /sets` + `GET /sets/by-history/<id>`.
  Workout screen now shows tap-to-log set chips with reps + weight + RPE
  bottom sheet.
- **Exercise cues** rendered inline under each slot card.
- **kg / lb unit toggle** on Profile (persisted in SharedPreferences). All
  workout / log displays honour the choice.

### Added — coach + admin UX
- **Coach edit-via-LLM**: `POST /coach/edit/<uuid>` mutates a pending plan via
  `FlashCommunicationService.apply_coach_edits()` (same path Telegram uses).
  Coach review screen has a new "Edit plan via LLM before approving" action.
- **Admin panel rewrite**: TabBar with Coaches / Clients / Admins
  (Admins tab visible only to super-admin). Invite / withdraw / promote /
  demote bottom sheets.

### Added — ops / privacy
- **Healthz**: `GET /healthz` reports DB / SMTP / LLM / Sentry / Telegram /
  version. No auth.
- **Rate limiting** on `/auth/login|register|forgot|reset` (10 req/min/IP).
- **Sentry** init when `SENTRY_DSN` set.
- **Structured JSON logging** when `STRUCTLOG_JSON=true`.
- **Audit log** of admin actions (`AuditEvent` table).
- **Soft delete + GDPR export**: `DELETE /profile` anonymises the row,
  `GET /profile/export` returns a full data dump.
- **Backup script**: `scripts/backup_db.sh` for SQLite or Postgres.
- **In-app feedback** button on Profile → `POST /feedback`.

### Changed
- **SQLite drift detector**: lifespan compares live `clientprofile` columns
  against the model and rebuilds the DB if columns are missing. Eliminates
  schema drift after model changes (dev only — destructive).
- `app/database.py` now runs `create_all()` at import time so TestClient flows
  that don't enter the FastAPI lifespan still find tables.
- `/api/v1/auth/refresh` accepts the refresh token from JSON body OR
  `refresh_token` cookie.

### Migrations
- `0014_coach_invite` — `coachinvite` table.
- `0015_set_log_feedback` — `setlog` + `feedback` tables.
- `0016_audit_event` — `auditevent` table.

### Tests
- 134 passing (was 121). New tests: super-admin self-heal, super-admin
  cannot be demoted, invited email registers as coach, non-invited registers
  as client, non-super-admin cannot promote, healthz, profile export, set
  logger, feedback submission.

---

## [1.0.0] — earlier

Initial release. See git history for the bootstrap, mobile scaffold,
backend REST API, JWT auth, password reset, email verification, etc.
