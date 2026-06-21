# Design: SP-C — Client↔Coach Q&A (one-shot, LLM-drafted)

**Date:** 2026-06-21
**Branch base:** `fix/audit-hardening`
**Status:** Approved design — pending implementation plan

Third of four sub-projects (SP-A, SP-B1 shipped). SP-D (pre-payment pitch) is last.

## Problem (feedback this slice closes)

**#3 — the client felt disconnected.** After receiving a plan, a client who wants to ask
about an exercise or anything else **has no way to reach the coach**. The only affordance —
the "❓ Question" button on the 24h plan-acknowledgment prompt (`handle_plan_ack`,
`ack_question`, `bot.py:5362`) — is a **dead end**: it edits the message to *"Feel free to ask
your question anytime — your coach will reply here,"* a promise with no routing, no coach
notification, no reply path. SP-C makes that promise real.

The client's question must reach the coach **with an LLM-drafted recommended answer + the
client's background**, so the coach can decide quickly (HITL — the draft is never auto-sent).

## Goals

- A client can ask their coach a question (via `/ask` **and** the now-live "❓ Question"
  button); the question is routed to the assigned coach (super-admin fallback) with an
  LLM-drafted answer + a client-background summary.
- The coach **Send draft / Edit & send / Dismiss**; the answer is DM'd back to the client.
- The client always hears back — no question vanishes silently.

## Non-goals (deferred)

- Multi-turn threads / live chat (one-shot Q→A; a follow-up is a new `/ask`).
- Exercise picker (free-text; the coach gets the full current plan as background).
- Attachments / images. Auto-sending the LLM draft (always coach-reviewed).

---

## Architecture overview

```
client side (new ConversationHandler)
  /ask  ──┐
  "❓ Question" (ack_question, rewired) ──┴─> ASK_QA_QUESTION -> store ClientQuestion
        -> draft_qa_answer() -> DM the coach -> ack the client

coach side (FOLD INTO the EXISTING admin/coach ConversationHandler — do NOT build a parallel one)
  qa_send:<qid>     (standalone callback)  -> final = draft  -> deliver -> answered
  qa_dismiss:<qid>  (standalone callback)  -> dismissed      -> brief client note
  qa_edit:<qid>     (entry into QA_COACH_ANSWER state) -> coach types -> deliver -> answered

delivery: resolve_primary_chat_id(client_id) -> bot.send_message
```

The coach-answer free-text capture (`QA_COACH_ANSWER`) lives in the **same**
ConversationHandler as the plan-reject `ADMIN_FEEDBACK` state, and the question is bound by
**`question_id` carried in `callback_data` → `user_data`** (like `reject_uuid`). See C3.

---

## C1 — Client ask flow

- **Entry points (both into one flow):** a new `CommandHandler("ask", start_ask)` **and** the
  rewired `ack_question` button. Today `ack_question` is a stateless
  `CallbackQueryHandler(handle_plan_ack, "^ack_")`; it must become an **`entry_points`** of the
  Q&A `ConversationHandler` (route it to `start_ask`). The other `ack_*` buttons
  (`ack_good`/`ack_ok`) stay stateless.
