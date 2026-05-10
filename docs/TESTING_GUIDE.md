# Beyond Fit — Manual Testing Guide

Bot-only deployment on `95.111.247.88`. Bot username: `@beyond_x_fit_bot`. Super-admin Telegram ID: `1314558685` (Omar). Test client account used during initial verification: `876071788`.

This doc tells you, for every user-facing flow:
1. **Flow** — what the code does step by step
2. **Expect** — what you should see in Telegram
3. **Test** — exact taps/messages to send
4. **Watch** — what fails most often + where to look
5. **DB tables touched** — so you can verify state with SQL when something is unclear

Scroll to the section you want. Each is independent.

> **🆕 SaaS refactor (Phases A–H)** — `/start` now opens a pre-payment menu. Service commands (`/checkin`, `/diet`, `/plan`, `/log`) are gated on (a) chat bound to a client account, (b) active subscription, (c) assigned coach. New flows: Subscribe → screenshot → super-admin verify → access code; coach application via bot with CV; coach picker; daily renewal reminders; multi-device login via access code. Search "Phase" in this doc for the new sections.

---

## 0a. Phase A–H quick test plan (run in this order)

1. **Pre-payment menu** — `/start` from a fresh chat → expect 4-button menu (Subscribe / Ask question / I have account / I want to coach).
2. **FAQ** — tap "Ask a question" → ask 1–2 things → expect LLM reply. 6th question in an hour → blocked.
3. **Subscribe + verify** — Subscribe → pick 1m → see EGP 1500 + Instapay text → upload any photo → super-admin gets DM with verify/reject → tap ✅ → client receives `BF-XXXX-XXXX-XXXX` code + "Pick your coach" menu.
4. **Coach apply** — from a different chat, "I want to coach" → fill 8-step questionnaire → super-admin gets bundle + CV → tap ✅ Approve.
5. **Coach pick** — back in client chat, tap "Pick a coach" → buttons list approved coaches → tap one → "Assigned to X" → "Begin setup" button.
6. **Begin setup** → goes into avatar/days/experience/limitations/email flow (existing intake) → workout plan generates → DM goes to **assigned coach** (not super-admin).
7. **Multi-device login** — from a third chat, `/start` → "I have an account" → paste code → bound; `/plan` shows the client's plan.
8. **/checkin gate** — log out (drop ChatBinding) and try `/checkin` → "isn't linked" message. Expire sub manually and `/checkin` → "expired" message. Clear `assigned_coach_id` and `/checkin` → "Pick a coach" message.
9. **Renewal reminders** — set a sub's `ends_at` to `now + 7d 1h`, run the job manually, check DM + `reminderlog` row.
10. **Coach scope** — as a coach (not super-admin), `/review` shows only your assigned clients' plans; `/override <other_client>` returns "🔒 Not your client."

---

## 0b. Paid SaaS flow — detailed

### Subscribe path

**Flow:** `/start` → menu → "💳 Subscribe" → state `SUBSCRIBE_PICK_PLAN` (buttons 1m/3m) → state `SUBSCRIBE_AWAIT_SCREENSHOT` → photo handler stores `Payment(status="pending")` → DM super-admin with photo + `pay_verify:<id>` / `pay_reject:<id>` buttons.

**Verify (super-admin tap):** inserts `Subscription` (30 or 90 days), `AccessCode` (`BF-XXXX-XXXX-XXXX`, 17-char Crockford), primary `ChatBinding`, marks `Payment.status="verified"`, DMs client with code + coach picker. Client clicks coach → `ClientProfile.assigned_coach_id` set → "Begin setup" button → re-enters the legacy avatar/days/.../email intake using the new `client_id` (`cl_<token>`), not `str(tg_user_id)`.

**Reject (super-admin tap):** super-admin types reason → `Payment.status="rejected"`, `rejection_reason` stored, client DM'd.

**DB tables:** `payment`, `subscription`, `accesscode`, `chatbinding`, `clientprofile`.

