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
