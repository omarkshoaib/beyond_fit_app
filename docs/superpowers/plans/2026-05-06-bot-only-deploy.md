# Bot-Only Deploy + Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the existing Telegram bot to a single Ubuntu host (95.111.247.88) as the only production interface. Plan delivery is Telegram-native (PDF document + inline summary). Email path is removed. Mobile/REST stays dormant. Fix the small set of high-severity bugs that block a clean end-to-end run, harden the docker-compose, and document a runbook the operator can follow.

**Architecture:** Single host. `docker compose` runs Postgres 16 + the existing `bot` container. No reverse proxy, no TLS, no FastAPI service. Telegram handles transport security. Secrets live in `.env` on the host (`chmod 600`). Backups: nightly cron of `scripts/backup_db.sh` to `/var/backups/beyond_fit/`. Logs: docker's default JSON driver with rotation caps.

**Tech Stack:** Python 3.12, python-telegram-bot, SQLModel/Alembic, PostgreSQL 16, WeasyPrint, OpenRouter (Gemini Flash Lite), Docker + Compose v2.

---

## Pre-flight context (read before starting)

- The bot already calls `context.bot.send_document()` with PDF bytes (`app/bot.py:2066`). The Telegram path works today.
- `EmailService.send_plan` is invoked with two wrong kwargs (`to_email` instead of `recipient_email`, and a non-existent `week_number`) at `app/bot.py:2074-2078`. The call raises `TypeError` on every approve, but a try/except logs `"Email delivery failed (non-fatal)"` and continues. Email has effectively never worked; removing it is a no-behaviour-change cleanup.
- The check-in flow filters slots with `slot.slot_type in ("main_compound", "main_lift")` at `app/bot.py:743`. The generator only ever sets `"main_compound"` (`app/generator.py:426`). The compound filter is harmless but the dead `"main_lift"` literal is a trap when someone reads the code later. Drop it.
- `super_admin_email` is hardcoded to `omarkshoaib@outlook.com` (`app/settings.py:48`). Self-heal runs at lifespan startup. Keep as-is.
- `.env.example` lists SMTP + AUTH_SECRET_KEY + CORS even though the bot path needs none of them. Keep the file but mark them optional in a comment block; the bot only requires DATABASE_URL, OPENROUTER_API_KEY, TELEGRAM_BOT_TOKEN, ADMIN_CHAT_ID.
- `docker-compose.yml` has no `web` service. Good — that matches scope.
- `Dockerfile` `CMD` is `python -m app.bot`. Good.
- The bot uses `os.getenv("ADMIN_TELEGRAM_ID")` at 14 sites. `Settings` exposes `admin_chat_id`. The `.env.example` documents `ADMIN_CHAT_ID`. There are TWO env-var names referring to the same thing. Operator must set both, or we standardise. We standardise on `ADMIN_CHAT_ID` (settings) and add a shim in the bot. (See Task 4.)

---

## File Structure (what gets touched)

| File | Change | Reason |
|---|---|---|
| `app/bot.py` | Modify around lines 2066–2082 | Remove broken email call, add inline plan summary message after PDF |
| `app/bot.py` | Modify line 743 | Drop dead `"main_lift"` literal from check-in filter |
| `app/bot.py` | Modify ~14 `os.getenv("ADMIN_TELEGRAM_ID")` sites | Centralise to a module helper that reads `ADMIN_CHAT_ID` first, falls back to `ADMIN_TELEGRAM_ID` |
| `app/bot.py` | Add `_format_plan_summary(workout)` helper | New inline summary text companion to PDF |
| `app/services/email_service.py` | Untouched | Still imported elsewhere (REST routes); leave alone, just stop calling from bot |
| `docker-compose.yml` | Modify | Require `POSTGRES_PASSWORD` (no default), pin Postgres minor, add log rotation, drop SMTP env block |
| `.env.example` | Modify | Mark email/auth/CORS as REST-only optional, add `ADMIN_CHAT_ID` next to existing one, comment SMTP out |
| `scripts/deploy.sh` | Create | One-shot host bootstrap: install docker if missing, write `.env` template, fetch repo, `docker compose up -d` |
| `scripts/health_check.sh` | Create | Polls bot container health, alerts on stdout if unhealthy. Used by cron or run manually |
| `docs/RUNBOOK_BOT_ONLY.md` | Create | Operator-facing runbook for 95.111.247.88 — install, deploy, restart, backup, view logs, smoke-test checklist |
| `tests/test_admin_approve_flow.py` | Create | Pytest async test that exercises `_do_approve_confirmed()` end-to-end with mocked Telegram bot, asserts `send_document` was called and email is NOT |
| `tests/test_checkin_filter.py` | Create | Asserts `slot_type` filter behaviour against a generated workout |

---

## Phase 1 — Bug fixes (code)

### Task 0: Capture pre-existing test baseline