**Watch:**
- Photo upload fails silently → check `bot.send_photo` logs (line ~610). `photo[-1].file_id` extraction.
- Verify works but no DM → super-admin id misconfigured. Check `SUPER_ADMIN_TELEGRAM_USER_ID` env.
- Two clients submit a payment at the same time → both `Payment` rows insert; verify both work independently because `payment.id` is autoincrement.

### Login by access code

**Flow:** `/start` from a new chat → "🔑 I have an account" → type code → `find_client_by_access_code` lookup → `bind_chat` inserts ChatBinding(is_primary=False). Already-bound chat to a different client → "blocked" reply, logs `chat_rebind_attempt`.

**DB:** `chatbinding`.

### FAQ Q&A

**Flow:** "❓ Ask a question" → `FAQ_LOOP` state → message goes through `FlashCommunicationService._llm.complete` with a fixed system prompt about service/pricing/Instapay/refunds. Rate-limit module-level dict caps at `FAQ_RATE_LIMIT_PER_HOUR` (default 5) per chat.

**Watch:** LLM unreachable → bot replies "Sorry, I can't reach the assistant…". Logs `faq_llm_call` per call.

### Coach application

**Flow:** "🧑‍🏫 I want to coach" → 8-state conversation (name → email → mobile → specialty buttons → years → certs → CV PDF or `/skip` → portfolio or `/skip`) → inserts `CoachProfile(status="pending")` → DMs super-admin bundle + forwards CV. Approve/reject buttons `coach_verify:<tg_id>` / `coach_reject:<tg_id>`. Re-entry guard: existing pending/approved/rejected application blocks re-apply with a status-specific message.

**DB:** `coachprofile`.

### Coach picker

**Flow:** after pay_verify, client gets DM with 3 buttons (Pick / Let admin choose / *Change* shown if already assigned). Pick → list of `CoachProfile WHERE status='approved'` → tap → writes `ClientProfile.assigned_coach_id`. "Let admin pick" → DMs super-admin "needs assignment" with one button per approved coach → super-admin tap fires `admin_assign:<client_id>:<coach_id>` → writes the FK + DMs client.

**Cross-chat hijack guard:** `cp_pick` re-checks `ChatBinding` so only the bound owner can pick for that `client_id`. Other chats see "This coach picker isn't yours."

### Daily renewal jobs (Phase F)

- **09:00 UTC** `send_renewal_reminders`: DMs clients whose `subscription.ends_at` is in the d-7 / d-3 / d-1 window. Idempotent via `reminderlog UNIQUE(subscription_id, kind)`.
- **00:05 UTC** `expire_subscriptions`: flips `status='active' → 'expired'` for past `ends_at` + DMs the client.

**Verify manually:**
```sql
-- mock a sub ending in ~7.5 days
UPDATE subscription SET ends_at = now() + interval '7 days 1 hour' WHERE id=<sub_id>;
```
Then run the job from a Python REPL inside the bot container:
```python
import asyncio
from app.bot import send_renewal_reminders
from types import SimpleNamespace
# (use the actual app.bot instance, or a stub: SimpleNamespace(bot=<app.bot>))
```

### Subscription + coach gate (Phase G)

Decorators `@requires_active_sub` and `@requires_assigned_coach` (in `app/auth/roles.py`) wrap the service entry-points. Failure messages:
- Unbound chat → "Your chat isn't linked to an account yet. Tap /start."
- Expired sub → "⛔ Your subscription has expired. Tap /start → Subscribe to renew."
- No coach assigned → "👀 Pick a coach first with /pick_coach."

Whitelisted commands (still work pre-binding): `/start`, `/help`, `/cancel`. Callbacks always pass.

### Role-aware /help (Phase H)

- Anyone → "Client commands" section.
- Approved coach (and not super-admin) → adds "Coach commands" section.
- Super-admin → adds "Super-admin commands" section. (Coach section suppressed for super-admin since they see everything.)

### Coach scope on /review, /override (Phase H)

