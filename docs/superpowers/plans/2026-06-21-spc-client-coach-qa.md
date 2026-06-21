# SP-C — Client↔Coach Q&A — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a client ask their coach a question (`/ask` or the now-live "❓ Question" button); the question reaches the coach with an LLM-drafted answer + client background; the coach Sends/Edits/Dismisses; the answer is DM'd back to the client.

**Architecture:** A new `ClientQuestion` table (Alembic 0022). A client-side `/ask` ConversationHandler. A coach-side flow whose free-text "Edit & send" state (`QA_COACH_ANSWER`) is folded into the **existing** admin/coach ConversationHandler (so it never collides with the plan-reject `ADMIN_FEEDBACK` state), with the `question_id` carried in `callback_data` → `user_data`. The LLM draft is added to `FlashCommunicationService` and is never auto-sent.

**Tech Stack:** Python 3.12, SQLModel/SQLite, Alembic, python-telegram-bot, pytest. Tests use `tests/conftest.py` (`make_callback_update`, `make_text_update`, `make_context`) + an `AsyncMock` bot and `bot.engine`.

**Spec:** `docs/superpowers/specs/2026-06-21-spc-client-coach-qa-design.md`

---

## File structure

- **Modify** `app/models.py` — new `ClientQuestion` table.
- **Create** `alembic/versions/0022_client_question.py`.
- **Modify** `app/services/llm_service.py` — `draft_qa_answer`.
- **Modify** `app/bot.py` — `/ask` flow + rewire `ack_question`; coach answer handlers; fold `QA_COACH_ANSWER` into the admin ConversationHandler; the coach-DM + client-delivery helpers.
- **Create** tests `tests/test_qa_llm.py`, `tests/test_qa_flow.py`.
- **Modify** `CLAUDE.md`, `CHANGELOG.md`.

**Task order:** 1 (model+migration) → 2 (LLM draft) → 3 (client ask flow) → 4 (coach answer flow) → 5 (docs).

---

## Task 1: `ClientQuestion` model + Alembic 0022

**Files:** Modify `app/models.py`; Create `alembic/versions/0022_client_question.py`; Test `tests/test_qa_flow.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_qa_flow.py
"""SP-C client↔coach Q&A."""
from datetime import datetime, timezone


def test_client_question_model_roundtrips():
    from app.models import ClientQuestion
    from app.bot import engine
    from sqlmodel import Session
    q = ClientQuestion(question_id="q_test1", client_id="cl_x", client_chat_id=111,
                       coach_recipient_id=222, question_text="why squats?",
                       draft_answer="because legs", status="pending",
                       created_at=datetime.now(timezone.utc))
    with Session(engine) as s:
        s.add(q); s.commit()
    with Session(engine) as s:
        got = s.get(ClientQuestion, "q_test1")
    assert got.status == "pending" and got.client_chat_id == 111 and got.final_answer is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_qa_flow.py::test_client_question_model_roundtrips -v`
Expected: FAIL — `ImportError: cannot import name 'ClientQuestion'`.

- [ ] **Step 3: Add the model**

In `app/models.py` (beside the other bot-side tables; `BigInteger`, `Column`, `Optional`,
`datetime`, `Field`, `SQLModel` are already imported), add:

```python
class ClientQuestion(SQLModel, table=True):
    """A one-shot client→coach question with an LLM draft and the coach's answer (SP-C)."""
    question_id: str = Field(primary_key=True)
    client_id: str = Field(index=True)
    client_chat_id: int = Field(sa_column=Column(BigInteger))
    coach_recipient_id: int = Field(sa_column=Column(BigInteger))
    question_text: str
    draft_answer: Optional[str] = Field(default=None)
    final_answer: Optional[str] = Field(default=None)
    status: str = Field(default="pending")   # pending | answered | dismissed
    created_at: datetime
    answered_at: Optional[datetime] = Field(default=None)
```

- [ ] **Step 4: Create the migration**

`alembic/versions/0022_client_question.py`:

```python
"""Add clientquestion table for the client↔coach Q&A channel (SP-C)."""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "clientquestion",
        sa.Column("question_id", sa.String(), primary_key=True),
        sa.Column("client_id", sa.String(), nullable=False, index=True),
        sa.Column("client_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("coach_recipient_id", sa.BigInteger(), nullable=False),
        sa.Column("question_text", sa.String(), nullable=False),
        sa.Column("draft_answer", sa.String(), nullable=True),
        sa.Column("final_answer", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("answered_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("clientquestion")
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_qa_flow.py -v` then `pytest -q`
Expected: PASS / green (SQLite `create_all` picks up the table).

