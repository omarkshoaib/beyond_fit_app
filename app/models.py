from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel
from typing import Dict, List, Optional
from sqlmodel import SQLModel, Field
from sqlalchemy import Column, JSON, BigInteger


class Exercise(BaseModel):
    exercise_id: str
    name: str
    movement_pattern: str
    primary_muscle: str
    secondary_muscles: List[str]
    fatigue_cost: int
    equipment_required: List[str]
    avatar_tags: List[str]
    biomechanical_focus: Optional[str] = None


class ClientProfile(SQLModel, table=True):
    client_id: str = Field(primary_key=True)
    avatar: str = Field(default="gen_pop")
    training_days: int = Field(default=3, ge=3, le=6)
    experience_level: str = Field(default="beginner")
    password_hash: Optional[str] = Field(default=None)
    is_coach: bool = Field(default=False)
    is_admin: bool = Field(default=False)
    coach_id: Optional[str] = Field(default=None, index=True)
    verified_at: Optional[datetime] = Field(default=None)
    limitations: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    available_equipment: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    week_number: int = 1
    active_workout_id: Optional[int] = None
    email: Optional[str] = Field(default=None)
    name: Optional[str] = Field(default=None)
    # Per-client feature flags (e.g. {"nutrition": True})
    features: Optional[Dict] = Field(default=None, sa_column=Column(JSON))
    # Coach exercise substitution map: {original_exercise_id: replacement_exercise_id}
    coach_overrides: Optional[Dict] = Field(default=None, sa_column=Column(JSON))
    limitations_notes: Optional[str] = Field(default=None)
    safety_override_note: Optional[str] = Field(default=None)
    # ── Safety / health screening fields (Phase 1.7) ──────────────
    # These are nullable so existing rows are unaffected.
    hypertension: Optional[bool] = Field(default=None)
    systolic_bp: Optional[int] = Field(default=None)     # mmHg
    cardiac_history: Optional[bool] = Field(default=None)
    cardiac_event_weeks_ago: Optional[int] = Field(default=None)
    osteoporosis: Optional[bool] = Field(default=None)
    pregnancy_status: Optional[str] = Field(default=None)  # "none"|"1st"|"2nd"|"3rd"
    postpartum_weeks: Optional[int] = Field(default=None)
    unexplained_weight_loss: Optional[bool] = Field(default=None)
    progressive_neuro_deficits: Optional[bool] = Field(default=None)


class ProfileSnapshot(SQLModel, table=True):
    """Immutable snapshot of a ClientProfile taken at plan-generation time."""
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: str = Field(index=True)
    snapshot_json: str  # JSON-serialised ClientProfile
    reason: str = "manual"  # e.g. "initial", "checkin", "manual"
    created_at: Optional[datetime] = Field(default=None)


class PendingApproval(SQLModel, table=True):
    approval_uuid: str = Field(primary_key=True)
    client_id: str
    client_chat_id: int = Field(sa_column=Column(BigInteger))
    client_name: str
    client_email: str
    workout_json: str
    coaching_message: str
    created_at: Optional[datetime] = Field(default=None)
    edit_log: Optional[list] = Field(default=None, sa_column=Column(JSON))
    cancelled_at: Optional[datetime] = Field(default=None)


class RejectionFeedback(SQLModel, table=True):
    """Coach-rejection messages, kept after PendingApproval is deleted so clients
    can read why their plan was rejected on the next /plans/today call."""
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: str = Field(index=True)
    feedback: str
    created_at: Optional[datetime] = Field(default=None)
    consumed: bool = Field(default=False)


class WorkoutHistory(SQLModel, table=True):
    """Versioned workout plan record. Statuses: draft|pending|approved|rejected|active|superseded."""
    history_id: Optional[int] = Field(default=None, primary_key=True)
    client_id: str = Field(index=True)
    week_number: int
    workout_json: str
    # Versioning fields (added in migration 0002)
    status: str = "active"
    block_number: int = 1
    version: int = 1
    profile_snapshot_id: Optional[int] = Field(default=None, foreign_key="profilesnapshot.id")
    acknowledged_at: Optional[datetime] = Field(default=None)
    plan_started_at: Optional[datetime] = Field(default=None)
    generation_notes: Optional[list] = Field(default=None, sa_column=Column(JSON))