Run the suite **before** any change so you can tell pre-existing failures apart from regressions you introduce.

- [ ] **Step 1: Run pytest, save the output**

```bash
pytest -q --tb=line | tee /tmp/pytest_baseline.txt
```

- [ ] **Step 2: Note any failing tests in this plan**

If anything fails, append a short list to the bottom of this section so future tasks know "these were already red." Example block to paste:

```
### Pre-existing failures (captured 2026-05-06)
- tests/foo.py::test_bar — flaky on SQLite, unrelated
```

If everything is green, write `### Pre-existing failures: none` instead so the file says so explicitly.

- [ ] **Step 3: Commit the baseline file (optional)**

If you want the baseline tracked:

```bash
mkdir -p docs/superpowers/baselines
cp /tmp/pytest_baseline.txt docs/superpowers/baselines/2026-05-06-pytest.txt
git add docs/superpowers/baselines/2026-05-06-pytest.txt
git commit -m "chore: pytest baseline before bot-only deploy work"
```

### Task 1: Remove the broken email send from approval flow

**Files:**
- Modify: `app/bot.py:2073-2082`
- Test: `tests/test_admin_approve_flow.py` (new)

- [ ] **Step 0: Re-read the function source**

The current `_do_approve_confirmed` lives at `app/bot.py:2026-2109`. Real signature is:

```python
async def _do_approve_confirmed(query, approval_id: str, context: ContextTypes.DEFAULT_TYPE) -> None:
```

Read the entire body before touching it. Note the existing structure you must preserve:

1. **First DB session** loads `PendingApproval` via `session.get(PendingApproval, approval_id)` (PK lookup, not `select`), then loads `ClientProfile` via `session.get`. Both are read-only.
2. **PDF render block** (2044–2063) uses a `transient_history` constructed from `pending.workout_json` (raw string, not re-serialised).
3. **`send_document` call** (2066–2071) — keep verbatim.
4. **Email block** (2072–2081) — this is what we delete.
5. **Final atomic transaction** (2083–2107) marks any active `WorkoutHistory` for that client `superseded`, inserts a new `active` row using `pending.workout_json` raw, then deletes the pending row by `session.get(PendingApproval, approval_id)` (re-fetch to avoid stale reference).
6. **Final `query.edit_message_text`** (2109).

Do NOT change any of the surviving logic, only:
- delete the email block
- inject a call to `_format_plan_summary` + `context.bot.send_message` after `send_document`

This is a *minimal* refactor, not a rewrite. The helper extraction below is for testability only and must produce byte-identical behaviour.

- [ ] **Step 1: Write the failing test**

Create `tests/test_admin_approve_flow.py`:

```python
"""Verifies the admin-approve path delivers the PDF via Telegram and never calls EmailService."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models import (
    ClientProfile,
    PendingApproval,
    WorkoutDay,
    WorkoutHistory,
    WorkoutSlot,
    WorkoutWeek,
)


@pytest.mark.asyncio
async def test_approve_sends_pdf_and_does_not_email(monkeypatch):
    from app import bot as bot_module

    week = WorkoutWeek(
        week_number=1,
        days=[
            WorkoutDay(
                day_name="Full Body A",
                slots=[
                    WorkoutSlot(
                        slot_order=1, slot_type="main_compound",
                        exercise_id="back_squat", exercise_name="Back Squat",
                        sets=3, reps="5", rpe=7,
                    )
                ],
                total_fatigue=4,
            )
        ],
    )
    pending = PendingApproval(
        approval_uuid="uuid-1",
        client_id="42",
        client_chat_id=12345,
        client_name="Test Client",
        client_email="ignored@example.com",
        workout_json=week.model_dump_json(),
        coaching_message="# Plan\n\nDo squats.",
    )
    profile = ClientProfile(
        client_id="42", avatar="gen_pop", training_days=3,
        experience_level="beginner", email="ignored@example.com",
        name="Test Client",
    )

    fake_bot = MagicMock()
    fake_bot.send_document = AsyncMock()
    fake_bot.send_message = AsyncMock()

    fake_context = MagicMock()
    fake_context.bot = fake_bot

    fake_query = MagicMock()
    fake_query.edit_message_text = AsyncMock()

    email_called = {"value": False}
    def _email_spy(*args, **kwargs):
        email_called["value"] = True
        return True
    monkeypatch.setattr(
        "app.services.email_service.EmailService.send_plan", _email_spy
    )

    # Stub the DB-touching helpers extracted in Step 3.
    monkeypatch.setattr(bot_module, "_load_pending_and_profile",
                        lambda approval_id: (pending, profile))
    monkeypatch.setattr(bot_module, "_safe_render_pdf",
                        lambda profile, pending: b"%PDF-fake")
    finalise_called = {"value": False}
    def _finalise_spy(pending_arg, _ctx_session=None):
        finalise_called["value"] = True
    monkeypatch.setattr(bot_module, "_atomic_finalise_history", _finalise_spy)

    await bot_module._do_approve_confirmed(fake_query, "uuid-1", fake_context)

    fake_bot.send_document.assert_awaited_once()
    assert fake_bot.send_document.await_args.kwargs["chat_id"] == 12345
    fake_bot.send_message.assert_awaited()  # inline summary
    assert finalise_called["value"] is True
    assert email_called["value"] is False, "email path must not be invoked in bot-only build"
```