- Super-admin: `/review` and `/review_batch` show all pending; silent-client list spans every client.
- Coach: shows only clients with `assigned_coach_id == coach.telegram_user_id`.
- `/override <other_coaches_client>`: "🔒 You don't have access to that client (not assigned to you)."
- Form-check video reply: super-admin can reply to any video; coach can reply only to videos from their assigned clients.

### Plan-DM routing (Phase H fix)

When a plan is ready for approval, the bot DMs the **assigned coach** (via `_resolve_review_recipient(client_id)`), not the super-admin. Unassigned clients fall back to super-admin so plans never go unreviewed.

### Schema diff (migration 0017)

New tables: `coachprofile`, `payment`, `subscription`, `accesscode`, `chatbinding`, `reminderlog`. New `clientprofile` columns: `assigned_coach_id (BIGINT)`, `created_at`. Legacy `is_coach`/`is_admin`/`coach_id` kept on `clientprofile` for FastAPI back-compat. Migration also wipes all client-derived rows — apply only when you're ready to start fresh.

```sql
-- inspect a fresh signup
SELECT * FROM payment ORDER BY id DESC LIMIT 3;
SELECT * FROM subscription ORDER BY id DESC LIMIT 3;
SELECT * FROM accesscode;
SELECT * FROM chatbinding;
SELECT telegram_user_id, name, status FROM coachprofile;
```

---

## 0. How to read logs and DB state

```bash
# tail bot logs
ssh -i /tmp/bf_deploy/key root@95.111.247.88 \
  'cd /root/beyond_fit_app && docker compose logs -f bot'

# tail db logs
ssh -i /tmp/bf_deploy/key root@95.111.247.88 \
  'cd /root/beyond_fit_app && docker compose logs -f db'

# open psql against the running db
ssh -i /tmp/bf_deploy/key root@95.111.247.88 \
  'cd /root/beyond_fit_app && docker compose exec db psql -U coaching -d coaching'
```

Useful one-liner queries (run inside psql):

```sql
-- everything about a client
SELECT * FROM clientprofile WHERE client_id='876071788';
SELECT history_id, week_number, status, plan_started_at FROM workouthistory
  WHERE client_id='876071788' ORDER BY history_id DESC;
SELECT approval_uuid, client_id FROM pendingapproval;
SELECT id, client_id, reason, created_at FROM profilesnapshot
  WHERE client_id='876071788' ORDER BY id DESC LIMIT 5;
SELECT id, client_id, raw_text, needs_coach_review, created_at FROM checkin
  WHERE client_id='876071788' ORDER BY id DESC LIMIT 5;

-- nuke a client to start fresh (use with care)
DELETE FROM checkin           WHERE client_id='876071788';
DELETE FROM workouthistory    WHERE client_id='876071788';
DELETE FROM pendingapproval   WHERE client_id='876071788';
DELETE FROM profilesnapshot   WHERE client_id='876071788';
DELETE FROM rejectionfeedback WHERE client_id='876071788';
DELETE FROM clientprofile     WHERE client_id='876071788';
```

---

## 1. Onboarding — `/start`

### Flow

1. Client sends `/start`.
2. `start_conversation` (`app/bot.py:423`) checks if `ClientProfile` exists.
   - If profile + `WorkoutHistory` rows exist → "Welcome back! You're on Week N. Type /checkin." → END.
   - If profile exists but no history → wipes profile + child rows (snapshot + pending) and continues.
3. 5 inline-keyboard / text questions: avatar → days → experience → limitations → email.
4. After email step, `run_generation_and_dispatch` runs:
   - `WorkoutGenerator.generate(client)` produces a `WorkoutWeek`.
   - `FlashCommunicationService.generate_coaching_message` (LLM via OpenRouter) formats it as Markdown.
   - Inserts a `PendingApproval` row.
   - DMs the admin chat (`ADMIN_CHAT_ID`) with the formatted plan + ✅/❌ buttons.
5. Client sees "⏳ Building your custom protocol... Coach Shoaib will review it shortly!"

### Expect

