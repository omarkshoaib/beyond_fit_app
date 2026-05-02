"""
Pydantic extraction schema for free-form client check-in messages.

Design rules (enforced by this schema):
- ALL fields Optional / default None — never force the LLM to fabricate data.
- Flat enums only — no $ref / anyOf nesting that breaks JSON Schema validators.
- Per-item confidence field on every high-value sub-object.
- needs_coach_review is derived SERVER-SIDE (not by the LLM) after extraction.
- clarifying_questions_for_client max 3 items.
"""
from __future__ import annotations

from typing import List, Literal, Optional
from pydantic import BaseModel, Field


# ── Enum literals ──────────────────────────────────────────────────────────────

Confidence = Literal["high", "medium", "low"]
Adherence = Literal["completed", "partial", "substituted", "skipped", "not_mentioned"]
PainSeverity = Literal["none", "mild", "moderate", "severe", "unknown"]
PRType = Literal["1rm", "rep_pr", "volume_pr", "bodyweight_pr", "other"]
Scale1to10 = Literal[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]


# ── Sub-models ─────────────────────────────────────────────────────────────────

class ExerciseFeedback(BaseModel):
    """Feedback for a single exercise mentioned in the check-in."""
    exercise_raw: Optional[str] = None           # exact text the client used
    exercise_canonical: Optional[str] = None     # matched exercise_id from catalog
    rpe: Optional[float] = Field(default=None, ge=1, le=10)
    rir: Optional[float] = Field(default=None, ge=0, le=5)
    actual_load_kg: Optional[float] = Field(default=None, ge=0)
    actual_reps: Optional[int] = Field(default=None, ge=0)
    actual_sets: Optional[int] = Field(default=None, ge=0)
    adherence: Optional[Adherence] = None
    notes: Optional[str] = None
    confidence: Optional[Confidence] = None


class PainFlag(BaseModel):
    """A pain report — distinct from DOMS/soreness."""
    body_part: Optional[str] = None
    severity: Optional[PainSeverity] = None
    is_new: Optional[bool] = None               # True = onset this week
    aggravated_by: Optional[str] = None         # e.g. "overhead press"
    confidence: Optional[Confidence] = None


class SorenessEntry(BaseModel):
    """Delayed-onset muscle soreness (normal training response — not pain)."""
    body_part: Optional[str] = None
    severity: Optional[PainSeverity] = None     # mild/moderate = typical DOMS
    confidence: Optional[Confidence] = None


class PersonalRecord(BaseModel):
    pr_type: Optional[PRType] = None
    exercise_raw: Optional[str] = None
    exercise_canonical: Optional[str] = None
    value: Optional[float] = None               # kg for 1RM; reps for rep_pr; etc.
    unit: Optional[str] = None                  # "kg", "reps", "kg_total"
    confidence: Optional[Confidence] = None


# ── Root extraction model ──────────────────────────────────────────────────────

class CheckInExtraction(BaseModel):
    """
    Structured extraction from a single free-form client check-in message.
    Every field is Optional — null means 'not mentioned', not 'zero' or 'bad'.
    """
    # ── Wellness ──────────────────────────────────────────────────────────────
    overall_fatigue: Optional[Scale1to10] = None      # 1=fresh, 10=exhausted
    sleep_quality: Optional[Scale1to10] = None        # 1=terrible, 10=perfect
    sleep_hours_avg: Optional[float] = Field(default=None, ge=0, le=24)
    stress_level: Optional[Scale1to10] = None         # 1=none, 10=extreme
    mood: Optional[Scale1to10] = None                 # 1=very low, 10=excellent
    motivation: Optional[Scale1to10] = None           # 1=none, 10=very high

    # ── Adherence ─────────────────────────────────────────────────────────────
    sessions_completed: Optional[int] = Field(default=None, ge=0)
    sessions_planned: Optional[int] = Field(default=None, ge=0)
    missed_sessions: Optional[int] = Field(default=None, ge=0)
    missed_session_reason: Optional[str] = None

    # ── Per-exercise feedback ──────────────────────────────────────────────────
    exercises: List[ExerciseFeedback] = Field(default_factory=list)

    # ── PRs ───────────────────────────────────────────────────────────────────
    personal_records: List[PersonalRecord] = Field(default_factory=list)

    # ── Pain & soreness ───────────────────────────────────────────────────────
    pain_flags: List[PainFlag] = Field(default_factory=list)
    soreness: List[SorenessEntry] = Field(default_factory=list)

    # ── Bodyweight ────────────────────────────────────────────────────────────
    bodyweight_kg: Optional[float] = Field(default=None, ge=20, le=300)
    bodyweight_trend: Optional[Literal["gaining", "losing", "stable", "unknown"]] = None

    # ── LLM output fields ─────────────────────────────────────────────────────
    # Max 3 targeted follow-up questions the bot should ask the client.
    clarifying_questions_for_client: List[str] = Field(default_factory=list, max_length=3)

    # Populated SERVER-SIDE after extraction — never set by the LLM.
    needs_coach_review: bool = False

    def derive_coach_review_flag(self) -> None:
        """
        Set needs_coach_review based on hard rules (no LLM involved).
        Call this after extraction, before persisting.
        """
        for pain in self.pain_flags:
            if pain.severity in ("moderate", "severe"):
                self.needs_coach_review = True
                return
            if pain.is_new:
                self.needs_coach_review = True
                return
        for ex in self.exercises:
            if ex.confidence == "low" and ex.adherence in ("skipped", "substituted"):
                self.needs_coach_review = True
                return