- [ ] **Step 6: Verify the migration chain**

Run: `python -c "from alembic.config import Config; from alembic.script import ScriptDirectory; s=ScriptDirectory.from_config(Config('alembic.ini')); print([r.revision for r in s.walk_revisions()][:3])"`
Expected: `0022` ahead of `0021`.

- [ ] **Step 7: Commit**

```bash
git add app/models.py alembic/versions/0022_client_question.py tests/test_qa_flow.py
git commit -m "feat(models): ClientQuestion table + Alembic 0022 (SP-C)"
```

---

## Task 2: `draft_qa_answer` LLM method

**Files:** Modify `app/services/llm_service.py`; Test `tests/test_qa_llm.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_qa_llm.py
from app.services.llm_service import FlashCommunicationService
from app.models import ClientProfile


class _FakeLLM:
    def __init__(self, reply="Do 3 sets of 10, focus on depth."):
        self.reply = reply
        self.last = None
    def complete(self, system, user, temperature=0.4):
        self.last = (system, user)
        return self.reply


def _client():
    return ClientProfile(client_id="cl_q", avatar="gen_pop", training_days=3,
                         experience_level="beginner", limitations=[], available_equipment=["full_gym"])


def test_draft_qa_answer_uses_profile_and_question():
    fake = _FakeLLM()
    svc = FlashCommunicationService(llm_client=fake)
    out = svc.draft_qa_answer("Why do I squat?", _client(), None)
    assert out == "Do 3 sets of 10, focus on depth."
    # the question + profile reached the LLM; no-plan path is handled
    assert "Why do I squat?" in fake.last[1]
    assert "no active plan" in fake.last[1].lower()


def test_draft_qa_answer_includes_plan_when_present():
    from app.models import WorkoutWeek, WorkoutDay, WorkoutSlot
    fake = _FakeLLM()
    wk = WorkoutWeek(week_number=1, days=[WorkoutDay(day_name="A", total_fatigue=3, slots=[
        WorkoutSlot(slot_order=0, slot_type="main_compound", exercise_id="bb_back_squat_highbar",
                    exercise_name="Barbell Squat", sets=3, reps="5", rpe=7)])])
    FlashCommunicationService(llm_client=fake).draft_qa_answer("form?", _client(), wk)
    assert "Barbell Squat" in fake.last[1]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_qa_llm.py -v`
Expected: FAIL — `AttributeError: ... 'draft_qa_answer'`.

- [ ] **Step 3: Add the method**