- [ ] **Step 2: Run the test, verify it fails**

```bash
pytest tests/test_admin_approve_flow.py -v
```

Expected: FAIL — test references `_load_pending`, `_load_profile`, `_atomic_finalise_history`, `_safe_render_pdf` helpers that don't exist yet (we will extract them in Step 3 to make the function testable), and the current code still calls `EmailService.send_plan`.

- [ ] **Step 3: Extract testable helpers and remove email call**

Open `app/bot.py` at line 2026. Above the existing `_do_approve_confirmed` definition, add these three module-level helpers. They mirror the existing logic exactly — same `session.get` pattern, same raw `pending.workout_json` reuse, same field names. The only behavioural change is removing the email block.

```python
# ── DB helper extraction (added for bot-only refactor) ────────────────────
def _load_pending_and_profile(approval_id: str):
    """Read PendingApproval + its ClientProfile in one session.

    Returns (pending, profile) or (None, None) if either is missing.
    Mirrors the original two `session.get` calls at the top of
    _do_approve_confirmed — no behaviour change.
    """
    with Session(engine) as session:
        pending = session.get(PendingApproval, approval_id)
        if not pending:
            return None, None
        profile = session.get(ClientProfile, pending.client_id)
        return pending, profile


def _safe_render_pdf(profile: ClientProfile, pending: PendingApproval) -> bytes:
    """Render the professional PDF; on failure, fall back to Markdown→PDF.

    Mirrors lines 2044–2063 of the pre-refactor source, including the
    transient-history shape (workout_json passed raw, not re-serialised).
    """
    transient_history = WorkoutHistory(
        client_id=pending.client_id,
        week_number=WorkoutWeek.model_validate_json(pending.workout_json).week_number,
        workout_json=pending.workout_json,
        status="active",
    )
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / "plan.pdf"
            render_plan_pdf(
                client=profile,
                out_path=pdf_path,
                workout_history=transient_history,
                draft_watermark=False,
            )
            return pdf_path.read_bytes()
    except Exception as err:
        logging.warning("Professional PDF render failed (%s), falling back", err)
        return PdfService.generate_pdf(pending.coaching_message)


def _atomic_finalise_history(pending: PendingApproval) -> None:
    """Supersede the old active plan, insert the new one, delete pending.

    Byte-identical to lines 2083–2107 of the original function.
    """
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        for old in session.exec(
            select(WorkoutHistory).where(
                WorkoutHistory.client_id == pending.client_id,
                WorkoutHistory.status == "active",
            )
        ).all():
            old.status = "superseded"
            session.add(old)

        new_history = WorkoutHistory(
            client_id=pending.client_id,
            week_number=WorkoutWeek.model_validate_json(pending.workout_json).week_number,
            workout_json=pending.workout_json,
            status="active",
            plan_started_at=now,
        )
        session.add(new_history)

        stale_pending = session.get(PendingApproval, pending.approval_uuid)
        if stale_pending:
            session.delete(stale_pending)
        session.commit()
```

Then replace the body of `_do_approve_confirmed` (lines 2026–2109) with this version. Note: keep the **exact same signature** as the existing function — `(query, approval_id, context)`.

```python
async def _do_approve_confirmed(query, approval_id: str, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shared approval logic called by both the direct and confirmation-step paths."""
    pending, profile = _load_pending_and_profile(approval_id)
    if pending is None:
        await query.edit_message_text("❌ Plan no longer pending.")
        return
    if profile is None:
        logging.warning("client_not_found: %s", pending.client_id)
        await query.edit_message_text("❌ Client profile not found — cannot approve.")
        return

    client_name = pending.client_name or pending.client_id
    await query.edit_message_text(f"Generating PDF for {client_name}...")

    workout = WorkoutWeek.model_validate_json(pending.workout_json)

    pdf_bytes = _safe_render_pdf(profile, pending)

    await context.bot.send_document(
        chat_id=pending.client_chat_id,
        document=pdf_bytes,
        filename=f"workout_plan_week{workout.week_number}.pdf",
        caption="🎉 Coach Shoaib has approved your plan! Here's your PDF 💪",
    )

    summary = _format_plan_summary(workout)
    if summary:
        try:
            await context.bot.send_message(
                chat_id=pending.client_chat_id,
                text=summary,
                parse_mode="Markdown",
            )
        except Exception as send_err:
            logging.warning("Inline summary send failed (non-fatal): %s", send_err)

    _atomic_finalise_history(pending)

    await query.edit_message_text(f"✅ Approved. PDF sent to {client_name} via Telegram!")
```

