# tests/test_qa_flow.py
"""SP-C client↔coach Q&A."""
from datetime import datetime, timezone

# Module-level import so SQLModel.metadata is populated (clientquestion + the seed models)
# before the autouse test-engine fixture calls create_all — required for isolated runs.
from app import bot  # noqa: F401
from app.models import ClientQuestion, ClientProfile, ChatBinding, CoachProfile  # noqa: F401


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
                             mobile="0", specialty="s", years_experience=1, certifications="none",
                             status="approved"))
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


def _seed_question(qid="q_ans", cid="cl_ans", coach_id=999, chat_id=5252, draft="draft A", status="pending"):
    from app import bot
    from app.models import ClientProfile, ChatBinding, CoachProfile, ClientQuestion
    from datetime import datetime, timezone
    with Session(bot.engine) as s:
        s.merge(ClientProfile(client_id=cid, avatar="gen_pop", training_days=3,
                              experience_level="beginner", limitations=[], available_equipment=["full_gym"],
                              assigned_coach_id=coach_id))
        s.merge(CoachProfile(telegram_user_id=coach_id, name="C", email="c@x.co", mobile="0",
                             specialty="s", years_experience=1, certifications="none", status="approved"))
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