- 5 questions arrive in sequence; each accepts taps or text.
- After email, "Building your custom protocol..." appears within 1s.
- Admin chat receives a long message + two buttons ~5–15s later (LLM round-trip).
- DB state: `clientprofile` + `profilesnapshot` + `pendingapproval` rows for that `client_id`.

### Test

In Telegram on the client account:
1. `/start`.
2. Tap "General Fitness" (or any).
3. Tap "3" days.
4. Tap "beginner".
5. Tap "None" for limitations.
6. Type any email.

### Watch

| Symptom | Likely cause | Where to look |
|---|---|---|
| Bot silent on `/start` | Crashed handler | `docker compose logs bot` for traceback |
| "Oops! Something went wrong: Chat not found" | Admin (`ADMIN_CHAT_ID`) hasn't DMed the bot yet | Make admin send any message to bot first |
| Email rejected | Invalid format | Bot validates with `re`; check error msg |
| Stuck at "Building..." with no admin notification | LLM timeout or OpenRouter outage | `docker compose logs bot \| grep openrouter` |
| Profile partially saved, /start re-run errors | FK violation between snapshot and clientprofile | Already fixed (commit `3617a1a`); confirm code on server matches |

### DB tables touched
`clientprofile`, `profilesnapshot`, `pendingapproval`.

---

## 2. Admin approval — ✅ Approve

### Flow

1. Admin taps ✅ on the approval message.
2. `handle_admin_approve` (`bot.py:1978`) — if the plan has 2+ edits OR was generated <3 days ago, shows a confirmation step. Otherwise calls `_do_approve_confirmed` directly.
3. `_do_approve_confirmed` (`bot.py:2146`):
   - Loads `PendingApproval` + `ClientProfile`.
   - Renders the professional PDF via `app.adapters.pdf.renderer.render_plan_pdf` → falls back to `PdfService.generate_pdf(coaching_message)` if WeasyPrint fails.
   - `context.bot.send_document(chat_id=client_chat_id, document=pdf_bytes, ...)`.
   - `context.bot.send_message(chat_id=client_chat_id, text=_format_plan_summary(workout), parse_mode="Markdown")`.
   - Atomic transaction: marks any active `workouthistory` row as `superseded`, inserts a new `active` row with `plan_started_at=now`, deletes the `pendingapproval` row.
4. Admin chat: button row replaced with "✅ Approved. PDF sent to {name} via Telegram!".

### Expect

Client account receives within 2–5s:
- A PDF file `workout_plan_week{N}.pdf`.
- A separate Markdown message: `📋 Week N — N day(s)` + per-day exercise lines `• Bench Press — 4×5 @ RPE 8`.

### Test

Admin chat → tap ✅ Approve.

### Watch

| Symptom | Likely cause | Action |
|---|---|---|
| Button does nothing | Double-click 400 "Message is not modified" | Already swallowed (commit `c20f0d1`); look for *other* errors in logs |
| PDF render error `'super' object has no attribute 'transform'` | weasyprint vs pydyf version mismatch | Already pinned (commit `9d04a0e`); verify with `docker compose exec bot pip show pydyf` shows `0.10.x` |
| Admin sees "Approved" but client gets nothing | `client_chat_id` wrong in `pendingapproval` | Check `SELECT client_chat_id FROM pendingapproval` before approve |
| Markdown summary fails to send | Markdown entity error | Wrapped in try/except; warning logged, PDF still sent |

### DB tables touched
`pendingapproval` (deleted), `workouthistory` (insert active + supersede previous active).

---

## 3. Admin reject + LLM edit loop — ❌ Reject

### Flow

1. Admin taps ❌ Reject.
2. `handle_admin_reject` (`bot.py:2120`) saves `reject_uuid` in user_data, replies "Type your requested changes…", returns `ADMIN_FEEDBACK` state.
3. Admin types feedback like "swap squats for leg press".
4. `handle_admin_feedback`:
   - Calls `FlashCommunicationService.apply_coach_edits(workout_json, feedback)` — LLM mutates the JSON.
   - Validates the mutated JSON deserialises back into a `WorkoutWeek`.
   - Re-runs `generate_coaching_message` for the new plan.
   - Updates the `pendingapproval` row's `workout_json`, `coaching_message`, appends to `edit_log`.
   - Re-presents the approval message with new content + same ✅/❌ buttons.

