# Changelog

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