- **Guard:** `@requires_active_sub` — **not** `@requires_assigned_coach`. (The guard-vs-fallback
  contradiction: requiring an assigned coach would block a no-coach client from asking — the
  exact disconnection #3 is about. Any paying client may ask; routing handles the no-coach case.)
- **Flow:** `start_ask` → "What's your question for your coach? (one message)" → state
  `ASK_QA_QUESTION` → `handle_qa_question(text)`:
  1. Enforce the **pending cap** (C5): if the client already has 3 `pending` questions →
     "You have 3 questions awaiting your coach — please wait for a reply before asking more."
     and END.
  2. Enforce a **length cap** (e.g. 1000 chars; truncate or re-ask if absurd).
  3. Resolve the recipient via `_resolve_review_recipient(client_id)` (assigned coach, else
     super-admin). Resolve the asking `chat_id` (`update.effective_chat.id`).
  4. Build the LLM draft (C2) + the background summary.
  5. Persist a `ClientQuestion` (C5) with `status="pending"`, `coach_recipient_id`,
     `client_chat_id`, `question_text`, `draft_answer`.
  6. DM the coach (C3). Ack the client: "✅ Sent to your coach — they'll reply here." END.

## C2 — LLM draft + background

- New `FlashCommunicationService.draft_qa_answer(question: str, profile: ClientProfile,
  latest_workout: "WorkoutWeek | None") -> str` — same shape as `generate_coaching_message`
  (system prompt + `_llm` call, `google/gemini-2.5-flash`). Drafts a concise, grounded
  *recommended* answer using the client's profile (avatar, experience, limitations, equipment,
  `exercise_ability`, e1RMs) + their current plan exercises.
- **No plan yet:** if the client has no `active` `WorkoutHistory`, pass `latest_workout=None`;
  the draft works from the profile alone (don't crash).
- **LLM down / error:** `draft_qa_answer` failure is caught — the coach still receives the
  question + background, with the draft slot reading *"[draft unavailable — please answer
  manually]"*. The flow never blocks on the LLM.
- **Never auto-sent.** The draft is a starting point for the human coach.

## C3 — Coach DM + answer flow (consolidated handler)

**Coach DM** (sent to `coach_recipient_id` via `safe_send_markdown`):
```
💬 Question from <client name>

<client background summary — reuse _build_client_summary(client_id)>

Their question:
<question_text>

Suggested draft — ⚠️ DRAFT, review before sending:
<draft_answer or "[draft unavailable — please answer manually]">
```
with inline keyboard:
`[✅ Send draft → qa_send:<qid>] [✏️ Edit & send → qa_edit:<qid>] [❌ Dismiss → qa_dismiss:<qid>]`.

The **`⚠️ DRAFT, review before sending`** label is mandatory so the coach does not rubber-stamp
a possibly-wrong LLM answer.

**Handlers (no parallel ConversationHandler — avoid the free-text collision):**
- `qa_send:<qid>` — **standalone** `CallbackQueryHandler` (no free text): load the
  `ClientQuestion`, set `final_answer = draft_answer`, `status="answered"`, deliver to the
  client (C4). Edits the coach message to "✅ Sent."
- `qa_dismiss:<qid>` — **standalone** `CallbackQueryHandler`: `status="dismissed"`, deliver the
  client a brief note (C4). Edits to "Dismissed."
- `qa_edit:<qid>` — added as an **entry point of the EXISTING admin/coach `ConversationHandler`**
  (the one already holding `reject:` → `ADMIN_FEEDBACK`). It stashes
  `context.user_data["qa_question_id"] = qid` (exactly like `reject_uuid`) and prompts "Type
  your answer:", returning a **new `QA_COACH_ANSWER` state** registered in that same handler.
  `handle_qa_coach_answer(text)` reads `qa_question_id` from `user_data`, sets
  `final_answer = text`, `status="answered"`, delivers (C4). Because the coach is only ever in
  **one** free-text-capture conversation, a coach who is mid-plan-reject and a Q&A answer never
  cross-route; the `question_id` in `user_data` disambiguates among multiple pending questions.

## C4 — Answer delivery to the client

`resolve_primary_chat_id(client_id)` → `bot.send_message(chat_id, ...)`:
- **Answered:** "💬 Your coach replied to your question:\n\n<final_answer>"
- **Dismissed:** "💬 Your coach reviewed your question — no further action needed. Ask anytime
  with /ask." (so a dismiss never leaves the client in silence — re-creating #3).
- **Client unreachable** (no `ChatBinding`): don't crash; tell the coach "⚠️ couldn't deliver —
  the client has no linked chat," leave the question `answered` (answer is stored).

