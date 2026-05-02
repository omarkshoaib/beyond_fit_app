"""
Phase 2 tests: CheckInExtraction schema + auto-regulation rule table.
These are unit tests — no LLM calls, no DB.
"""
import pytest
from app.domain.checkin.schema import CheckInExtraction, PainFlag, ExerciseFeedback
from app.domain.workout.autoregulation import derive_plan_delta, apply_delta, PlanDelta
from app.models import ClientProfile, WorkoutWeek
from app.generator import WorkoutGenerator


# ── Fixtures ───────────────────────────────────────────────────────

@pytest.fixture
def base_plan() -> WorkoutWeek:
    client = ClientProfile(
        client_id="ck_base",
        avatar="powerbuilder",
        training_days=4,
        experience_level="intermediate",
        limitations=[],
        available_equipment=["full_gym"],
        week_number=1,
    )
    return WorkoutGenerator().generate(client)


# ── Extraction schema ──────────────────────────────────────────────

def test_extraction_all_nulls():
    """Minimal vague check-in should parse without errors."""
    data = CheckInExtraction.model_validate({
        "overall_fatigue": None,
        "exercises": [],
        "pain_flags": [],
        "soreness": [],
        "personal_records": [],
        "clarifying_questions_for_client": [],
    })
    assert data.needs_coach_review is False


def test_extraction_needs_coach_review_pain():
    """Moderate/severe pain must trigger needs_coach_review."""
    extraction = CheckInExtraction(
        pain_flags=[PainFlag(body_part="right_shoulder", severity="severe", is_new=True)],
    )
    extraction.derive_coach_review_flag()
    assert extraction.needs_coach_review is True


def test_extraction_new_pain_triggers_review():
    """Any new pain, even mild, must trigger needs_coach_review."""
    extraction = CheckInExtraction(
        pain_flags=[PainFlag(body_part="knee", severity="mild", is_new=True)],
    )
    extraction.derive_coach_review_flag()
    assert extraction.needs_coach_review is True


def test_extraction_no_pain_no_review():
    extraction = CheckInExtraction(
        overall_fatigue=6,
        sessions_completed=4,
        sessions_planned=4,
    )
    extraction.derive_coach_review_flag()
    assert extraction.needs_coach_review is False


def test_extraction_clarifying_questions_capped():
    """clarifying_questions_for_client must not exceed 3 items."""
    with pytest.raises(Exception):
        CheckInExtraction(
            clarifying_questions_for_client=[
                "Q1", "Q2", "Q3", "Q4"  # 4 exceeds max_length=3
            ]
        )


# ── Auto-regulation rules ──────────────────────────────────────────

def test_autoreg_no_change_on_empty_extraction(base_plan):
    extraction = CheckInExtraction()
    delta = derive_plan_delta(extraction, base_plan)
    assert delta.is_empty()


def test_autoreg_pain_moderate_triggers_adjustment(base_plan):
    """Moderate pain on a named exercise should produce a slot adjustment."""
    # Find the main lift exercise name
    main_slot = base_plan.days[0].slots[0]
    extraction = CheckInExtraction(
        pain_flags=[PainFlag(
            body_part="lower_back",
            severity="moderate",
            is_new=False,
            aggravated_by=main_slot.exercise_name,
        )],
    )
    delta = derive_plan_delta(extraction, base_plan)
    assert any(a.exercise_id == main_slot.exercise_id for a in delta.slot_adjustments)
    assert any("coach review" in n for n in delta.notes)


def test_autoreg_high_fatigue_plus_poor_sleep_triggers_deload(base_plan):
    extraction = CheckInExtraction(overall_fatigue=9, sleep_hours_avg=3.5)
    delta = derive_plan_delta(extraction, base_plan)
    assert delta.trigger_deload is True
    assert "deload" in delta.deload_reason.lower()