### Expect

- Bot replies "Re-presenting plan with your edits…" or similar.
- New approval message appears, slightly different.
- `edit_log` JSON column on `pendingapproval` grows by one entry.

### Test

1. From admin, tap ❌.
2. Type free-text: e.g. `swap back squat for front squat`.
3. Wait ~10s for LLM.
4. New approval appears.
5. Tap ✅ to actually deliver.

### Watch

| Symptom | Cause |
|---|---|
| LLM returns invalid JSON | Some edits trip the prompt; the bot logs + tells you to retry |
| Same plan returned | Edit was vague; try more specific wording |
| 500-style error | OpenRouter down or wrong key |

### DB tables touched
`pendingapproval` (updated, NOT deleted until ✅ Approve).

---

## 4. Check-in — `/checkin`

### Flow

1. Client sends `/checkin`.
2. `start_checkin` (`bot.py:705`):
   - Loads the client's `active` `WorkoutHistory` row.
   - `_select_checkin_slots(week)` returns all `slot_type='main_compound'` slots.
   - Skips slots already logged (`slot.actual_rpe is not None`).
   - Per-slot loop: asks weight (`CHECKIN_EX_WEIGHT`), then RPE (`CHECKIN_EX_RPE`), optional pain (`CHECKIN_EX_PAIN`), optional sets-cut flag (`CHECKIN_EX_SETS`).
   - Final "any notes? or /skip" prompt.
3. `_process_checkin`:
   - Mutates the `workout_json` in the latest history row, filling `actual_weight`/`actual_rpe` per slot.
   - Calls `FlashCommunicationService.extract_checkin(raw_text)` (LLM) for any free-text notes → structured progress signals.
   - Persists a `CheckIn` row.
   - Increments `client.week_number`.
   - Calls `run_generation_and_dispatch` with `prior_workout` = the just-completed history → autoregulator kicks in.
4. New `pendingapproval` lands in admin chat for the next week.

### What the autoregulator does

`AutoRegulator.calculate_next_load(last_weight, last_target_rpe, last_actual_rpe, next_target_rpe)` (`app/generator.py:30`):

```
rpe_error = last_actual_rpe - last_target_rpe
if rpe_error > 0:                     # too easy
    corrected = last_weight - (rpe_error * 0.04 * last_weight)
else:                                 # too hard
    corrected = last_weight + (abs(rpe_error) * 0.04 * last_weight)
target_jump = next_target_rpe - last_target_rpe
next_target = corrected + (target_jump * 0.025 * corrected)
return round(next_target / 2.5) * 2.5  # snap to 2.5 kg increment
```

So if Week 1 said RPE 7, target 100 kg, you logged actual 9 (too hard), Week 2 starts ~92 kg.

### Expect

- Bot iterates each main lift one by one.
- Final "All done! Generating Week 2..."
- Admin chat: new approval msg.
- After approval, client's Week 2 PDF: same exercises in main compound slots, **different `target_weight`** computed from the rule above.

### Test

After Week 1 PDF is delivered:
1. Client → `/checkin`.
2. Reply with weights + RPEs. Mix of high/low to see autoregulator behaviour:
   - For one lift, log `target_weight - 5` and RPE `8` (too hard) → expect Week 2 lower.
   - For another, log `target_weight + 5` and RPE `6` (too easy) → expect Week 2 higher.
3. /skip the final notes.
4. Approve Week 2 in admin chat.
5. Compare Week 1 vs Week 2 PDFs side by side.

### Watch