`_format_plan_summary` is defined in Task 2. If running this task standalone, drop a stub at the top of the file: `def _format_plan_summary(workout): return ""`.

**Important:** the email block (original lines 2072–2081) is gone. Do NOT keep it.

**Equally important:** preserve every original log message and every original `query.edit_message_text` so admin UX is unchanged.

- [ ] **Step 4: Run the test again, verify it passes**

```bash
pytest tests/test_admin_approve_flow.py -v
```

Expected: PASS. `send_document` called exactly once. `EmailService.send_plan` not called.

- [ ] **Step 5: Commit**

```bash
git add app/bot.py tests/test_admin_approve_flow.py
git commit -m "fix(bot): drop broken email call from approve flow, extract helpers

EmailService.send_plan was being called with kwargs that didn't match its
signature (to_email vs recipient_email, plus a stray week_number). Every
approve raised TypeError that was swallowed. Telegram send_document is the
real delivery channel, so the email path is removed outright. While in
the file, three DB helpers were extracted so the function is now unit
testable without spinning up a real session."
```

### Task 2: Add inline plan summary message after PDF

**Files:**
- Modify: `app/bot.py` (add `_format_plan_summary` near other formatters)
- Test: `tests/test_plan_summary.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_plan_summary.py
from app.bot import _format_plan_summary
from app.models import WorkoutDay, WorkoutSlot, WorkoutWeek


def _slot(name: str, sets: int, reps: str, rpe: int) -> WorkoutSlot:
    return WorkoutSlot(
        slot_order=1, slot_type="main_compound",
        exercise_id=name.lower().replace(" ", "_"),
        exercise_name=name, sets=sets, reps=reps, rpe=rpe,
    )


def test_summary_shows_week_and_day_count():
    week = WorkoutWeek(
        week_number=3,
        days=[
            WorkoutDay(day_name="Push", slots=[_slot("Bench Press", 4, "5", 8)],
                       total_fatigue=4),
            WorkoutDay(day_name="Pull", slots=[_slot("Pendlay Row", 4, "5", 8)],
                       total_fatigue=4),
        ],
    )
    out = _format_plan_summary(week)
    assert "Week 3" in out
    assert "Push" in out and "Pull" in out
    assert "Bench Press" in out
    assert "4×5 @ RPE 8" in out


def test_summary_handles_empty_week():
    week = WorkoutWeek(week_number=1, days=[])
    out = _format_plan_summary(week)
    assert "Week 1" in out
```

- [ ] **Step 2: Run, verify failure**

```bash
pytest tests/test_plan_summary.py -v
```

Expected: FAIL — `ImportError: cannot import name '_format_plan_summary'`.

- [ ] **Step 3: Implement the helper**

Add this function to `app/bot.py` near other plan-formatting helpers (search for `safe_send_markdown` and place above it):

```python
def _format_plan_summary(workout: WorkoutWeek) -> str:
    """Compact text summary of a workout week.

    Sent as a Telegram message alongside the PDF so the client sees the plan
    inline without opening the PDF on a small screen.
    """
    lines = [f"📋 *Week {workout.week_number}* — {len(workout.days)} day(s)"]
    if not workout.days:
        return "\n".join(lines)
    for day in workout.days:
        lines.append("")
        lines.append(f"*{day.day_name}*")
        for slot in day.slots:
            lines.append(
                f"• {slot.exercise_name} — {slot.sets}×{slot.reps} @ RPE {slot.rpe}"
            )
    return "\n".join(lines)
```

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/test_plan_summary.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/bot.py tests/test_plan_summary.py
git commit -m "feat(bot): inline plan summary message after PDF approval"
```

### Task 3: Drop dead `main_lift` literal from check-in filter

**Files:**
- Modify: `app/bot.py:743`
- Test: `tests/test_checkin_filter.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_checkin_filter.py
from app.bot import _select_checkin_slots
from app.models import WorkoutDay, WorkoutSlot, WorkoutWeek


def _mk(slot_type: str, name: str) -> WorkoutSlot:
    return WorkoutSlot(
        slot_order=1, slot_type=slot_type,
        exercise_id=name, exercise_name=name,
        sets=3, reps="5", rpe=8,
    )


def test_only_main_compound_slots_are_collected():
    week = WorkoutWeek(
        week_number=1,
        days=[WorkoutDay(
            day_name="Push",
            slots=[
                _mk("main_compound", "Bench"),
                _mk("secondary_compound", "OHP"),
                _mk("isolation", "Lateral Raise"),
            ],
            total_fatigue=10,
        )],
    )
    chosen = _select_checkin_slots(week)
    assert [s.exercise_name for _, s in chosen] == ["Bench"]