In `app/services/llm_service.py`, add to `FlashCommunicationService` (mirrors
`generate_coaching_message`'s retry shape; `time`, `logger` already imported):

```python
    def draft_qa_answer(self, question: str, profile: "ClientProfile",
                        latest_workout: "WorkoutWeek | None") -> str:
        """Draft a RECOMMENDED answer to a client's question, grounded in their profile and
        current plan. This is a DRAFT for the human coach to review — never sent as-is."""
        system_instruction = (
            "You are an elite strength & conditioning coach drafting a SUGGESTED reply to a "
            "client's question, for your head coach to review before it is sent. Ground the "
            "answer in the client's profile and current plan. Be concise (2-5 sentences), "
            "specific, and safe; if the question needs medical or in-person assessment, say so "
            "rather than guessing. Plain text suitable for a messaging app; no preamble."
        )
        plan_section = (latest_workout.model_dump_json(indent=2)
                        if latest_workout is not None else "(no active plan yet)")
        prompt = (
            f"CLIENT PROFILE:\n{profile.model_dump_json(indent=2)}\n\n"
            f"CURRENT PLAN:\n{plan_section}\n\n"
            f"CLIENT QUESTION:\n{question}\n\n"
            "Draft the suggested answer."
        )
        for attempt in range(3):
            try:
                return self._llm.complete(system=system_instruction, user=prompt, temperature=0.4)
            except Exception as e:
                if attempt == 2:
                    raise
                logger.warning("draft_qa_answer LLM call failed (attempt %d/3): %s", attempt + 1, e)
                time.sleep(2 ** attempt)
```

(Add `from app.models import ClientProfile, WorkoutWeek` to the TYPE imports if not present;
they are referenced as forward-ref strings so a top-level import isn't strictly required.)

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_qa_llm.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add app/services/llm_service.py tests/test_qa_llm.py
git commit -m "feat(llm): draft_qa_answer — recommended coach answer from profile + plan (SP-C)"
```

---

## Task 3: Client ask flow (`/ask` + rewire the dead-end button)

**Files:** Modify `app/bot.py`; Test `tests/test_qa_flow.py`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_qa_flow.py
import pytest
from unittest.mock import AsyncMock
from sqlmodel import Session, select
from tests.conftest import make_text_update, make_callback_update, make_context


@pytest.fixture
def mock_bot():
    return AsyncMock()


def _seed_client(cid="cl_ask", coach_id=999, chat_id=4242):
    from app import bot
    from app.models import ClientProfile, ChatBinding, CoachProfile
    with Session(bot.engine) as s:
        s.merge(ClientProfile(client_id=cid, avatar="gen_pop", training_days=3,
                              experience_level="beginner", limitations=[],
                              available_equipment=["full_gym"], assigned_coach_id=coach_id))
        s.merge(CoachProfile(telegram_user_id=coach_id, name="Coach", email="c@x.co",
                             mobile="0", specialty="s", years_experience=1, status="approved"))
        s.merge(ChatBinding(chat_id=chat_id, client_id=cid, is_primary=True))
        s.commit()
    return cid, coach_id, chat_id


@pytest.mark.asyncio
async def test_ask_persists_pending_and_dms_coach(mock_bot, monkeypatch):
    from app import bot
    from app.models import ClientQuestion
    cid, coach_id, chat_id = _seed_client()
    # stub the LLM draft so the test is offline
    monkeypatch.setattr(bot.FlashCommunicationService, "draft_qa_answer",
                        lambda self, q, p, w: "draft text")
    ctx = make_context(mock_bot)
    upd = make_text_update(mock_bot, user_id=chat_id, text="Why do I squat low-bar?")
    nxt = await bot.handle_qa_question(upd, ctx)
    with Session(bot.engine) as s:
        rows = s.exec(select(ClientQuestion).where(ClientQuestion.client_id == cid)).all()
    assert len(rows) == 1 and rows[0].status == "pending"
    assert rows[0].coach_recipient_id == coach_id and rows[0].draft_answer == "draft text"
    # coach was DM'd (message routed to the coach's telegram id)
    sent_targets = [c.kwargs.get("chat_id") for c in mock_bot.send_message.call_args_list]
    assert coach_id in sent_targets
    assert nxt == bot.ConversationHandler.END


@pytest.mark.asyncio
async def test_ask_cap_refuses_fourth_pending(mock_bot, monkeypatch):
    from app import bot
    from app.models import ClientQuestion
    cid, coach_id, chat_id = _seed_client(cid="cl_cap", chat_id=4343)
    from datetime import datetime, timezone
    with Session(bot.engine) as s:
        for i in range(3):
            s.add(ClientQuestion(question_id=f"q{i}", client_id=cid, client_chat_id=chat_id,
                                 coach_recipient_id=coach_id, question_text="x", status="pending",
                                 created_at=datetime.now(timezone.utc)))
        s.commit()
    ctx = make_context(mock_bot)
    nxt = await bot.handle_qa_question(make_text_update(mock_bot, user_id=chat_id, text="one more?"), ctx)
    with Session(bot.engine) as s:
        n = len(s.exec(select(ClientQuestion).where(ClientQuestion.client_id == cid)).all())
    assert n == 3  # not inserted
    assert nxt == bot.ConversationHandler.END
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_qa_flow.py -k ask -v`
Expected: FAIL — `AttributeError: ... 'handle_qa_question'`.

- [ ] **Step 3: Add the state const + handlers + the coach-DM helper**

In `app/bot.py`, add a state const near the other string states:

```python
ASK_QA_QUESTION = "ASK_QA_QUESTION"
QA_COACH_ANSWER = "QA_COACH_ANSWER"
_QA_MAX_PENDING = 3
_QA_MAX_LEN = 1000
```

Add the handlers + helper (place near `handle_plan_ack`):

```python
def _qa_coach_keyboard(qid: str, has_draft: bool) -> InlineKeyboardMarkup:
    rows = []
    if has_draft:
        rows.append([InlineKeyboardButton("✅ Send draft", callback_data=f"qa_send:{qid}")])
    rows.append([InlineKeyboardButton("✏️ Edit & send", callback_data=f"qa_edit:{qid}")])
    rows.append([InlineKeyboardButton("❌ Dismiss", callback_data=f"qa_dismiss:{qid}")])
    return InlineKeyboardMarkup(rows)


async def _dm_coach_question(bot, q) -> None:
    """Send the coach the question + client background + the DRAFT, with action buttons."""
    summary = _build_client_summary(q.client_id)
    draft = q.draft_answer or "[draft unavailable — please answer manually]"
    text = (
        f"💬 *New question from your client*\n\n{summary}\n\n"
        f"*Their question:*\n{q.question_text}\n\n"
        f"*Suggested draft — ⚠️ DRAFT, review before sending:*\n{draft}"
    )
    await safe_send_markdown(bot, q.coach_recipient_id, text,
                             reply_markup=_qa_coach_keyboard(q.question_id, bool(q.draft_answer)))


@auth_roles.requires_active_sub
async def start_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    """Entry for /ask AND the rewired 'Question' button."""
    if update.callback_query is not None:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("What's your question for your coach? (one message)")
    else:
        await update.message.reply_text("What's your question for your coach? (one message)")
    return ASK_QA_QUESTION


# IMPLEMENTER NOTE: `start_ask` is an entry point for BOTH /ask (a message update) and the
# ack_question button (a callback_query update). Verify `@auth_roles.requires_active_sub`
# handles a callback_query update (it must reply via the callback / effective_message, not
# update.message which is None for a callback). If the decorator only supports message updates,
# drop the decorator from start_ask and instead gate at the top of handle_qa_question (which
# already resolves the client) with the equivalent active-sub check. Confirm against
# app/auth/roles.py:235 before wiring.


async def handle_qa_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import uuid
    from datetime import datetime, timezone
    from app.models import ClientQuestion, ClientProfile, WorkoutHistory, WorkoutWeek
    chat_id = update.effective_chat.id
    client = auth_roles.get_authenticated_client(chat_id)
    if client is None:
        await update.message.reply_text("Your chat isn't linked. Tap /start to log in.")
        return ConversationHandler.END
    cid = client.client_id

    with Session(engine) as session:
        pending = session.exec(
            select(ClientQuestion).where(ClientQuestion.client_id == cid,
                                         ClientQuestion.status == "pending")
        ).all()
    if len(pending) >= _QA_MAX_PENDING:
        await update.message.reply_text(
            f"You have {_QA_MAX_PENDING} questions awaiting your coach — please wait for a reply "
            "before asking more.")
        return ConversationHandler.END

    question_text = (update.message.text or "").strip()[:_QA_MAX_LEN]
    if not question_text:
        await update.message.reply_text("Please type your question.")
        return ASK_QA_QUESTION

    coach_id = _resolve_review_recipient(cid)
    if coach_id is None:
        await update.message.reply_text("No coach is available right now — please try again later.")
        return ConversationHandler.END

    # latest active plan (optional)
    latest = None
    with Session(engine) as session:
        hist = session.exec(
            select(WorkoutHistory).where(WorkoutHistory.client_id == cid,
                                         WorkoutHistory.status == "active")
            .order_by(WorkoutHistory.week_number.desc())
        ).first()
    if hist is not None:
        try:
            latest = WorkoutWeek.model_validate_json(hist.workout_json)
        except Exception:
            latest = None

    draft = None
    try:
        draft = FlashCommunicationService().draft_qa_answer(question_text, client, latest)
    except Exception:
        logging.exception("draft_qa_answer failed client_id=%s", cid)

    q = ClientQuestion(question_id=f"q_{uuid.uuid4().hex[:12]}", client_id=cid, client_chat_id=chat_id,
                       coach_recipient_id=coach_id, question_text=question_text, draft_answer=draft,
                       status="pending", created_at=datetime.now(timezone.utc))
    with Session(engine) as session:
        session.add(q); session.commit()

    await _dm_coach_question(context.bot, q)
    await update.message.reply_text("✅ Sent to your coach — they'll reply here.")
    return ConversationHandler.END
```

- [ ] **Step 4: Rewire `ack_question` + register the `/ask` ConversationHandler**

(a) The existing dead-end branch in `handle_plan_ack` for `ack_question` is now replaced by the
ConversationHandler entry — change the stateless registration so `handle_plan_ack` only handles
the non-question acks. Find `app.add_handler(CallbackQueryHandler(handle_plan_ack, pattern=r"^ack_"))`
(~`bot.py:5920`) and change the pattern to:

```python
    app.add_handler(CallbackQueryHandler(handle_plan_ack, pattern=r"^ack_(good|ok)$"))
```

(b) Register the client Q&A ConversationHandler (near the other client ConversationHandlers,
e.g. after the check-in handler):

```python
    app.add_handler(ConversationHandler(
        entry_points=[
            CommandHandler("ask", start_ask),
            CallbackQueryHandler(start_ask, pattern=r"^ack_question$"),
        ],
        states={ASK_QA_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_qa_question)]},
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
    ))
```

(`handle_plan_ack`'s internal `if query.data == "ack_question"` branch is now dead — leave it or
remove it; the `^ack_(good|ok)$` pattern means it never receives `ack_question` anymore.)

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_qa_flow.py -k ask -v` then `pytest -q`
Expected: PASS / green.

- [ ] **Step 6: Commit**

```bash
git add app/bot.py tests/test_qa_flow.py
git commit -m "feat(bot): /ask client question flow + rewire dead-end Question button; routes to coach with LLM draft (SP-C)"
```

---

## Task 4: Coach answer flow (Send / Edit / Dismiss) + client delivery

**Files:** Modify `app/bot.py`; Test `tests/test_qa_flow.py`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_qa_flow.py
def _seed_question(qid="q_ans", cid="cl_ans", coach_id=999, chat_id=5252, draft="draft A", status="pending"):
    from app import bot
    from app.models import ClientProfile, ChatBinding, CoachProfile, ClientQuestion
    from datetime import datetime, timezone
    with Session(bot.engine) as s:
        s.merge(ClientProfile(client_id=cid, avatar="gen_pop", training_days=3,
                              experience_level="beginner", limitations=[], available_equipment=["full_gym"],
                              assigned_coach_id=coach_id))
        s.merge(CoachProfile(telegram_user_id=coach_id, name="C", email="c@x.co", mobile="0",
                             specialty="s", years_experience=1, status="approved"))
        s.merge(ChatBinding(chat_id=chat_id, client_id=cid, is_primary=True))
        s.merge(ClientQuestion(question_id=qid, client_id=cid, client_chat_id=chat_id,
                               coach_recipient_id=coach_id, question_text="q?", draft_answer=draft,
                               status=status, created_at=datetime.now(timezone.utc)))
        s.commit()
    return qid, cid, coach_id, chat_id


@pytest.mark.asyncio
async def test_qa_send_delivers_draft_to_client(mock_bot):
    from app import bot
    from app.models import ClientQuestion
    qid, cid, coach_id, chat_id = _seed_question()
    ctx = make_context(mock_bot)
    await bot.handle_qa_send(make_callback_update(mock_bot, user_id=coach_id, data=f"qa_send:{qid}"), ctx)
    with Session(bot.engine) as s:
        q = s.get(ClientQuestion, qid)
    assert q.status == "answered" and q.final_answer == "draft A"
    targets = [c.kwargs.get("chat_id") for c in mock_bot.send_message.call_args_list]
    assert chat_id in targets  # client got the answer


@pytest.mark.asyncio
async def test_qa_edit_then_typed_answer_binds_to_question(mock_bot):
    from app import bot
    from app.models import ClientQuestion
    qid, cid, coach_id, chat_id = _seed_question(qid="q_edit", cid="cl_edit", chat_id=5353)
    ctx = make_context(mock_bot)
    st = await bot.handle_qa_edit(make_callback_update(mock_bot, user_id=coach_id, data=f"qa_edit:{qid}"), ctx)
    assert st == bot.QA_COACH_ANSWER and ctx.user_data["qa_question_id"] == qid
    await bot.handle_qa_coach_answer(make_text_update(mock_bot, user_id=coach_id, text="My real answer."), ctx)
    with Session(bot.engine) as s:
        q = s.get(ClientQuestion, qid)
    assert q.status == "answered" and q.final_answer == "My real answer."


@pytest.mark.asyncio
async def test_qa_dismiss_notifies_client(mock_bot):
    from app import bot
    from app.models import ClientQuestion
    qid, cid, coach_id, chat_id = _seed_question(qid="q_dis", cid="cl_dis", chat_id=5454)
    ctx = make_context(mock_bot)
    await bot.handle_qa_dismiss(make_callback_update(mock_bot, user_id=coach_id, data=f"qa_dismiss:{qid}"), ctx)
    with Session(bot.engine) as s:
        q = s.get(ClientQuestion, qid)
    assert q.status == "dismissed"
    targets = [c.kwargs.get("chat_id") for c in mock_bot.send_message.call_args_list]
    assert chat_id in targets  # client still hears back
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_qa_flow.py -k "qa_send or qa_edit or qa_dismiss" -v`
Expected: FAIL — `AttributeError: ... 'handle_qa_send'`.

- [ ] **Step 3: Add the delivery helper + the three coach handlers**

```python
async def _deliver_qa_answer(bot, q, text: str) -> bool:
    """DM the client their coach's answer (or dismissal note). Returns False if unreachable."""
    chat_id = auth_roles.resolve_primary_chat_id(q.client_id)
    if chat_id is None:
        return False
    await bot.send_message(chat_id=chat_id, text=text)
    return True


def _load_question_for_coach(qid: str, coach_user_id: int):
    """Load a ClientQuestion if the coach may act on its client; else None + reason."""
    with Session(engine, expire_on_commit=False) as session:
        q = session.get(ClientQuestion, qid)
    if q is None:
        return None, "❌ Question no longer exists."
    if not _user_can_act_on_client(coach_user_id, q.client_id):
        return None, "🔒 Not authorized for this client."
    if q.status != "pending":
        return None, "Already handled."
    return q, None


async def _finalise_qa(q, final_answer: str, deliver_text: str, status: str, context) -> None:
    from datetime import datetime, timezone
    with Session(engine) as session:
        row = session.get(ClientQuestion, q.question_id)
        row.final_answer = final_answer
        row.status = status
        row.answered_at = datetime.now(timezone.utc)
        session.add(row); session.commit()
    delivered = await _deliver_qa_answer(context.bot, q, deliver_text)
    if not delivered:
        await context.bot.send_message(chat_id=q.coach_recipient_id,
                                       text="⚠️ Couldn't deliver — the client has no linked chat.")


async def handle_qa_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    qid = query.data.split(":", 1)[1]
    q, err = _load_question_for_coach(qid, update.effective_user.id)
    if q is None:
        await query.edit_message_text(err); return
    if not q.draft_answer:
        await query.answer("No draft — use ✏️ Edit & send.", show_alert=True); return
    await _finalise_qa(q, q.draft_answer, f"💬 Your coach replied:\n\n{q.draft_answer}", "answered", context)
    await query.edit_message_text("✅ Sent to the client.")


async def handle_qa_dismiss(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    qid = query.data.split(":", 1)[1]
    q, err = _load_question_for_coach(qid, update.effective_user.id)
    if q is None:
        await query.edit_message_text(err); return
    await _finalise_qa(q, None,
                       "💬 Your coach reviewed your question — no further action needed. Ask anytime with /ask.",
                       "dismissed", context)
    await query.edit_message_text("Dismissed (client notified).")


async def handle_qa_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    qid = query.data.split(":", 1)[1]
    q, err = _load_question_for_coach(qid, update.effective_user.id)
    if q is None:
        await query.edit_message_text(err)
        return ConversationHandler.END
    context.user_data["qa_question_id"] = qid
    await query.edit_message_text("Type your answer to send to the client:")
    return QA_COACH_ANSWER


async def handle_qa_coach_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    qid = context.user_data.pop("qa_question_id", None)
    answer = (update.message.text or "").strip()
    if not qid:
        await update.message.reply_text("Lost track of the question — please tap Edit again.")
        return ConversationHandler.END
    q, err = _load_question_for_coach(qid, update.effective_user.id)
    if q is None:
        await update.message.reply_text(err)
        return ConversationHandler.END
    await _finalise_qa(q, answer, f"💬 Your coach replied:\n\n{answer}", "answered", context)
    await update.message.reply_text("✅ Sent to the client.")
    return ConversationHandler.END
```

- [ ] **Step 4: Register the coach handlers (fold Edit into the existing admin handler)**

(a) Add `qa_send` / `qa_dismiss` as standalone callbacks near the ack registration:

```python
    app.add_handler(CallbackQueryHandler(handle_qa_send, pattern=r"^qa_send:"))
    app.add_handler(CallbackQueryHandler(handle_qa_dismiss, pattern=r"^qa_dismiss:"))
```

(b) Fold the free-text `qa_edit` → `QA_COACH_ANSWER` into the **existing** admin/coach
ConversationHandler (the one at ~`bot.py:5796` with `reject:`/`ADMIN_FEEDBACK`). Add `qa_edit`
to its `entry_points` and `QA_COACH_ANSWER` to its `states`:

```python
    app.add_handler(ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handle_admin_reject, pattern=r"^reject:"),
            CallbackQueryHandler(handle_fc_edit, pattern=r"^fc_edit_"),
            CallbackQueryHandler(handle_qa_edit, pattern=r"^qa_edit:"),
        ],
        states={
            ADMIN_FEEDBACK: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_feedback)],
            FORMCHECK_TIPS_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_fc_tip_edit)],
            QA_COACH_ANSWER: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_qa_coach_answer)],
        },
        fallbacks=[CommandHandler("cancel", cancel_admin)],
        per_message=False,
    ))
```

(This is the existing block — add the two new lines, don't create a second handler. A coach is
therefore only ever in ONE free-text-capture state, so a Q&A answer and a plan-reject edit can't
cross-route; `qa_question_id` in `user_data` binds the typed answer to its question even with
multiple pending.)

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_qa_flow.py -v` then `pytest -q`
Expected: PASS / green.

- [ ] **Step 6: Commit**

```bash
git add app/bot.py tests/test_qa_flow.py
git commit -m "feat(bot): coach Q&A answer flow — Send/Edit/Dismiss, delivered to client; Edit folded into admin handler (SP-C)"
```

---

## Task 5: Docs (CLAUDE.md + CHANGELOG)

**Files:** Modify `CLAUDE.md`, `CHANGELOG.md`.

- [ ] **Step 1: Update CLAUDE.md**

Add a bullet under "Key design constraints":

```markdown
- Clients can ask their coach a question (SP-C): `/ask` or the (now-live) plan "❓ Question"
  button → `ClientQuestion` row → `FlashCommunicationService.draft_qa_answer` drafts a
  recommended answer + `_build_client_summary` background → DM'd to the assigned coach
  (super-admin fallback via `_resolve_review_recipient`) with **Send draft / Edit & send /
  Dismiss**. The coach's free-text "Edit & send" state (`QA_COACH_ANSWER`) lives **inside the
  existing admin/coach ConversationHandler** (not a parallel one) so it never collides with the
  plan-reject `ADMIN_FEEDBACK` state; the `question_id` rides in `callback_data`. The answer
  (or a dismissal note — the client always hears back) is DM'd via `resolve_primary_chat_id`.
  Max 3 pending questions/client; the LLM draft is never auto-sent. Alembic 0022. See
  `docs/superpowers/specs/2026-06-21-spc-client-coach-qa-design.md`.
```

- [ ] **Step 2: Update CHANGELOG.md**

Add at the top:

```markdown
## [1.6.0] — 2026-06-21 — SP-C: client↔coach Q&A

### Added
- Clients can ask their coach a question (`/ask` or the now-live plan "❓ Question" button);
  routed to the coach with an LLM-drafted answer + client background; coach Sends / Edits /
  Dismisses; the answer is DM'd back. New `ClientQuestion` table (Alembic 0022). Max 3 pending
  questions/client; the LLM draft is always coach-reviewed, never auto-sent.
```

- [ ] **Step 3: Run the full suite**

Run: `pytest -q`
Expected: green.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md CHANGELOG.md
git commit -m "docs: record SP-C client↔coach Q&A (1.6.0)"
```

---

## Definition of done

- `/ask` and the "❓ Question" button both let a client ask; the question persists `pending`,
  routes to the assigned coach (super-admin fallback) with an LLM draft + background.
- The 3-pending cap refuses a 4th; a no-coach client still reaches the super-admin.
- Coach **Send draft** delivers the draft; **Edit & send** delivers the typed answer bound to
  the right question (no collision with plan-reject); **Dismiss** notifies the client.
- Answer/dismissal DM'd via `resolve_primary_chat_id`; unreachable client handled gracefully.
- Alembic 0022 applies; `pytest -q` green.
- **Deploy note:** run `docker compose run --rm bot alembic upgrade head` on the server after
  deploying (0021 → 0022).
```
