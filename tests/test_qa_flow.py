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