```

- [ ] **Step 2: Verify failure**

```bash
pytest tests/test_checkin_filter.py -v
```

Expected: FAIL — `_select_checkin_slots` does not exist yet.

- [ ] **Step 3: Extract the filter into a tiny pure helper**

In `app/bot.py`, near the top of `start_checkin` (around line 740), extract the comprehension into a helper at module scope and call it from `start_checkin`. Add this helper near other helpers:

```python
def _select_checkin_slots(week: WorkoutWeek) -> list[tuple[str, WorkoutSlot]]:
    """Returns (day_name, slot) tuples for all main_compound slots in the week.

    Was previously inline in start_checkin and accidentally also matched a
    "main_lift" slot_type that the generator never sets. That literal is gone
    so this is now the single source of truth for "what does the client log
    during /checkin".
    """
    return [
        (day.day_name, slot)
        for day in week.days
        for slot in day.slots
        if slot.slot_type == "main_compound"
    ]
```

In `start_checkin`, replace the inline list comprehension at line 738–743 with:

```python
all_main_slots = _select_checkin_slots(week)
```

- [ ] **Step 4: Verify pass**

```bash
pytest tests/test_checkin_filter.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/bot.py tests/test_checkin_filter.py
git commit -m "fix(bot): drop dead 'main_lift' literal from /checkin filter

The generator only ever sets slot_type='main_compound'. The check-in
filter accepted both literals; the second has never matched anything.
Removing it eliminates a confusion trap and makes the filter testable
in isolation."
```

### Task 4: Standardise admin chat ID env var

**Files:**
- Modify: `app/bot.py` (~14 sites — see investigator output)
- Modify: `.env.example`
- Test: `tests/test_admin_id_resolver.py` (new)

- [ ] **Step 1: Write the failing test**

`_admin_chat_id()` reads `os.getenv` on every call, so no `importlib.reload` is needed (and reload would be dangerous: `app.bot` registers Telegram handlers and reads env at import time).

```python
# tests/test_admin_id_resolver.py
from app.bot import _admin_chat_id


def test_admin_chat_id_prefers_admin_chat_id_env(monkeypatch):
    monkeypatch.setenv("ADMIN_CHAT_ID", "1111")
    monkeypatch.setenv("ADMIN_TELEGRAM_ID", "2222")
    assert _admin_chat_id() == 1111


def test_admin_chat_id_falls_back_to_legacy(monkeypatch):
    monkeypatch.delenv("ADMIN_CHAT_ID", raising=False)
    monkeypatch.setenv("ADMIN_TELEGRAM_ID", "3333")
    assert _admin_chat_id() == 3333


def test_admin_chat_id_returns_none_when_unset(monkeypatch):
    monkeypatch.delenv("ADMIN_CHAT_ID", raising=False)
    monkeypatch.delenv("ADMIN_TELEGRAM_ID", raising=False)
    assert _admin_chat_id() is None


def test_admin_chat_id_returns_none_when_non_integer(monkeypatch):
    monkeypatch.setenv("ADMIN_CHAT_ID", "not-a-number")
    monkeypatch.delenv("ADMIN_TELEGRAM_ID", raising=False)
    assert _admin_chat_id() is None
```

- [ ] **Step 2: Verify failure**

```bash
pytest tests/test_admin_id_resolver.py -v
```

Expected: FAIL — helper does not exist.

- [ ] **Step 3: Implement helper and migrate call sites**

Add to `app/bot.py` (near other env-reading helpers, top of file):

```python
def _admin_chat_id() -> int | None:
    """Resolve the admin Telegram chat ID.

    Reads ADMIN_CHAT_ID (current canonical name) first, falls back to the
    legacy ADMIN_TELEGRAM_ID. Returns None if neither is set so callers can
    decide whether to no-op or raise.
    """
    raw = os.getenv("ADMIN_CHAT_ID") or os.getenv("ADMIN_TELEGRAM_ID")
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        logging.error("ADMIN_CHAT_ID must be an integer chat id, got %r", raw)
        return None
```

Then run a search and replace inside `app/bot.py`. Investigator listed 14 sites that read `os.getenv("ADMIN_TELEGRAM_ID")`: lines 338, 376, 1103, 1208, 1321, 1359, 1761, 2299, 2408, 2498, 2711, 2840, 2856, 3039.

For each, replace the immediate read pattern. Two patterns occur:

```python
# Pattern A
chat_id = int(os.getenv("ADMIN_TELEGRAM_ID"))
# becomes:
chat_id = _admin_chat_id()
if chat_id is None:
    logging.warning("ADMIN_CHAT_ID not configured; skipping admin notification")
    return