def test_autoreg_high_fatigue_alone_no_deload(base_plan):
    """Fatigue alone (without poor sleep) must NOT trigger early deload."""
    extraction = CheckInExtraction(overall_fatigue=9, sleep_hours_avg=7)
    delta = derive_plan_delta(extraction, base_plan)
    assert delta.trigger_deload is False


def test_autoreg_rpe_too_hard_reduces_load(base_plan):
    """RPE 2+ points above target should reduce target_weight."""
    main_slot = base_plan.days[0].slots[0]
    # Prescribe a target weight so apply_delta has something to modify
    main_slot.target_weight = 100.0

    extraction = CheckInExtraction(
        exercises=[ExerciseFeedback(
            exercise_canonical=main_slot.exercise_id,
            rpe=float(main_slot.rpe) + 2.5,  # much harder than prescribed
            adherence="completed",
            confidence="high",
        )],
    )
    delta = derive_plan_delta(extraction, base_plan)
    adj = next((a for a in delta.slot_adjustments if a.exercise_id == main_slot.exercise_id), None)
    assert adj is not None
    assert adj.load_multiplier is not None and adj.load_multiplier < 1.0


def test_autoreg_rpe_too_easy_increases_load(base_plan):
    """RPE 2+ points below target should increase target_weight."""
    main_slot = base_plan.days[0].slots[0]
    main_slot.target_weight = 100.0

    extraction = CheckInExtraction(
        exercises=[ExerciseFeedback(
            exercise_canonical=main_slot.exercise_id,
            rpe=float(main_slot.rpe) - 2.0,  # much easier than prescribed
            adherence="completed",
            confidence="high",
        )],
    )
    delta = derive_plan_delta(extraction, base_plan)
    adj = next((a for a in delta.slot_adjustments if a.exercise_id == main_slot.exercise_id), None)
    assert adj is not None
    assert adj.load_multiplier is not None and adj.load_multiplier > 1.0


def test_autoreg_apply_delta_reduces_rpe(base_plan):
    """apply_delta with rpe_delta=-2 should lower the slot's RPE by 2."""
    from app.domain.workout.autoregulation import SlotAdjustment
    main_slot = base_plan.days[0].slots[0]
    original_rpe = main_slot.rpe

    delta = PlanDelta(
        slot_adjustments=[SlotAdjustment(
            exercise_id=main_slot.exercise_id,
            rpe_delta=-2.0,
            reason="test",
        )]
    )
    adjusted = apply_delta(base_plan, delta)
    adjusted_slot = adjusted.days[0].slots[0]
    assert adjusted_slot.rpe == max(6, original_rpe - 2)


def test_autoreg_apply_delta_does_not_mutate_original(base_plan):
    """apply_delta must return a new plan; original must be unchanged."""
    from app.domain.workout.autoregulation import SlotAdjustment
    main_slot = base_plan.days[0].slots[0]
    original_rpe = main_slot.rpe

    delta = PlanDelta(
        slot_adjustments=[SlotAdjustment(
            exercise_id=main_slot.exercise_id,
            rpe_delta=-2.0,
            reason="test",
        )]
    )
    apply_delta(base_plan, delta)
    assert base_plan.days[0].slots[0].rpe == original_rpe, "Original plan was mutated"


def test_autoreg_pr_note_added(base_plan):
    """A 1RM PR should add a note about recomputing %-based prescriptions."""
    extraction = CheckInExtraction(
        personal_records=[
            __import__("app.domain.checkin.schema", fromlist=["PersonalRecord"]).PersonalRecord(
                pr_type="1rm",
                exercise_raw="squat",
                value=180.0,
                unit="kg",
                confidence="high",
            )
        ]
    )
    delta = derive_plan_delta(extraction, base_plan)
    assert any("1RM" in n for n in delta.notes)


def test_autoreg_skipped_sessions_noted(base_plan):
    """<50% session completion should produce a volume-hold note."""
    extraction = CheckInExtraction(sessions_completed=1, sessions_planned=4)
    delta = derive_plan_delta(extraction, base_plan)
    assert any("session" in n.lower() for n in delta.notes)