| Symptom | Cause |
|---|---|
| `/checkin` says "no active plan" | `workouthistory.status` not `active`; check DB |
| Loop skips a lift | `slot.actual_rpe` already set (re-running checkin); manually `UPDATE` to clear |
| Week 2 weights identical to Week 1 | Autoregulator reads zero telemetry; check that `_process_checkin` actually wrote to `workout_json` |
| Crash on free-text notes | LLM extraction failed; should fall back to raw text without crashing (silent fallback at `bot.py:1115` — known caveat) |

### DB tables touched
`workouthistory` (existing row mutated + new row inserted), `checkin`, `pendingapproval`, `clientprofile.week_number`.

---

## 5. View current plan — `/plan`

### Flow

`client_plan` shows today's session by default, full week with `plan_full_week` button.

### Expect
Markdown message with day name, exercise lines, sets×reps, target weight if set, coaching cues.

### Test
`/plan` → view today. Then tap "Show full week" if shown.

### Watch
- Empty plan = no `active` history. Onboard first.

---

## 6. Manual log — `/log`

### Flow

`start_log` (`bot.py:2998`) — pick day → pick exercise → enter weight → enter RPE. Edits one slot in the active workout's JSON, no week increment. Useful when you missed a day or want to fix a typo.

### Expect
Confirmation: "Logged: Bench Press @ 100 kg, RPE 8".

### Test
1. `/log`.
2. Tap day.
3. Tap exercise.
4. Type weight.
5. Type RPE.

### Watch
- Slot lookup fails if exercise was rotated out — re-run `/plan` to confirm exercise is still in the week.

### DB tables touched
`workouthistory.workout_json` mutated. `setlog` may also be inserted (real-time per-set logger).

---

## 7. Coach exercise substitution — `/override`

### Flow

Admin only. Two forms:

- `/override <client_id> <from_exercise_id> <to_exercise_id>` — add or replace a substitution rule. Stored in `clientprofile.coach_overrides` JSON map.
- `/override <client_id>` — list current overrides + offer a "Remove" inline button per entry.

The generator's `_apply_override` (`generator.py:254`) reads the map at exercise-selection time and substitutes. Effect is permanent until removed.

### Expect

- After setting an override, the next generated week shows the replacement.
- Admin gets confirmation message listing overrides.

### Test

Admin → `/override 876071788 back_squat front_squat` → approve next week → check PDF.

### Watch
- Exercise IDs must exist in `app/exercise_db.py`. Misspell = silent no-op (override stored but never matches).

### DB tables touched
`clientprofile.coach_overrides`.

---

## 8. Pending plan list — `/review`, `/review_batch`

### Flow

- `/review` — admin gets a numbered list of every `pendingapproval` row, each with an "Open" inline button. Tap → re-renders the approval message for that uuid.
- `/review_batch` — same data grouped by training pattern (push/pull/legs). Useful when you have many pending plans.

### Test
1. Stack 2–3 pending plans (from different test accounts).
2. Admin → `/review`. List should show both.
3. Tap one → approve flow continues.

---

## 9. Diet / Nutrition — `/diet`

### Flow

`start_diet` (`bot.py:1433`) — 18-question intake captured into `nutritionprofile`:

1. weight kg
2. height cm
3. age
4. sex (M/F)
5. body fat % (optional, type `skip`)
6. goal (fat_loss / lean_bulk / bulk / recomp / maintain)
7. aggressiveness (conservative / moderate / aggressive)
8. activity level
9. target rate %/wk
10. diet style (omnivore / vegetarian / vegan / pescatarian / keto)
11. allergies (csv text)
12. dislikes (csv text)
13. religious restrictions (csv)
14. meals/day (1–6)
15. cooking skill (1–4)
16. cooking time (min)
17. budget tier (1–3)
18. medical conditions (csv text)

Then `NutritionService.build_plan(profile)` calculates targets (Mifflin-St Jeor + activity multiplier + goal adjustment), generates a `NutritionPlan` row in `draft` status, and posts a separate approval message to admin with `nutrapprove:` / `nutrdiscard:` buttons.

Admin approve → plan moves to `approved`/`active`, client receives… **(unverified — needs testing)** likely a Markdown message + possibly a PDF.