## C5 — Data model + rate cap

New table **`ClientQuestion`** (mirrors the existing JSON/SQLModel table style):
```python
class ClientQuestion(SQLModel, table=True):
    question_id: str = Field(primary_key=True)          # uuid
    client_id: str = Field(index=True)
    client_chat_id: int = Field(sa_column=Column(BigInteger))   # the chat that asked
    coach_recipient_id: int = Field(sa_column=Column(BigInteger))  # telegram id at ask time
    question_text: str
    draft_answer: Optional[str] = None
    final_answer: Optional[str] = None
    status: str = "pending"                              # pending | answered | dismissed
    created_at: datetime
    answered_at: Optional[datetime] = None
```
**Alembic 0022** (`revision="0022"`, `down_revision="0021"`) creates it.

**Rate cap:** max **3** `pending` questions per `client_id` (queried before insert in C1).
**Staleness is intentional:** `coach_recipient_id` + `client_chat_id` are captured at **ask
time** — for a one-shot Q→A, whoever was notified answers; do not re-resolve at answer time.

## Error handling / edge cases

- No assigned coach → `_resolve_review_recipient` returns the super-admin → full flow works.
- LLM draft fails → coach answers manually (draft slot shows the fallback text).
- Pending cap hit → friendly refusal, no insert.
- Client has no plan yet → draft from profile only.
- Client has no chat binding at answer time → coach told; answer stored.
- Sub expires / coach removed after asking → the stored `coach_recipient_id` still answers; the
  client still receives the reply (delivery is by chat_id, independent of sub state).

## Testing (TDD)

- **C1:** `/ask` and `ack_question` both enter `ASK_QA_QUESTION`; a question persists a
  `pending` `ClientQuestion` routed to `_resolve_review_recipient`; the 3-pending cap refuses a
  4th; a no-coach client routes to super-admin; the client gets the ack.
- **C2:** `draft_qa_answer` returns a string from profile+plan; no-plan path doesn't crash; an
  LLM error yields the manual-answer fallback (coach still notified).
- **C3:** `qa_send` sets `final_answer=draft` + `answered` + delivers; `qa_edit` → typed answer
  becomes `final_answer` bound to the right `question_id` even with 2 pending questions; the
  `QA_COACH_ANSWER` state does not consume a plan-reject `ADMIN_FEEDBACK` message and vice
  versa; `qa_dismiss` marks dismissed + notifies the client.
- **C4:** answered/dismissed both deliver to `resolve_primary_chat_id`; unreachable client is
  handled gracefully.
- **C5:** migration 0022 up/down; the table round-trips.

---

## Appendix — Verified surfaces (file:line, from the SP-C exploration)

- Dead-end button: `handle_plan_ack` / `ack_question` `bot.py:5362-5373`; registered
  `CallbackQueryHandler(handle_plan_ack, "^ack_")` `bot.py:5920`.
- Coach routing: `_resolve_review_recipient(client_id)` `bot.py:78-98`.
- Reusable coach free-text template: `handle_admin_reject` (`bot.py:4468`) →
  `ADMIN_FEEDBACK` (=100, `bot.py:195`) → `handle_admin_feedback` (`bot.py:4501`); the admin/coach
  ConversationHandler registration `bot.py:5796-5807`.
- Client delivery: `auth_roles.resolve_primary_chat_id(client_id)` `roles.py:105-119`.
- LLM service: `FlashCommunicationService` `llm_service.py:15`; `generate_coaching_message`
  `:36`, `apply_coach_edits` `:85`; model `google/gemini-2.5-flash`.
- Latest plan: `select(WorkoutHistory).where(client_id, status=="active").order_by(week_number.desc())`
  `bot.py:4613`; `WorkoutHistory` `models.py:161`.
- Background summary helper: `_build_client_summary(client_id)`.
- Guard: `@requires_active_sub` `roles.py:235`.
- Latest migration **0021** → new **0022**.