# Pattern B (no int())
admin = os.getenv("ADMIN_TELEGRAM_ID")
# becomes:
admin = _admin_chat_id()
```

Use `grep -n 'ADMIN_TELEGRAM_ID' app/bot.py` after migration to confirm only the helper itself references the legacy name.

Update `.env.example` — replace the Telegram block with:

```
# Telegram (required)
TELEGRAM_BOT_TOKEN=
ADMIN_CHAT_ID=
# Legacy: ADMIN_TELEGRAM_ID is still honoured if ADMIN_CHAT_ID is unset.
```

- [ ] **Step 4: Verify pass**

```bash
pytest tests/test_admin_id_resolver.py -v
grep -n 'ADMIN_TELEGRAM_ID' app/bot.py
```

Expected: tests PASS. `grep` returns exactly one line — the resolver helper.

- [ ] **Step 5: Commit**

```bash
git add app/bot.py .env.example tests/test_admin_id_resolver.py
git commit -m "refactor(bot): single _admin_chat_id() resolver, prefer ADMIN_CHAT_ID

Settings already exposes admin_chat_id; the bot was reading the legacy
ADMIN_TELEGRAM_ID directly at 14 sites. Centralised the lookup, kept the
legacy var as a fallback for one release cycle."
```

### Task 5: Run full test suite — green-baseline before deploy

- [ ] **Step 1: Run all tests**

```bash
pytest -q --tb=short
```

Expected: all green. If any pre-existing test fails unrelated to this work, capture the output, decide whether to fix it now or open an issue, and document in the commit message.

- [ ] **Step 2: If anything fails — repair**

Read the failure. If it's our regression, fix in the same task. If it's pre-existing, mark with `@pytest.mark.skip(reason="pre-existing, tracked in issue X")` only after confirming with the operator that it isn't a real production blocker.

- [ ] **Step 3: Commit if anything was changed**

```bash
git commit -am "test: green baseline before bot-only deploy"
```

---

## Phase 2 — Compose hardening

### Task 6: Lock down `docker-compose.yml`

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Inspect the current file**

```bash
cat docker-compose.yml
```

- [ ] **Step 2: Replace with hardened version**

Write `docker-compose.yml`:

```yaml
services:
  db:
    image: postgres:16.4-alpine
    restart: unless-stopped
    environment:
      POSTGRES_DB: coaching
      POSTGRES_USER: coaching
      # No default — operator must set POSTGRES_PASSWORD in .env
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set in .env}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U coaching"]
      interval: 5s
      timeout: 5s
      retries: 10
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "5"

  bot:
    build: .
    restart: unless-stopped
    depends_on:
      db:
        condition: service_healthy
    environment:
      DATABASE_URL: postgresql://coaching:${POSTGRES_PASSWORD}@db:5432/coaching
      TELEGRAM_BOT_TOKEN: ${TELEGRAM_BOT_TOKEN:?TELEGRAM_BOT_TOKEN must be set in .env}
      ADMIN_CHAT_ID: ${ADMIN_CHAT_ID:?ADMIN_CHAT_ID must be set in .env}
      OPENROUTER_API_KEY: ${OPENROUTER_API_KEY:?OPENROUTER_API_KEY must be set in .env}
      OPENROUTER_BASE_URL: ${OPENROUTER_BASE_URL:-https://openrouter.ai/api/v1}
      LLM_MODEL_ID: ${LLM_MODEL_ID:-google/gemini-3.1-flash-lite-preview}
      LLM_TEMPERATURE: ${LLM_TEMPERATURE:-0.4}
      AUTH_SECRET_KEY: ${AUTH_SECRET_KEY:-not-used-in-bot-mode}
    volumes:
      - ./prompts:/app/prompts:ro
      - ./logs:/app/logs
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "5"

volumes:
  pgdata:
```

Key changes from previous file:
- Postgres image pinned to `16.4-alpine` (was `16-alpine`)
- `POSTGRES_PASSWORD` is required — `${VAR:?msg}` syntax fails compose if unset
- Same fail-fast for `TELEGRAM_BOT_TOKEN`, `ADMIN_CHAT_ID`, `OPENROUTER_API_KEY`
- All SMTP env vars removed from the bot service
- Log rotation: 10MB × 5 files per container (50MB cap)
- New `./logs` bind mount on the bot for application logs (the bot writes to stdout, but if anyone adds a file handler later this is the path)

- [ ] **Step 3: Validate compose file**

```bash
docker compose config
```

Expected: prints the resolved configuration with no errors when env vars are set, or fails clearly when one is missing.

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml
git commit -m "ops: harden docker-compose for bot-only deploy

- Require POSTGRES_PASSWORD, TELEGRAM_BOT_TOKEN, ADMIN_CHAT_ID,
  OPENROUTER_API_KEY (compose fails fast if any is missing).
- Pin postgres image to 16.4-alpine.
- 10MB x 5 log rotation on both services.
- Drop SMTP env block (bot doesn't email anymore)."
```

### Task 7: Add a deploy bootstrap script

**Files:**
- Create: `scripts/deploy.sh`

- [ ] **Step 1: Write the script**

```bash
#!/usr/bin/env bash
# Bootstrap the bot on a fresh Ubuntu host.
#
# Usage:
#   ./scripts/deploy.sh
#
# Requirements: an .env file in the repo root with all required vars set.
# Will install docker if missing.

set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
    echo "❌ .env not found. Copy .env.example, fill in secrets, then re-run." >&2
    exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
    echo "📦 Installing docker..."
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker "$USER"
    echo "⚠️  You were added to the docker group. Log out and log back in, then re-run."
    exit 0
fi

if ! docker compose version >/dev/null 2>&1; then
    echo "❌ docker compose v2 plugin missing. Install docker-compose-plugin." >&2
    exit 1
fi

chmod 600 .env

echo "🔨 Building images..."
docker compose build

echo "🚀 Starting services..."
docker compose up -d

echo "⏳ Waiting for postgres to report healthy..."
for i in {1..30}; do
    cid=$(docker compose ps -q db || true)
    if [[ -n "$cid" ]]; then
        status=$(docker inspect --format '{{.State.Health.Status}}' "$cid" 2>/dev/null || echo "starting")
        if [[ "$status" == "healthy" ]]; then
            echo "✅ DB healthy."
            break
        fi
    fi
    sleep 2
done

echo "🛠  Running migrations..."
docker compose exec -T bot alembic upgrade head || echo "⚠️  alembic skipped (sqlite or first run)"

echo "📜 Tail logs with:  docker compose logs -f bot"
```

- [ ] **Step 2: Make executable**

```bash
chmod +x scripts/deploy.sh
```

- [ ] **Step 3: Smoke-test locally (dry parse)**

```bash
bash -n scripts/deploy.sh
```

Expected: no syntax errors.

- [ ] **Step 4: Commit**

```bash
git add scripts/deploy.sh
git commit -m "ops: add scripts/deploy.sh — one-shot host bootstrap"
```

### Task 8: Add a health-check script

**Files:**
- Create: `scripts/health_check.sh`

- [ ] **Step 1: Write the script**

```bash
#!/usr/bin/env bash
# Verifies the bot container is up + the db is healthy.
# Uses `docker inspect` (stable across compose minor versions) instead of
# `docker compose ps --format json` which has shifted output shape.
# Returns 0 on healthy, 1 otherwise. Prints status to stdout.

set -uo pipefail

cd "$(dirname "$0")/.."

ok=true

bot_cid=$(docker compose ps -q bot 2>/dev/null || true)
db_cid=$(docker compose ps -q db 2>/dev/null || true)

if [[ -z "$bot_cid" ]]; then
    echo "❌ bot container not found"
    ok=false
else
    bot_state=$(docker inspect --format '{{.State.Status}}' "$bot_cid" 2>/dev/null || echo "missing")
    if [[ "$bot_state" != "running" ]]; then
        echo "❌ bot container state=$bot_state"
        ok=false
    fi
fi

if [[ -z "$db_cid" ]]; then
    echo "❌ db container not found"
    ok=false
else
    db_health=$(docker inspect --format '{{.State.Health.Status}}' "$db_cid" 2>/dev/null || echo "none")
    if [[ "$db_health" != "healthy" ]]; then
        echo "❌ db health=$db_health"
        ok=false
    fi
fi

if $ok; then
    echo "✅ bot stack healthy"
    exit 0
fi
exit 1
```

- [ ] **Step 2: Make executable + dry-parse**

```bash
chmod +x scripts/health_check.sh
bash -n scripts/health_check.sh
```

- [ ] **Step 3: Commit**

```bash
git add scripts/health_check.sh
git commit -m "ops: scripts/health_check.sh for cron / manual ping"
```

---

## Phase 3 — Operator runbook

### Task 9: Write `docs/RUNBOOK_BOT_ONLY.md`

**Files:**
- Create: `docs/RUNBOOK_BOT_ONLY.md`

- [ ] **Step 1: Write the file**

```markdown
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
| `ADMIN_CHAT_ID` | yes | your numeric Telegram user id (msg @userinfobot) |
| `OPENROUTER_API_KEY` | yes | openrouter.ai → Keys |
| `OPENROUTER_BASE_URL` | no | default fine |
| `LLM_MODEL_ID` | no | default `google/gemini-3.1-flash-lite-preview` |
| SMTP* | no | unused in bot-only mode |
| `AUTH_SECRET_KEY` | no | unused in bot-only mode |

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
4. The client chat receives a PDF + an inline summary message
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
gunzip -c backups/<file>.sql.gz | docker compose exec -T db psql -U coaching -d coaching
```

## 6. Common failures

| Symptom | First place to look |
|---|---|
| Bot doesn't reply to /start | `docker compose logs bot` — was the token rejected? |
| Admin doesn't get approval message | `ADMIN_CHAT_ID` correct? Right numeric id, not username? |
| PDF send fails | `docker compose logs bot` — WeasyPrint render errors usually mean missing system libs (already in the Dockerfile, so this should be impossible inside the container) |
| LLM call times out | OpenRouter rate-limited or wrong key — check the `openrouter.ai` dashboard |
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
```

- [ ] **Step 2: Sanity-read it back**

```bash
cat docs/RUNBOOK_BOT_ONLY.md | head -80
```

- [ ] **Step 3: Commit**

```bash
git add docs/RUNBOOK_BOT_ONLY.md
git commit -m "docs: bot-only runbook for 95.111.247.88"
```

---

## Phase 4 — Pre-deploy verification

### Task 10: Local end-to-end dry run with docker compose

- [ ] **Step 1: Set up local `.env`**

Create `.env` in the repo root with real test values:

```
POSTGRES_PASSWORD=<random 32-char>
TELEGRAM_BOT_TOKEN=<from botfather, dedicated test bot>
ADMIN_CHAT_ID=<your telegram id>
OPENROUTER_API_KEY=<your key>
```

```bash
chmod 600 .env
```

- [ ] **Step 2: Build + run locally**

```bash
docker compose build
docker compose up -d
docker compose logs -f bot
```

Expected: no errors. Bot prints "Application started" or equivalent.

- [ ] **Step 3: Run the smoke test from `RUNBOOK_BOT_ONLY.md` §4**

Walk through `/start`, admin approve, PDF + summary delivered, `/checkin`, second week approval. Note any failures.

- [ ] **Step 4: If failures occur, capture and triage**

For each failure, capture:
- The exact bot log line
- The Telegram message you sent that triggered it
- Open a follow-up task in this plan or a separate doc

- [ ] **Step 5: Tear down local stack**

```bash
docker compose down -v
```

(`-v` because the local DB has test data we don't want to keep.)

### Task 11: Deploy to 95.111.247.88

- [ ] **Step 1: SSH in and run bootstrap**

Follow `docs/RUNBOOK_BOT_ONLY.md` §1.

- [ ] **Step 2: Repeat the smoke test against the production bot token**

Note: use a separate `TELEGRAM_BOT_TOKEN` for production, not the local-test one.

- [ ] **Step 3: Set up the cron backup job**

Per `RUNBOOK_BOT_ONLY.md` §5.

- [ ] **Step 4: Set up a basic uptime check**

Crontab on the host:

```
*/5 * * * * /home/ubuntu/beyond_fit_app/scripts/health_check.sh || logger -t beyond_fit "bot stack unhealthy"
```

This dumps unhealthy events to `journalctl -t beyond_fit`, which is enough for now.

- [ ] **Step 5: Final verification**

```bash
./scripts/health_check.sh
docker compose logs --tail 50 bot
```

Expected: ✅ healthy, no error log lines.

---

## Self-review checklist

Before declaring done, verify:

- [ ] All 11 tasks have associated tests OR explicit verification commands.
- [ ] No placeholders (TBD, TODO, "implement later") anywhere in this plan.
- [ ] Function/helper names used in later tasks (`_format_plan_summary`, `_select_checkin_slots`, `_admin_chat_id`, `_load_pending`, `_load_profile`, `_safe_render_pdf`, `_atomic_finalise_history`) are all defined in earlier tasks.
- [ ] Spec coverage: bot-only deploy ✓, hardening ✓, hosting docs ✓, security note about leaked SSH key ✓, smoke test ✓.
- [ ] Email path is removed (Task 1) — confirmed by Task 1 step-3 test.
- [ ] No mobile / REST work creeps in (out of scope for this plan).

## Intentional non-changes (do NOT "clean up")

- **`ASK_EMAIL` state in `/start`** — kept on purpose. We no longer email plans, but the email is still stored on `ClientProfile` as an identifier, used by the REST routes (dormant) and useful to operators who want to reach a client out-of-band. Removing it would require a migration; not worth it.
- **`EmailService` the class** — kept. Other modules (REST `/auth/forgot`, `/auth/register`, coach invites) still import it. Bot just stops calling it.
- **`SMTP_*` env vars in `.env.example`** — kept, marked optional. Same reason.
- **Self-healing super-admin block** in `app/main.py` — irrelevant in bot-only mode but harmless. Leave it.

## Out of scope (do NOT touch in this plan)

- Mobile Flutter app (`mobile/`) — frozen.
- FastAPI service in compose — not added.
- Reverse proxy / Caddy / TLS — not needed; Telegram handles transport.
- New features (nutrition, form-check video review, coach overrides) — already in the bot, not refactoring.
- Splitting `app/bot.py` into multiple modules — tempting but high-risk; defer to a follow-up plan.

## Execution handoff

Plan saved to `docs/superpowers/plans/2026-05-06-bot-only-deploy.md`. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — execute tasks in this session using `superpowers:executing-plans`, batch with checkpoints.

Pick one and we start with Task 1.
