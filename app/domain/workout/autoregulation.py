"""
Auto-regulation: maps CheckInExtraction signals to a PlanDelta,
then applies the delta to the current WorkoutPlan draft.

Rule priority: safety (pain) → adherence → fatigue → progression → PR.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from app.domain.checkin.schema import CheckInExtraction
from app.models import WorkoutWeek, WorkoutSlot

logger = logging.getLogger(__name__)


@dataclass
class SlotAdjustment:
    exercise_id: str
    load_multiplier: Optional[float] = None   # e.g. 0.9 = drop 10%
    sets_delta: int = 0                       # e.g. -1, +1
    rpe_delta: float = 0.0                    # e.g. -1.0 for deload
    substitute_with: Optional[str] = None    # replacement exercise_id
    reason: str = ""


@dataclass
class PlanDelta:
    """Aggregate of all adjustments derived from a single check-in."""
    slot_adjustments: list[SlotAdjustment] = field(default_factory=list)
    trigger_deload: bool = False
    deload_reason: str = ""
    notes: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.slot_adjustments and not self.trigger_deload


def derive_plan_delta(
    extraction: CheckInExtraction,
    current_plan: WorkoutWeek,
    prior_plan: Optional[WorkoutWeek] = None,
) -> PlanDelta:
    """
    Apply rule table (priority order: safety → adherence → fatigue → progression → PR)
    and return a PlanDelta describing what to change next week.
    """
    delta = PlanDelta()

    # ── Rule 1: Safety — pain (highest priority) ───────────────────────────
    for pain in extraction.pain_flags:
        if pain.severity in ("moderate", "severe"):
            ex_id = _find_exercise_aggravated_by(pain.aggravated_by, current_plan)
            if ex_id:
                delta.slot_adjustments.append(SlotAdjustment(
                    exercise_id=ex_id,
                    rpe_delta=-2.0,
                    sets_delta=-1,
                    reason=f"Pain flag: {pain.body_part} ({pain.severity})",
                ))
            delta.notes.append(
                f"⚠️ {pain.body_part} pain ({pain.severity}) — coach review required"
            )

        if pain.is_new and pain.severity not in ("none", None):
            delta.notes.append(f"🆕 New pain: {pain.body_part} — auto-regulation held pending coach review")

    # ── Rule 2: Adherence — >50% sessions skipped ──────────────────────────
    if (extraction.sessions_completed is not None
            and extraction.sessions_planned is not None
            and extraction.sessions_planned > 0):
        completion_rate = extraction.sessions_completed / extraction.sessions_planned
        if completion_rate < 0.5:
            delta.notes.append(
                f"📉 Only {extraction.sessions_completed}/{extraction.sessions_planned} sessions completed — "
                "holding volume, no progression this week"
            )
            # Zero out all progression by keeping RPE/sets flat (no delta needed — generator will hold)

    # ── Rule 3: Fatigue + sleep — early deload trigger ────────────────────
    high_fatigue = extraction.overall_fatigue is not None and extraction.overall_fatigue >= 8
    poor_sleep = extraction.sleep_hours_avg is not None and extraction.sleep_hours_avg <= 4
    if high_fatigue and poor_sleep:
        delta.trigger_deload = True
        delta.deload_reason = (
            f"Fatigue={extraction.overall_fatigue}/10, sleep={extraction.sleep_hours_avg}h — early deload"
        )
        delta.notes.append(f"😴 Early deload triggered: {delta.deload_reason}")

    # ── Rule 3b: Performance decline across multiple lifts ────────────────
    if not delta.trigger_deload:
        high_rpe_count = 0
        for ex_fb in extraction.exercises:
            if ex_fb.rpe is None or ex_fb.exercise_canonical is None:
                continue
            planned = _find_slot(ex_fb.exercise_canonical, current_plan)
            if planned is not None and ex_fb.rpe - planned.rpe >= 2.0:
                high_rpe_count += 1
        if high_rpe_count >= 3:
            delta.trigger_deload = True
            delta.deload_reason = f"{high_rpe_count} lifts reporting RPE ≥ target+2 — systemic fatigue"
            delta.notes.append(f"📉 Reactive deload: {delta.deload_reason}")

    # ── Rule 3c: Severe joint pain — immediate deload ─────────────────────
    if not delta.trigger_deload:
        severe_pain = any(p.severity == "severe" for p in extraction.pain_flags)
        if severe_pain:
            delta.trigger_deload = True
            delta.deload_reason = "Severe joint pain reported — deload + coach review"
            delta.notes.append(f"🚨 Reactive deload: {delta.deload_reason}")

    # ── Rule 4: Progression — RPE feedback on main lifts ──────────────────
    for ex_fb in extraction.exercises:
        if ex_fb.exercise_canonical is None or ex_fb.rpe is None:
            continue
        slot = _find_slot(ex_fb.exercise_canonical, current_plan)
        if slot is None:
            continue

        rpe_error = ex_fb.rpe - slot.rpe
        if rpe_error >= 1.5 and ex_fb.confidence in ("high", "medium"):
            # Too hard — back off load
            delta.slot_adjustments.append(SlotAdjustment(
                exercise_id=ex_fb.exercise_canonical,
                load_multiplier=max(0.90, 1.0 - rpe_error * 0.04),
                reason=f"RPE error +{rpe_error:.1f} — reducing load",
            ))
        elif rpe_error <= -1.5 and ex_fb.confidence in ("high", "medium"):
            # Too easy — bump load
            delta.slot_adjustments.append(SlotAdjustment(
                exercise_id=ex_fb.exercise_canonical,
                load_multiplier=min(1.10, 1.0 + abs(rpe_error) * 0.025),
                reason=f"RPE error {rpe_error:.1f} — increasing load",
            ))

    # ── Rule 5: PR — update 1RM note ──────────────────────────────────────
    for pr in extraction.personal_records:
        if pr.pr_type == "1rm" and pr.value is not None:
            delta.notes.append(
                f"🏆 New 1RM: {pr.exercise_raw} = {pr.value}{pr.unit or 'kg'} — "
                "%-based prescriptions should be recomputed"
            )

    return delta


def apply_delta(plan: WorkoutWeek, delta: PlanDelta) -> WorkoutWeek:
    """
    Return a mutated copy of the plan with the delta applied.
    Does not mutate the original plan in-place.
    """
    if delta.is_empty():
        return plan

    import copy
    new_plan = copy.deepcopy(plan)

    adj_map = {a.exercise_id: a for a in delta.slot_adjustments}

    for day in new_plan.days:
        for slot in day.slots:
            adj = adj_map.get(slot.exercise_id)
            if adj is None:
                continue
            slot.rpe = max(6, min(10, slot.rpe + round(adj.rpe_delta)))
            slot.sets = max(1, slot.sets + adj.sets_delta)
            if adj.load_multiplier is not None and slot.target_weight is not None:
                from app.generator import AutoRegulator  # avoid circular at module level
                slot.target_weight = round(
                    (slot.target_weight * adj.load_multiplier) / 2.5
                ) * 2.5

    return new_plan


# ── Helpers ────────────────────────────────────────────────────────────────────

def _find_slot(exercise_id: str, plan: WorkoutWeek) -> Optional[WorkoutSlot]:
    for day in plan.days:
        for slot in day.slots:
            if slot.exercise_id == exercise_id:
                return slot
    return None


def _find_exercise_aggravated_by(
    aggravated_by: Optional[str], plan: WorkoutWeek
) -> Optional[str]:
    """Return the exercise_id of the slot closest to the pain-aggravating movement."""
    if not aggravated_by:
        return None
    term = aggravated_by.lower()
    for day in plan.days:
        for slot in day.slots:
            if term in slot.exercise_name.lower():
                return slot.exercise_id
    return None