`/diet quick` — skips biometrics, uses safe defaults, jumps to step 6.

### Expect

- 18 prompts, ~2 minutes.
- Admin gets nutrition approval message.
- Approve → client sees calorie + macro targets.

### Test

1. Client → `/diet quick` (faster).
2. Walk through goals + prefs.
3. Admin gets nutrition approval.
4. Tap approve.
5. Verify client receives plan.

### Watch

- No feature flag enforced on the bot side (`feature_nutrition_enabled` exists in settings but is read nowhere — `/diet` works regardless of `.env`).
- LLM-generated meal-plan content depends on prompt quality. Inspect `prompts/` directory if outputs look off.
- The "approved → client gets plan" path was added late and hasn't been smoke-tested in this deploy. Likely sends `plan_markdown` as a chat message; PDF generation may or may not trigger. Verify and tell me what actually arrives.

### DB tables touched
`nutritionprofile`, `nutritionplan`.

---

## 10. PDF style + content — what to test

The PDF is what the client opens daily. Two render paths:

- **Primary**: `app/adapters/pdf/renderer.py::render_plan_pdf` — Jinja2 template + WeasyPrint. Produces a polished multi-page document.
- **Fallback**: `app/services/pdf_service.py::PdfService.generate_pdf(markdown_str)` — `markdown2` → HTML → WeasyPrint. Plain looking. Triggered when primary throws.

### Inspect the templates locally

```bash
ls app/adapters/pdf/
ls app/templates/        # if exists
ls prompts/              # LLM prompts, separate
```

The HTML template + CSS that drive the PDF live under `app/adapters/pdf/`. Open them in a browser to preview without the full PDF round-trip.

### Render a PDF outside of Telegram (fast iteration)

```python
# scripts/render_test_pdf.py — one-shot dev script you can write
from app.adapters.pdf.renderer import render_plan_pdf
from app.models import ClientProfile, WorkoutHistory
from sqlmodel import Session, select
from app.database import engine

with Session(engine) as s:
    client = s.exec(select(ClientProfile).where(ClientProfile.client_id == "876071788")).first()
    hist   = s.exec(select(WorkoutHistory).where(
        WorkoutHistory.client_id == client.client_id,
        WorkoutHistory.status == "active",
    )).first()
render_plan_pdf(client=client, out_path="/tmp/preview.pdf", workout_history=hist, draft_watermark=True)
```

Run inside the bot container:
```bash
ssh -i /tmp/bf_deploy/key root@95.111.247.88 \
  'cd /root/beyond_fit_app && docker compose exec bot python scripts/render_test_pdf.py && docker compose cp bot:/tmp/preview.pdf -' > /tmp/preview.pdf
```

(Adjust path and rsync back to your laptop.)

### What to verify in the PDF

| Aspect | What good looks like | Red flag |
|---|---|---|
| Header | Client name, week number, generation date | Empty / "None" |
| Day sections | Day name, total fatigue, exercise table | Missing days, wrong order |
| Per-exercise rows | Sets × reps, target weight, RPE, rest, tempo, cues | Cells missing, broken table layout |
| Warmup ramp | Top set + 3–5 warmup percentages | Only working set shown for compound lifts |
| Typography | Consistent fonts, no overflow, readable on mobile | Text clipped, body font too tiny |
| Page breaks | Each day starts on its own page (or clean break) | Day cut mid-table |
| Watermark | Approved PDF has none. Draft preview has "DRAFT". | Approved doc shows DRAFT (= bug) |

### Iterate on style

1. Edit the template/CSS under `app/adapters/pdf/`.
2. Re-run the local render script.
3. When happy, `git add` + `git commit` + `rsync` + `docker compose restart bot`.

### Watch

- WeasyPrint silently drops unsupported CSS (no flexbox in some versions, no grid).
- Custom fonts need to be packaged in the image or hosted; otherwise WeasyPrint falls back to default.
- Right-to-left or non-Latin scripts may need `lang="ar"` + a font with Arabic glyphs.

---

