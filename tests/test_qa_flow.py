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