class NutritionProfile(SQLModel, table=True):
    """Client nutrition preferences and biometrics (1-1 with ClientProfile, nullable)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: str = Field(unique=True, index=True)
    # Demographics
    weight_kg: Optional[float] = None
    height_cm: Optional[float] = None
    age: Optional[int] = None
    sex: Optional[str] = None              # "male" | "female"
    body_fat_pct: Optional[float] = None
    # Goals
    goal: Optional[str] = None             # fat_loss | lean_bulk | bulk | recomp | maintain
    aggressiveness: Optional[str] = None   # conservative | moderate | aggressive
    activity_level: Optional[str] = None
    target_rate_pct_per_week: Optional[float] = None
    # Preferences
    diet_style: Optional[str] = None       # omnivore | vegetarian | vegan | pescatarian | keto
    allergies: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    dislikes: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    religious_restrictions: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    meals_per_day: int = 3
    cooking_skill: int = 2                 # 1–4
    cooking_time_min: int = 30
    budget_tier: int = 2                   # 1–3
    # Medical
    medical_conditions: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    updated_at: Optional[datetime] = None


class NutritionPlan(SQLModel, table=True):
    """Immutable, versioned nutrition plan (approved by coach)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: str = Field(index=True)
    profile_snapshot_id: Optional[int] = Field(default=None, foreign_key="profilesnapshot.id")
    block_number: int = 1
    version: int = 1
    status: str = "draft"                  # draft|pending|approved|active|superseded
    # Targets
    kcal_target: Optional[float] = None
    protein_g: Optional[float] = None
    fat_g: Optional[float] = None
    carb_g: Optional[float] = None
    fiber_g: Optional[float] = None
    water_ml: Optional[float] = None
    # Plan content
    plan_json: Optional[str] = None        # serialised list[DayPlan]
    plan_markdown: Optional[str] = None
    rationale: Optional[str] = None
    approved_at: Optional[datetime] = None
    pdf_path: Optional[str] = None
    created_at: Optional[datetime] = None


class CheckIn(SQLModel, table=True):
    """Stores a single client check-in: raw text, extraction, derived plan delta."""
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: str = Field(index=True)
    raw_text: str
    extraction_json: Optional[str] = None      # JSON-serialised CheckInExtraction
    digest_markdown: Optional[str] = None      # ≤6-line coach digest
    active_workout_plan_id: Optional[int] = Field(default=None)
    resulting_workout_plan_id: Optional[int] = Field(default=None)
    needs_coach_review: bool = False
    created_at: Optional[datetime] = Field(default=None)
    structured_progress: Optional[dict] = Field(default=None, sa_column=Column(JSON))


# ── Workout plan value objects (stored as nested JSON in WorkoutHistory) ──────


class WarmupSet(BaseModel):
    pct_of_working: float
    reps: int
    rest_seconds: int
    is_primer: bool = False


class WorkoutSlot(BaseModel):
    slot_order: int = 0
    slot_type: Optional[str] = None
    exercise_id: str
    exercise_name: str
    sets: int
    reps: str
    rpe: int
    rest_seconds: Optional[int] = None
    tempo: Optional[str] = None
    coaching_cues: List[str] = []
    warmup_sets: List[WarmupSet] = []
    biomechanical_focus: Optional[str] = None
    target_weight: Optional[float] = None
    actual_weight: Optional[float] = None
    actual_rpe: Optional[float] = None


class WorkoutDay(BaseModel):
    day_name: str
    slots: List[WorkoutSlot]
    total_fatigue: int


class WorkoutWeek(BaseModel):
    week_number: int
    days: List[WorkoutDay]


class CoachedWorkoutResponse(BaseModel):
    workout: WorkoutWeek
    coaching_message: str