## 11. Edge cases worth running once

### Safety refusal
1. Re-onboard a fresh test account.
2. Answer "yes" to cardiac history with `<24` weeks ago.
3. Bot refuses with reason from `HARD_REFUSE_CONDITIONS` (`app/domain/workout/constants.py`). Admin gets a "Clear safety gate" inline button.
4. Tap it → safety gate skipped, plan generates.

### Deload week (week 5)
1. After Week 4's check-in or by manually setting `clientprofile.week_number=5`.
2. Generate. Bot logs `deload_week: RPE=6 trigger=week_5_cycle`.
3. Volume budget × deload_factor (default 0.6), RPE capped at 6, all `target_weight` × 0.6 rounded to 2.5 kg.
4. PDF should clearly look lighter and shorter.

### Restart resilience
1. During a multi-step flow (e.g. mid-`/start`), `docker compose restart bot`.
2. Re-send next message. Bot has lost the in-memory conversation state.
3. **Known limitation**: PTB's `ConversationHandler` keeps state in memory; restart drops it. The user has to `/cancel` and start over. Fix would be `PicklePersistence` or a Redis backend — not done.

---

## 12. Things that are still half-built / known gaps

These are not test cases. They are limitations to know about so you don't waste time chasing them.

- `EmailService` exists and other modules import it (legacy / dormant FastAPI routes). The bot never calls it. SMTP env vars are unused; safe to leave blank.
- `FEATURE_NUTRITION_ENABLED` setting is read nowhere — `/diet` runs regardless.
- Restart loses in-flight conversations (above).
- Concurrency: two clients can have different sessions fine. Two admins approving the *same* `pendingapproval` would race; second one hits "Plan no longer pending."
- Logs rotate at 10 MB × 5 files; no remote log shipping.
- No backup cron yet — set up per `RUNBOOK_BOT_ONLY.md` §5.
- Mobile app + REST API: dormant. Not exposed by the running compose.

---

## 13. When something breaks — debug recipe

1. **Read the bot log first.** 90% of the time the traceback is right there.
   ```
   docker compose logs --tail 100 bot
   ```
2. **Check container state.**
   ```
   docker compose ps
   ./scripts/health_check.sh
   ```
3. **Verify DB state for the affected client.** Use the queries in §0.
4. **Reproduce the action manually with `curl` against the Telegram API** if you suspect a Telegram-side issue:
   ```
   curl "https://api.telegram.org/bot<TOKEN>/getMe"
   curl "https://api.telegram.org/bot<TOKEN>/sendMessage?chat_id=<ID>&text=ping"
   ```
5. **If the bot is stuck in a crash loop**, restart it:
   ```
   docker compose restart bot
   ```
6. **If migrations are out of sync** (rare):
   ```
   docker compose exec bot alembic current
   docker compose exec bot alembic upgrade head
   ```
7. **Last resort — wipe the test client and start over.** SQL block in §0.

---

## 14. Improvement backlog (suggested, in roughly priority order)

1. **Persistent conversation state.** PTB `PicklePersistence` or Redis backend. Survives restarts.
2. **Per-set logger UI.** Bot already has `setlog` table, but no `/log_set` interaction wired up.
3. **`/checkin` resume.** If user disconnects mid-loop, resume from last logged slot. Partial implementation already exists (`_persist_checkin_progress`).
4. **PDF template polish.** Brand consistency, mobile-friendly font sizes, page-break tuning.
5. **Backup cron** + S3 upload of nightly dumps.
6. **Sentry / structured logging** end-to-end (already wired in `app/main.py`, not active in bot process).
7. **Nutrition PDF.** Confirm the approve path actually sends one; if not, add it.
8. **Foreign-key cascades.** Make `profilesnapshot.client_id` FK use `ON DELETE CASCADE` so we don't have to delete rows manually in code.
9. **Rate limit per chat.** A user spamming `/start` 50× will queue 50 LLM calls.
10. **Admin web dashboard.** Eventually the FastAPI routes already exist; surface them at a private URL.
