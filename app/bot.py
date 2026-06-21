import os
import re
import uuid
import json
import signal
import hashlib
import html as _html
import logging
import traceback
import time
from collections import defaultdict
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import NetworkError, Conflict, BadRequest
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)
from sqlmodel import Session, select
from pydantic import ValidationError

import tempfile
from pathlib import Path

from app.generator import WorkoutGenerator, SafetyRefusalError
from app.services.llm_service import FlashCommunicationService
from app.services.pdf_service import PdfService
from app.adapters.pdf.renderer import render_plan_pdf
from datetime import datetime, timedelta, timezone

from app.models import (
    ClientProfile, WorkoutWeek, WorkoutSlot, PendingApproval, WorkoutHistory, ProfileSnapshot,
    NutritionProfile, NutritionPlan, CheckIn,
    AccessCode, Payment, Subscription, ChatBinding, CoachProfile, ClientQuestion,
)
from app.database import engine, create_db_and_tables
from app.auth import roles as auth_roles
from app.settings import get_settings

# ── Subscription gating policy (Phase G) ──────────────────────────────────────
#
# The bot enforces "paid + assigned-to-a-coach" via two decorators on entry-point
# handlers rather than a global group=-2 message gate. Every service entry point
# below MUST be decorated; mid-conversation states inherit the gate transitively
# because they are unreachable except through a gated entry.
#
# @auth_roles.requires_active_sub      — paid (Subscription.status='active' and ends_at>now)
#   • start_update_profile
#   • cmd_pick_coach
#
# @auth_roles.requires_assigned_coach  — paid + ClientProfile.assigned_coach_id is not NULL
#   • start_checkin
#   • start_diet
#   • client_plan
#   • start_log
#
# When adding a new service entry point, decorate it with one of the above.
# When in doubt, prefer @requires_assigned_coach — the stricter gate.
# ──────────────────────────────────────────────────────────────────────────────
from app.adapters.llm.extractors import extract_checkin, render_digest
from app.adapters.llm.openrouter import OpenRouterClient
from app.domain.workout.autoregulation import derive_plan_delta, apply_delta
from app.domain.workout.equipment import floor_equipment

load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)


def _resolve_review_recipient(client_id: str) -> int | None:
    """Where to DM a plan-approval message for this client.

    Prefers the client's assigned coach (Phase H scope) **only if the coach
    is still approved**. Falls back to the super-admin if the coach was
    rejected, removed, or never set, so plans don't go unreviewed.
    """
    with Session(engine) as session:
        client = session.get(ClientProfile, client_id)
        coach = None
        if client is not None and client.assigned_coach_id is not None:
            coach = session.get(CoachProfile, client.assigned_coach_id)
    if coach is not None and coach.status == "approved":
        return coach.telegram_user_id
    if client is not None and client.assigned_coach_id is not None:
        logging.warning(
            "coach_routing_stale client_id=%s assigned_coach_id=%s coach_status=%s",
            client_id, client.assigned_coach_id,
            coach.status if coach else "missing",
        )
    return auth_roles.super_admin_user_id() or _admin_chat_id()


_EMAIL_RE = __import__("re").compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _looks_like_email(s: str) -> bool:
    """Minimal but non-trivial email validator. Rejects 'foo@@@', 'a@b' (no dot)
    and 'hello'. Use at boundaries (intake, /update_profile)."""
    return bool(_EMAIL_RE.match(s)) and len(s) <= 254


def _user_can_act_on_client(user_id: int, client_id: str) -> bool:
    """Phase H scope check: super-admin sees all; coaches act only on assigned clients."""
    legacy_admin = _admin_chat_id()
    if auth_roles.is_super_admin(user_id) or (legacy_admin is not None and user_id == legacy_admin):
        return True
    if not auth_roles.is_coach(user_id):
        return False
    with Session(engine) as session:
        profile = session.get(ClientProfile, client_id)
    return profile is not None and profile.assigned_coach_id == user_id


def _admin_chat_id() -> int | None:
    """Resolve the admin Telegram chat ID.

    Reads ADMIN_CHAT_ID (current canonical name) first, falls back to the
    legacy variable name. Returns None if neither is set so callers can
    decide whether to no-op or raise.
    """
    raw = os.getenv("ADMIN_CHAT_ID") or os.getenv("ADMIN_TELEGRAM_ID")
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        logging.error("ADMIN_CHAT_ID must be an integer chat id, got %r", raw)
        return None


def _strip_markdown(text: str) -> str:
    """Remove Markdown formatting to produce safe plain text for Telegram."""
    import re
    text = re.sub(r'\*+', '', text)      # bold / italic
    text = re.sub(r'_+', '', text)       # italic / underline
    text = re.sub(r'`+', '', text)       # code
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)  # links
    return text


async def safe_send_markdown(bot, chat_id, text, reply_markup=None):
    """Try Markdown first, fall back to plain text if Telegram rejects it."""
    kwargs = dict(chat_id=chat_id, text=text, reply_markup=reply_markup)
    try:
        return await bot.send_message(**kwargs, parse_mode="Markdown")
    except Exception:
        return await bot.send_message(**{k: v for k, v in kwargs.items() if v is not None},
                                     parse_mode=None)

# ── Intake states (ints for backward compat) ──────────────────────────────────
ASK_AVATAR, ASK_DAYS, ASK_EXPERIENCE, ASK_LIMITATIONS, ASK_EMAIL = range(5)
ASK_LIMITATIONS_OTHER = "ASK_LIMITATIONS_OTHER"
# Baseline-lift intake states (A.4). Strings keep them distinct from the ints above
# within the single intake ConversationHandler.
ASK_BASE_SQUAT = "ASK_BASE_SQUAT"
ASK_BASE_BENCH = "ASK_BASE_BENCH"
ASK_BASE_DEADLIFT = "ASK_BASE_DEADLIFT"
# Equipment survey states (SP-A C1). Strings keep them distinct from the intake ints.
ASK_EQUIPMENT = "ASK_EQUIPMENT"
ASK_EQUIPMENT_CUSTOM = "ASK_EQUIPMENT_CUSTOM"
ASK_EQUIPMENT_PULLUP = "ASK_EQUIPMENT_PULLUP"
# Ability survey state (SP-B1 C4).
ASK_ABILITY = "ASK_ABILITY"
_ABILITY_FAMILIES = ["squat", "hinge", "horizontal_push", "vertical_push",
                     "horizontal_pull", "vertical_pull"]
_ABILITY_FAMILY_PROMPT = {
    "squat": "your SQUAT (bodyweight squat → barbell back squat)",
    "hinge": "your HINGE / DEADLIFT (glute bridge → barbell deadlift)",
    "horizontal_push": "your PUSH (push-ups → bench press)",
    "vertical_push": "your OVERHEAD PRESS (pike push-up → barbell OHP)",
    "horizontal_pull": "your ROW (inverted row → barbell row)",
    "vertical_pull": "your PULL-UP (assisted → strict/weighted pull-up)",
}
_ABILITY_LEVEL = {"1": 2, "2": 3, "3": 4}  # button value -> ability tier (2/3/4)

# ── /update_profile field-picker states (strings, isolated from intake) ───────
UPD_PICK = "UPD_PICK"
UPD_AVATAR = "UPD_AVATAR"
UPD_DAYS = "UPD_DAYS"
UPD_EXP = "UPD_EXP"
UPD_LIM = "UPD_LIM"
UPD_LIM_OTHER = "UPD_LIM_OTHER"
UPD_EMAIL = "UPD_EMAIL"
UPD_EQUIPMENT = "UPD_EQUIPMENT"

# ── Admin states ──────────────────────────────────────────────────────────────
ADMIN_FEEDBACK = 100
FORMCHECK_TIPS_CONFIRM = 101

# ── Check-in + post-menu states (strings to avoid int overlap) ────────────────
(
    CHECKIN_COLLECTING,
    CHECKIN_CLARIFYING,
    CHECKIN_RESUME,
    CHECKIN_EX_WEIGHT,
    CHECKIN_EX_RPE,
    CHECKIN_EX_PAIN,
    CHECKIN_EX_SETS,
    CHECKIN_GENERAL,
    POST_MENU,
    UPDATES_TEXT,
    FORMCHECK_EXERCISE,
    FORMCHECK_MODE,
    FORMCHECK_VIDEO,
) = [
    "CHECKIN_COLLECTING", "CHECKIN_CLARIFYING", "CHECKIN_RESUME",
    "CHECKIN_EX_WEIGHT", "CHECKIN_EX_RPE", "CHECKIN_EX_PAIN", "CHECKIN_EX_SETS", "CHECKIN_GENERAL",
    "POST_MENU", "UPDATES_TEXT", "FORMCHECK_EXERCISE",
    "FORMCHECK_MODE", "FORMCHECK_VIDEO",
]

# ── Log flow states ────────────────────────────────────────────────────────────
(
    LOG_SELECT_DAY, LOG_SELECT_EXERCISE, LOG_WEIGHT, LOG_RPE,
) = ["LOG_SELECT_DAY", "LOG_SELECT_EXERCISE", "LOG_WEIGHT", "LOG_RPE"]

# ── Pre-payment funnel states ──────────────────────────────────────────────────
(
    MENU_ROOT, SUBSCRIBE_PICK_PLAN, SUBSCRIBE_AWAIT_SCREENSHOT,
    LOGIN_AWAIT_CODE, FAQ_LOOP, PAY_REJECT_REASON,
) = ["MENU_ROOT", "SUBSCRIBE_PICK_PLAN", "SUBSCRIBE_AWAIT_SCREENSHOT",
     "LOGIN_AWAIT_CODE", "FAQ_LOOP", "PAY_REJECT_REASON"]

# ── Coach-application states ────────────────────────────────────────────────────
(
    COACH_APPLY_NAME, COACH_APPLY_EMAIL, COACH_APPLY_MOBILE,
    COACH_APPLY_SPECIALTY, COACH_APPLY_YEARS, COACH_APPLY_CERTS,
    COACH_APPLY_CV, COACH_APPLY_PORTFOLIO, COACH_REJECT_REASON,
) = [
    "COACH_APPLY_NAME", "COACH_APPLY_EMAIL", "COACH_APPLY_MOBILE",
    "COACH_APPLY_SPECIALTY", "COACH_APPLY_YEARS", "COACH_APPLY_CERTS",
    "COACH_APPLY_CV", "COACH_APPLY_PORTFOLIO", "COACH_REJECT_REASON",
]


# ── Client Q&A states + caps (SP-C) ──────────────────────────────────────────
ASK_QA_QUESTION = "ASK_QA_QUESTION"
QA_COACH_ANSWER = "QA_COACH_ANSWER"
_QA_MAX_PENDING = 3
_QA_MAX_LEN = 1000

# ── FAQ rate limiter (5 questions / chat / hour) ───────────────────────────────
# Maps chat_id → list of monotonic timestamps within the rolling window.
_faq_recent_calls: dict[int, list[float]] = defaultdict(list)


_FAQ_BUCKET_HARD_CAP = 10_000


def _faq_rate_check(chat_id: int) -> bool:
    """Return True if the chat is allowed another FAQ call. Side effect: records the call.

    Prunes empty buckets and caps total bucket count to bound memory if the bot
    runs for a long time without restart and the FAQ ever sees real volume.
    """
    settings = get_settings()
    limit = max(1, settings.faq_rate_limit_per_hour)
    window_seconds = 3600.0
    now = time.monotonic()
    bucket = _faq_recent_calls[chat_id]
    # Drop expired timestamps from this caller's bucket.
    bucket[:] = [t for t in bucket if now - t < window_seconds]
    if len(bucket) >= limit:
        return False
    bucket.append(now)

    if len(_faq_recent_calls) > _FAQ_BUCKET_HARD_CAP:
        # Sweep: drop callers whose entire bucket has rolled out of the window.
        stale = [c for c, b in _faq_recent_calls.items() if not b or now - b[-1] >= window_seconds]
        for c in stale:
            _faq_recent_calls.pop(c, None)
        if len(_faq_recent_calls) > _FAQ_BUCKET_HARD_CAP:
            logging.warning(
                "faq_rate_limiter_overflow buckets=%s — consider a persistent store",
                len(_faq_recent_calls),
            )
    return True


# ── Nutrition intake states ────────────────────────────────────────────────────
(
    DN_WEIGHT, DN_HEIGHT, DN_AGE, DN_SEX, DN_BODYFAT, DN_GOAL, DN_AGGRESSIVENESS,
    DN_ACTIVITY, DN_TARGET_RATE, DN_DIET_STYLE, DN_ALLERGIES, DN_DISLIKES,
    DN_RELIGIOUS, DN_MEALS, DN_COOKING_SKILL, DN_COOKING_TIME, DN_BUDGET,
    DN_MEDICAL,
) = [
    "DN_WEIGHT", "DN_HEIGHT", "DN_AGE", "DN_SEX", "DN_BODYFAT", "DN_GOAL",
    "DN_AGGRESSIVENESS", "DN_ACTIVITY", "DN_TARGET_RATE", "DN_DIET_STYLE",
    "DN_ALLERGIES", "DN_DISLIKES", "DN_RELIGIOUS", "DN_MEALS",
    "DN_COOKING_SKILL", "DN_COOKING_TIME", "DN_BUDGET", "DN_MEDICAL",
]


# ── CLIENT STATUS SUMMARY ─────────────────────────────────────────────────────

def _build_client_summary(client_id: str) -> str:
    """
    One-card status summary for admin messages.
    Shows profile, biometrics, current week, and the last 4 weeks of workout telemetry.
    """
    with Session(engine) as session:
        profile = session.get(ClientProfile, client_id)
        if not profile:
            return f"⚠️ No profile found for client {client_id}"

        nutr_profile = session.exec(
            select(NutritionProfile).where(NutritionProfile.client_id == client_id)
        ).first()

        histories = session.exec(
            select(WorkoutHistory)
            .where(WorkoutHistory.client_id == client_id)
            .order_by(WorkoutHistory.week_number.desc())
        ).all()

        subscription = session.exec(
            select(Subscription)
            .where(Subscription.client_id == client_id, Subscription.status == "active")
            .order_by(Subscription.ends_at.desc())
        ).first()
        coach = None
        if profile.assigned_coach_id is not None:
            coach = session.get(CoachProfile, profile.assigned_coach_id)

    name = profile.name or profile.client_id
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    lines = [
        f"👤 *{name}*  ·  {profile.email or 'no email'}  ·  Today: {today}",
        f"  Avatar: {profile.avatar}  ·  {profile.experience_level}  ·  "
        f"{profile.training_days}d/wk  ·  Week {profile.week_number}",
    ]
    if profile.limitations:
        lines.append(f"  Limitations: {', '.join(profile.limitations)}")
    if profile.limitations_notes:
        lines.append(f"  Limitations note: {profile.limitations_notes}")
    if profile.coach_overrides:
        override_str = ", ".join(f"{k}→{v}" for k, v in profile.coach_overrides.items())
        lines.append(f"  Overrides: {override_str}")
    if profile.available_equipment:
        lines.append(f"  Equipment: {', '.join(profile.available_equipment)}")

    if subscription is not None:
        ends = subscription.ends_at
        if ends.tzinfo is None:
            ends = ends.replace(tzinfo=timezone.utc)
        days_left = max(0, (ends - datetime.now(timezone.utc)).days)
        plan_label = "1 month" if subscription.plan_type == "1m" else "3 months"
        lines.append(
            f"  📅 Subscription: *{plan_label}* · {days_left} day(s) left "
            f"(ends {ends.strftime('%Y-%m-%d')})"
        )
    else:
        lines.append("  📅 Subscription: *none active*")

    if coach is not None:
        lines.append(f"  🧑‍🏫 Coach: *{coach.name}* ({coach.specialty})")
    elif profile.assigned_coach_id is None:
        lines.append("  🧑‍🏫 Coach: *unassigned*")

    if nutr_profile:
        bio_parts = []
        if nutr_profile.weight_kg is not None:
            bio_parts.append(f"{nutr_profile.weight_kg:.1f} kg")
        if nutr_profile.height_cm is not None:
            bio_parts.append(f"{nutr_profile.height_cm:.0f} cm")
        if nutr_profile.age is not None:
            bio_parts.append(f"{nutr_profile.age}y")
        if nutr_profile.sex:
            bio_parts.append(nutr_profile.sex)
        if nutr_profile.body_fat_pct is not None:
            bio_parts.append(f"{nutr_profile.body_fat_pct:.1f}% BF")
        if bio_parts:
            logged = nutr_profile.updated_at.strftime("%Y-%m-%d") if nutr_profile.updated_at else "unknown"
            lines.append(f"  Biometrics (logged {logged}): {' · '.join(bio_parts)}")
        if nutr_profile.goal:
            lines.append(f"  Goal: {nutr_profile.goal} ({nutr_profile.aggressiveness or 'moderate'})")

    recent = [h for h in histories if h.status in ("active", "superseded")][:4]
    if recent:
        lines.append("")
        lines.append("*Recent weeks:*")

        # Pre-compute weighted avg RPE per week for trend delta calculation
        _SLOT_WEIGHTS = {"main_compound": 2.0, "secondary_compound": 1.0, "accessory": 1.0, "isolation": 0.5}

        def _weighted_avg_rpe(h: WorkoutHistory) -> "float | None":
            wk = WorkoutWeek.model_validate_json(h.workout_json)
            total_w, total_rpe = 0.0, 0.0
            for day in wk.days:
                for slot in day.slots:
                    if slot.actual_rpe is not None:
                        w = _SLOT_WEIGHTS.get(slot.slot_type or "", 1.0)
                        total_rpe += slot.actual_rpe * w
                        total_w += w
            return total_rpe / total_w if total_w >= 3.0 else None

        week_rpees = [_weighted_avg_rpe(h) for h in reversed(recent)]

        for i, h in enumerate(reversed(recent)):
            week = WorkoutWeek.model_validate_json(h.workout_json)
            rpe_pairs = []
            loads = []
            for day in week.days:
                for slot in day.slots:
                    if slot.slot_type in ("main_compound", "secondary_compound"):
                        if slot.actual_rpe is not None:
                            rpe_pairs.append(
                                f"{slot.exercise_name[:20]}: RPE {slot.actual_rpe}"
                                + (f" @{slot.actual_weight}kg" if slot.actual_weight else "")
                            )
                        elif slot.target_weight:
                            loads.append(f"{slot.exercise_name[:20]}: {slot.target_weight}kg")

            # Trend delta vs previous week
            trend = ""
            if i > 0 and week_rpees[i] is not None and week_rpees[i - 1] is not None:
                delta = week_rpees[i] - week_rpees[i - 1]
                trend = " ▲" if delta > 0.3 else (" ▼" if delta < -0.3 else " ▬")

            status_tag = "✅" if h.status == "active" else "📁"
            lines.append(f"  {status_tag} Wk {h.week_number} ({h.status}){trend}")
            if rpe_pairs:
                for rp in rpe_pairs[:4]:
                    lines.append(f"    · {rp}")
            elif loads:
                for ld in loads[:4]:
                    lines.append(f"    · {ld}")

    return "\n".join(lines)


def _format_past_week(week: WorkoutWeek) -> str:
    """Compact summary of a completed week's actual results for admin."""
    lines = [f"*Week {week.week_number} results:*"]
    for day in week.days:
        day_lines = []
        for slot in sorted(day.slots, key=lambda s: s.slot_order):
            if slot.actual_rpe is not None or slot.actual_weight is not None:
                load = f"{slot.actual_weight}kg" if slot.actual_weight else "—"
                rpe = f"RPE {slot.actual_rpe}" if slot.actual_rpe else "—"
                day_lines.append(f"    {slot.exercise_name[:22]}: {load} × {slot.sets}  {rpe}")
        if day_lines:
            lines.append(f"  *{day.day_name}*")
            lines.extend(day_lines)
    return "\n".join(lines) if len(lines) > 1 else ""


# ── SHARED GENERATION + HITL DISPATCH ─────────────────────────────────────────

async def run_generation_and_dispatch(
    context: ContextTypes.DEFAULT_TYPE,
    client_chat_id: int,
    client_user_id: str,
    client_first_name: str,
    client_email: str,
    profile: ClientProfile,
    prior_workout: WorkoutWeek = None,
    force_deload: bool = False,
) -> None:
    if not _check_rate_limit(client_user_id):
        await context.bot.send_message(
            chat_id=client_chat_id,
            text="⏳ Please wait a few minutes before requesting another plan.",
        )
        return

    with Session(engine) as _idem_session:
        _existing = _idem_session.exec(
            select(PendingApproval).where(PendingApproval.client_id == str(client_user_id))
        ).first()
        if _existing:
            _age_s = (
                datetime.now(timezone.utc)
                - (_existing.created_at or datetime.min).replace(tzinfo=timezone.utc)
            ).total_seconds()
            if _age_s < 60 and _existing.coaching_message:
                await context.bot.send_message(
                    chat_id=client_chat_id,
                    text="A plan is already waiting for coach approval. You'll be notified once it's reviewed.",
                )
                return
            _idem_session.delete(_existing)
            _idem_session.commit()

    try:
        generator = WorkoutGenerator()
        new_workout = generator.generate(profile, prior_workout, force_deload=force_deload)

        with Session(engine) as _snap_session:
            snapshot = ProfileSnapshot(
                client_id=profile.client_id,
                snapshot_json=profile.model_dump_json(),
                reason="checkin" if prior_workout else "initial",
                created_at=datetime.now(timezone.utc),
            )
            _snap_session.add(snapshot)
            _snap_session.commit()

        llm_service = FlashCommunicationService()
        coaching_message = llm_service.generate_coaching_message(profile, new_workout)

        # Build RPE delta trace for admin visibility
        rpe_deltas = []
        if prior_workout:
            for d in prior_workout.days:
                for past_slot in d.slots:
                    if past_slot.actual_weight and past_slot.slot_type == "main_compound":
                        for nd in new_workout.days:
                            for n_slot in nd.slots:
                                if n_slot.exercise_id == past_slot.exercise_id and n_slot.target_weight:
                                    error = float(past_slot.actual_rpe) - float(past_slot.rpe)
                                    sign = "+" if error > 0 else ""
                                    rpe_deltas.append(
                                        f"- {past_slot.exercise_name}: RPE Error {sign}{error} "
                                        f"→ target {n_slot.target_weight}kg"
                                    )

        if rpe_deltas:
            coaching_message = (
                "**Auto-Regulator Deductions (Admin Only):**\n"
                + "\n".join(rpe_deltas)
                + "\n\nClient Email:\n"
                + coaching_message
            )

        approval_id = str(uuid.uuid4())

        with Session(engine) as session:
            pending = PendingApproval(
                approval_uuid=approval_id,
                client_id=client_user_id,
                client_chat_id=client_chat_id,
                client_name=client_first_name,
                client_email=client_email,
                workout_json=new_workout.model_dump_json(),
                coaching_message=coaching_message,
                created_at=datetime.now(timezone.utc),
            )
            session.add(pending)
            session.commit()

        # Route the approval DM to the assigned coach (Phase H scope) — falls back
        # to the super-admin for unassigned clients so the plan doesn't go unreviewed.
        review_recipient = _resolve_review_recipient(client_user_id)
        if review_recipient is not None:
            keyboard = [[
                InlineKeyboardButton("✅ Approve", callback_data=f"approve:{approval_id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject:{approval_id}"),
                InlineKeyboardButton("➕ Add core", callback_data=f"addcore:{approval_id}"),
            ]]

            summary = _build_client_summary(client_user_id)

            past_week_section = ""
            if prior_workout:
                pw = _format_past_week(prior_workout)
                if pw:
                    past_week_section = f"\n\n{pw}"

            gen_notes = generator.last_generation_notes
            notes_section = ""
            if gen_notes:
                notes_section = "\n\n*Generator notes:*\n" + "\n".join(f"• {n}" for n in gen_notes)
            from app.domain.workout.equipment import equipment_gap_note, validate_equipment
            gap = equipment_gap_note(profile.available_equipment if profile else None)
            if gap:
                notes_section += f"\n\n{gap}"
            # Add-core path (_core_choices_for_client) is already equipment-filtered — no guard needed there.
            _gen_violations = validate_equipment(new_workout, profile.available_equipment if profile else None)
            if _gen_violations:
                bad_list = ", ".join(f"{v.exercise_name} (needs {', '.join(v.missing)})" for v in _gen_violations)
                notes_section += f"\n\n🚫 *Equipment mismatch in this plan:* {bad_list}"

            admin_text = (
                f"🔔 *Plan ready for approval — Week {new_workout.week_number}*\n\n"
                f"{summary}"
                f"{past_week_section}"
                f"{notes_section}\n\n"
                f"────────────────────\n"
                f"{coaching_message}"
            )
            # Telegram message cap is 4096 chars — truncate coaching message if needed
            if len(admin_text) > 4000:
                admin_text = admin_text[:3950] + "\n…[truncated]"

            await safe_send_markdown(
                context.bot, review_recipient, admin_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
            )

    except SafetyRefusalError as e:
        admin_id = _admin_chat_id()
        if admin_id is not None:
            clearance_kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "✅ Mark cleared by physician",
                    callback_data=f"safety_clear:{client_user_id}:{e.condition_key}",
                )
            ]])
            await context.bot.send_message(
                chat_id=admin_id,
                text=(
                    f"⚠️ Safety gate triggered for {client_first_name} ({client_user_id})\n"
                    f"Condition: {e.condition_key}\nReason: {e.reason}"
                ),
                reply_markup=clearance_kb,
            )
        await context.bot.send_message(
            chat_id=client_chat_id,
            text="Your coach needs to review your profile before we can generate a plan. They've been notified.",
        )
        return
    except Exception as exc:
        logging.error("Engine error: %s", exc)
        await context.bot.send_message(
            chat_id=client_chat_id,
            text=f"Oops! Something went wrong in the engine: {exc}",
        )


# ── CLIENT INTAKE FLOW ─────────────────────────────────────────────────────────


def _current_client_id(update: Update) -> "str | None":
    """Resolve the opaque ClientProfile.client_id for the current chat via ChatBinding.

    Replaces the legacy `str(update.effective_user.id)` derivation, which broke
    once client_id moved to `cl_<token>` opaque strings.
    """
    chat = getattr(update, "effective_chat", None)
    if chat is None:
        return None
    client = auth_roles.get_authenticated_client(chat.id)
    return client.client_id if client else None


async def start_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point for /start. Dispatches by chat-binding status:

      - Bound chat → "Welcome back" (legacy).
      - Unbound chat → 3-button pre-payment menu.
    """
    chat_id = update.effective_chat.id
    client = auth_roles.get_authenticated_client(chat_id)

    if client is not None:
        # Returning client (any device bound to this chat).
        sub_active = auth_roles.has_active_subscription(client.client_id)
        if not sub_active:
            await update.message.reply_text(
                "Welcome back — but your subscription has expired or hasn't started yet. "
                "Tap /start → 💳 Subscribe to renew, or pick the Subscribe button below."
            )
            # Drop them at the funnel menu so they can re-pay or ask a question.
            return await _show_root_menu(update, context)

        with Session(engine, expire_on_commit=False) as session:
            has_history = session.exec(
                select(WorkoutHistory).where(WorkoutHistory.client_id == client.client_id)
            ).first()
        if has_history:
            await update.message.reply_text(
                f"Welcome back! You're on Week {client.week_number}. "
                "Type /checkin to log your week and get next week's plan."
            )
        else:
            await update.message.reply_text(
                "Welcome back! Your account is set up — finish your profile with /update_profile "
                "or wait for your coach to send your first plan."
            )
        return ConversationHandler.END

    # Brand-new chat: show the pre-payment menu.
    return await _show_root_menu(update, context)


async def _show_root_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [
        [InlineKeyboardButton("💳 Subscribe", callback_data="menu_subscribe")],
        [InlineKeyboardButton("❓ Ask a question", callback_data="menu_faq")],
        [InlineKeyboardButton("🔑 I have an account", callback_data="menu_login")],
        [InlineKeyboardButton("🧑‍🏫 I want to coach", callback_data="menu_coach")],
    ]
    text = (
        "Welcome to *Beyond Fit*! 🏋️‍♂️\n\n"
        "Pick one to get started:\n"
        "• *Subscribe* — pay and start with a coach\n"
        "• *Ask a question* — about pricing, what's included, etc.\n"
        "• *I have an account* — bind this device with your access code\n"
        "• *I want to coach* — apply to join the team"
    )
    sender = update.callback_query.edit_message_text if update.callback_query else update.message.reply_text
    await sender(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return MENU_ROOT


# ── Pre-payment funnel handlers ────────────────────────────────────────────────


async def handle_menu_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    s = get_settings()
    keyboard = [
        [InlineKeyboardButton(f"1 Month — EGP {s.subscription_price_1m_egp}", callback_data="sub_pick:1m")],
        [InlineKeyboardButton(f"3 Months — EGP {s.subscription_price_3m_egp}", callback_data="sub_pick:3m")],
        [InlineKeyboardButton("⬅️ Back", callback_data="menu_back")],
    ]
    await query.edit_message_text(
        "Choose your plan:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return SUBSCRIBE_PICK_PLAN


async def handle_subscribe_pick_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    plan_type = query.data.split(":", 1)[1]  # "1m" or "3m"
    s = get_settings()
    amount = s.subscription_price_1m_egp if plan_type == "1m" else s.subscription_price_3m_egp
    months = "1 month" if plan_type == "1m" else "3 months"
    context.user_data["subscribe_plan_type"] = plan_type
    context.user_data["subscribe_amount"] = amount

    payee = s.instapay_display_name or "Beyond Fit"
    handle = s.instapay_payee_handle or "(handle not configured)"
    text = (
        f"💳 *Pay EGP {amount}* for *{months}* via Instapay:\n\n"
        f"• To: *{payee}*\n"
        f"• Handle: `{handle}`\n\n"
        "Once you've paid, *send the screenshot here* as a photo. "
        "Your coach will verify it and unlock your account."
    )
    await query.edit_message_text(text, parse_mode="Markdown")
    return SUBSCRIBE_AWAIT_SCREENSHOT


async def handle_payment_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Photo received from a prospective subscriber."""
    photos = update.message.photo or []
    if not photos:
        await update.message.reply_text("Please send the receipt as a photo (not a document).")
        return SUBSCRIBE_AWAIT_SCREENSHOT
    file_id = photos[-1].file_id  # largest resolution

    plan_type = context.user_data.get("subscribe_plan_type")
    amount = context.user_data.get("subscribe_amount")
    if plan_type not in ("1m", "3m") or not isinstance(amount, int):
        await update.message.reply_text("Session expired — please /start over.")
        return ConversationHandler.END

    chat_id = update.effective_chat.id
    sender_name = update.effective_user.first_name or update.effective_user.username or str(chat_id)

    # Reserve a client_id now; the ClientProfile row is created on verify.
    client_id = context.user_data.get("subscribe_client_id") or auth_roles.new_client_id()
    context.user_data["subscribe_client_id"] = client_id

    with Session(engine, expire_on_commit=False) as session:
        payment = Payment(
            client_id=client_id,
            plan_type=plan_type,
            amount_egp=amount,
            screenshot_file_id=file_id,
            status="pending",
            submitted_at=datetime.now(timezone.utc),
        )
        session.add(payment)
        session.commit()
        session.refresh(payment)
        payment_id = payment.id

    # Stash chat_id + sender_name on Payment via in-memory bot_data so verify can DM back.
    pending_index = context.application.bot_data.setdefault("pending_payments", {})
    pending_index[payment_id] = {
        "chat_id": chat_id,
        "sender_name": sender_name,
        "client_id": client_id,
        "plan_type": plan_type,
        "amount": amount,
    }

    logging.info("payment_submitted client_id=%s payment_id=%s amount=%s", client_id, payment_id, amount)

    # DM super-admin with the screenshot + verify/reject buttons.
    sa_id = auth_roles.super_admin_user_id()
    if sa_id is None:
        await update.message.reply_text(
            "❗ Coach contact not configured on the bot. Please reach out directly."
        )
        return ConversationHandler.END

    months = "1 month" if plan_type == "1m" else "3 months"
    caption = (
        f"💳 <b>Payment pending</b> (id <code>{payment_id}</code>)\n"
        f"From: <b>{_html.escape(sender_name)}</b> (chat <code>{chat_id}</code>)\n"
        f"Plan: {months} — EGP {amount}\n"
        f"Tentative client_id: <code>{_html.escape(client_id)}</code>"
    )
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Verify", callback_data=f"pay_verify:{payment_id}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"pay_reject:{payment_id}"),
    ]])
    await context.bot.send_photo(
        chat_id=sa_id,
        photo=file_id,
        caption=caption,
        parse_mode="HTML",
        reply_markup=keyboard,
    )

    await update.message.reply_text(
        "✅ Got it! Your screenshot is with the coach. You'll get a message here once it's verified."
    )
    return ConversationHandler.END


# ── FAQ flow ───────────────────────────────────────────────────────────────────


_FAQ_SYSTEM_PROMPT = (
    "You are a concise customer-service assistant for the Beyond Fit coaching app. "
    "Answer questions about the service in 2-4 short sentences. Stay in scope: "
    "what the service is, how subscription works, pricing, what's included, "
    "how check-ins work, how to contact the coach. "
    "Hard facts you can cite: subscription tiers are EGP 1500 / month and EGP 3500 / "
    "3 months, paid via Instapay; access is unlocked after a coach verifies the payment "
    "screenshot; clients receive weekly programmed workouts and (optionally) nutrition "
    "plans, then check in to log RPE/weights so the next week is auto-regulated; one "
    "human coach reviews and approves every plan before it's sent. "
    "If the user asks about anything outside the service, refuse politely and redirect "
    "to the Subscribe button. Never invent prices or policies you weren't told."
)


async def handle_menu_faq(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "Ask me anything about the service. Type /cancel to go back to the menu.\n"
        "(Up to 5 questions per hour.)"
    )
    return FAQ_LOOP


async def handle_faq_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    if not _faq_rate_check(chat_id):
        await update.message.reply_text(
            "You've hit the hourly question limit. Try again in a bit, or use Subscribe to start."
        )
        return FAQ_LOOP

    question = (update.message.text or "").strip()
    if not question:
        return FAQ_LOOP
    if len(question) > 500:
        await update.message.reply_text("Please keep your question under 500 characters.")
        return FAQ_LOOP

    try:
        llm = FlashCommunicationService(_make_llm_client())
        answer = llm._llm.complete(
            system=_FAQ_SYSTEM_PROMPT,
            user=question,
            temperature=0.4,
        )
    except Exception as err:
        logging.warning("faq_llm_call failed chat_id=%s err=%s", chat_id, err)
        await update.message.reply_text(
            "Sorry, I can't reach the assistant right now. Please try again later, or hit Subscribe."
        )
        return FAQ_LOOP

    logging.info("faq_llm_call chat_id=%s q_len=%s", chat_id, len(question))
    answer = (answer or "").strip()[:1500] or "I'm not sure — please reach out via Subscribe to talk to the coach."
    await update.message.reply_text(answer)
    return FAQ_LOOP


# ── Login by access code (Phase C bundled) ─────────────────────────────────────


async def handle_menu_login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🔑 Send your access code (looks like `BF-XXXX-XXXX-XXXX`).\n"
        "Type /cancel to go back to the menu.",
        parse_mode="Markdown",
    )
    return LOGIN_AWAIT_CODE


async def handle_login_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    code = (update.message.text or "").strip().upper()
    chat_id = update.effective_chat.id

    client_id = auth_roles.find_client_by_access_code(code)
    if client_id is None:
        await update.message.reply_text(
            "❌ Invalid code. Double-check it and resend, or /cancel to go back."
        )
        return LOGIN_AWAIT_CODE

    with Session(engine, expire_on_commit=False) as session:
        result = auth_roles.bind_chat(session, chat_id=chat_id, client_id=client_id, is_primary=False)

    if result == "conflict":
        logging.info("chat_rebind_attempt blocked chat_id=%s requested_client_id=%s", chat_id, client_id)
        await update.message.reply_text(
            "❌ This Telegram chat is already linked to a different account. Reach out to the coach if this is a mistake."
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "✅ Logged in. Use /plan to see your current week or /checkin to log your last week."
    )
    return ConversationHandler.END


# ── Menu navigation ────────────────────────────────────────────────────────────


async def handle_menu_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    return await _show_root_menu(update, context)


# ── Post-verify intake entry ──────────────────────────────────────────────────


async def handle_setup_begin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Triggered by the 'Begin setup' button DM'd to the client after pay_verify."""
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    client = auth_roles.get_authenticated_client(chat_id)
    if client is None:
        await query.edit_message_text("This chat isn't linked to an account yet. /start over.")
        return ConversationHandler.END

    # Stash client_id so handle_email persists into the existing row instead of
    # creating a new one keyed by str(telegram_user_id).
    context.user_data["intake_client_id"] = client.client_id

    keyboard = [[
        InlineKeyboardButton("Powerlifter", callback_data="powerlifter"),
        InlineKeyboardButton("Powerbuilder", callback_data="powerbuilder"),
    ], [
        InlineKeyboardButton("General Fitness", callback_data="gen_pop"),
    ]]
    await query.edit_message_text(
        "Let's set up your profile! 🏋️‍♂️\n\nWhat is your primary training goal?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return ASK_AVATAR


# ── Admin payment review ───────────────────────────────────────────────────────


async def handle_payment_verify(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not auth_roles.is_super_admin(update.effective_user.id):
        await query.edit_message_caption(caption=query.message.caption + "\n\n🔒 Not authorized.")
        return

    payment_id = int(query.data.split(":", 1)[1])
    pending_index = context.application.bot_data.get("pending_payments", {})
    info = pending_index.get(payment_id)

    with Session(engine, expire_on_commit=False) as session:
        payment = session.get(Payment, payment_id)
        if payment is None:
            await query.edit_message_caption(caption="⚠️ Payment record vanished.")
            return
        if payment.status != "pending":
            await query.edit_message_caption(caption=f"Already {payment.status}.")
            return

        client_id = payment.client_id
        plan_type = payment.plan_type
        chat_id = info.get("chat_id") if info else None
        sender_name = info.get("sender_name") if info else None

        if chat_id is None:
            # Fallback: payment row exists but bot_data lost (restart). Reject path.
            await query.edit_message_caption(
                caption=(query.message.caption or "")
                + "\n\n⚠️ Lost the client's chat reference (bot restarted). Reject + ask client to /start again."
            )
            return

        # 1. Create ClientProfile row (deferred until verify).
        existing_profile = session.get(ClientProfile, client_id)
        if existing_profile is None:
            session.add(ClientProfile(
                client_id=client_id,
                avatar="gen_pop",
                training_days=3,
                experience_level="beginner",
                week_number=1,
                name=sender_name,
                created_at=datetime.now(timezone.utc),
            ))

        # 2. Create Subscription window.
        days = 30 if plan_type == "1m" else 90
        now = datetime.now(timezone.utc)
        subscription = Subscription(
            client_id=client_id,
            plan_type=plan_type,
            started_at=now,
            ends_at=now + timedelta(days=days),
            status="active",
            payment_id=payment_id,
            created_at=now,
        )
        session.add(subscription)

        # 3. Generate access code.
        code = auth_roles.generate_unique_access_code(session)
        session.add(AccessCode(
            client_id=client_id,
            code=code,
            created_at=now,
        ))

        # 4. Bind the originating chat as primary (idempotent — if the chat is
        # already bound to a *different* client we keep the existing row and log).
        existing_binding = session.exec(
            select(ChatBinding).where(ChatBinding.chat_id == chat_id)
        ).first()
        if existing_binding is None:
            session.add(ChatBinding(
                chat_id=chat_id,
                client_id=client_id,
                bound_at=now,
                is_primary=True,
            ))
        elif existing_binding.client_id != client_id:
            logging.warning(
                "chat_rebind_conflict_at_verify chat_id=%s existing_client_id=%s new_client_id=%s",
                chat_id, existing_binding.client_id, client_id,
            )

        # 5. Mark Payment verified.
        payment.status = "verified"
        payment.verified_at = now
        payment.verified_by = str(update.effective_user.id)
        session.add(payment)

        session.commit()
        session.refresh(subscription)
        sub_id = subscription.id

    logging.info(
        "payment_verified payment_id=%s subscription_id=%s client_id=%s",
        payment_id, sub_id, client_id,
    )

    # DM the client the access code, then show the coach picker.
    code_text = (
        "✅ *Payment verified!*\n\n"
        f"Your access code (don't share with anyone):\n\n`{code}`\n\n"
        "Save it somewhere safe. You can use it to log in from another device."
    )
    try:
        await context.bot.send_message(
            chat_id=chat_id, text=code_text, parse_mode="Markdown",
        )
        await _send_coach_picker(context.bot, client_id=client_id, chat_id=chat_id, with_change=False)
    except Exception as err:
        logging.warning("payment_verify dm_failed client_id=%s err=%s", client_id, err)

    # Update the admin's message.
    try:
        await query.edit_message_caption(
            caption=(query.message.caption or "")
            + f"\n\n✅ Verified. Subscription `{sub_id}` active until "
            + (now + timedelta(days=days)).strftime("%Y-%m-%d") + ".",
            parse_mode="Markdown",
        )
    except Exception:
        pass


async def handle_payment_reject_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if not auth_roles.is_super_admin(update.effective_user.id):
        try:
            await query.edit_message_caption(caption=(query.message.caption or "") + "\n\n🔒 Not authorized.")
        except Exception:
            pass
        return ConversationHandler.END
    payment_id = int(query.data.split(":", 1)[1])
    context.user_data["reject_payment_id"] = payment_id
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"Reason for rejecting payment `{payment_id}`? (free text)",
        parse_mode="Markdown",
    )
    return PAY_REJECT_REASON


async def handle_payment_reject_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    payment_id = context.user_data.pop("reject_payment_id", None)
    reason = (update.message.text or "").strip()
    if payment_id is None:
        await update.message.reply_text("Lost track of which payment to reject. Re-tap Reject on the message.")
        return ConversationHandler.END

    pending_index = context.application.bot_data.get("pending_payments", {})
    info = pending_index.get(payment_id)

    with Session(engine, expire_on_commit=False) as session:
        payment = session.get(Payment, payment_id)
        if payment is None:
            await update.message.reply_text("Payment vanished.")
            return ConversationHandler.END
        if payment.status != "pending":
            await update.message.reply_text(f"Already {payment.status}.")
            return ConversationHandler.END
        payment.status = "rejected"
        payment.rejection_reason = reason[:500]
        payment.verified_at = datetime.now(timezone.utc)
        payment.verified_by = str(update.effective_user.id)
        session.add(payment)
        session.commit()

    logging.info("payment_rejected payment_id=%s reason=%r", payment_id, reason[:100])

    if info and info.get("chat_id"):
        try:
            await context.bot.send_message(
                chat_id=info["chat_id"],
                text=f"❌ Your payment couldn't be verified.\n\nReason: {reason}\n\n/start over to retry.",
            )
        except Exception as err:
            logging.warning("payment_reject dm_failed err=%s", err)

    await update.message.reply_text(f"Rejected payment `{payment_id}`.", parse_mode="Markdown")
    return ConversationHandler.END


# ── Coach application flow (Phase D) ──────────────────────────────────────────


_COACH_SPECIALTIES = [
    ("powerlifting", "Powerlifting"),
    ("powerbuilding", "Powerbuilding"),
    ("bodybuilding", "Bodybuilding"),
    ("gen_pop", "General fitness"),
]


async def handle_menu_coach(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    # Check if this telegram_user_id already has an application.
    user_id = update.effective_user.id
    with Session(engine) as session:
        existing = session.get(CoachProfile, user_id)
    if existing is not None:
        msg = {
            "pending": "⏳ Your coach application is already submitted. Coach Shoaib will review it shortly.",
            "approved": "✅ You're already on the team! Use /help to see your coach commands.",
            "rejected": (
                "Your previous application wasn't approved. "
                f"Reason: {existing.rejection_reason or '—'}\n"
                "Reach out to the coach if you'd like to re-apply."
            ),
        }.get(existing.status, "An application exists for this account.")
        await query.edit_message_text(msg)
        return ConversationHandler.END

    context.user_data["coach_apply"] = {}
    await query.edit_message_text(
        "🧑‍🏫 *Coach application*\n\n"
        "We'll need a few details + your CV (PDF). Type /cancel anytime to abort.\n\n"
        "First — what's your *full name*?",
        parse_mode="Markdown",
    )
    return COACH_APPLY_NAME


async def coach_apply_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = (update.message.text or "").strip()
    if len(name) < 2:
        await update.message.reply_text("Please send your full name (at least 2 characters).")
        return COACH_APPLY_NAME
    context.user_data.setdefault("coach_apply", {})["name"] = name[:120]
    await update.message.reply_text("Good. What's your *email* address?", parse_mode="Markdown")
    return COACH_APPLY_EMAIL


async def coach_apply_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    email = (update.message.text or "").strip()
    if not _looks_like_email(email):
        await update.message.reply_text("That doesn't look like a valid email. Try again.")
        return COACH_APPLY_EMAIL
    context.user_data.setdefault("coach_apply", {})["email"] = email
    await update.message.reply_text(
        "Got it. *Mobile number* (the one Coach Shoaib can call for an interview)?",
        parse_mode="Markdown",
    )
    return COACH_APPLY_MOBILE


async def coach_apply_mobile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    mobile = (update.message.text or "").strip()
    if len(mobile) < 7 or len(mobile) > 30:
        await update.message.reply_text("Please send a valid phone number with country code.")
        return COACH_APPLY_MOBILE
    context.user_data.setdefault("coach_apply", {})["mobile"] = mobile
    keyboard = [
        [InlineKeyboardButton(label, callback_data=f"coach_spec:{key}")]
        for key, label in _COACH_SPECIALTIES
    ]
    await update.message.reply_text(
        "What's your *specialty*?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return COACH_APPLY_SPECIALTY


async def coach_apply_specialty(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    spec = query.data.split(":", 1)[1]
    valid = {k for k, _ in _COACH_SPECIALTIES}
    if spec not in valid:
        await query.edit_message_text("Pick one of the listed specialties.")
        return COACH_APPLY_SPECIALTY
    context.user_data.setdefault("coach_apply", {})["specialty"] = spec
    await query.edit_message_text("How many *years* of coaching experience? (just the number)",
                                   parse_mode="Markdown")
    return COACH_APPLY_YEARS


async def coach_apply_years(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = (update.message.text or "").strip()
    try:
        years = int(raw)
    except ValueError:
        await update.message.reply_text("Send a whole number, e.g. `5`.", parse_mode="Markdown")
        return COACH_APPLY_YEARS
    if years < 0 or years > 60:
        await update.message.reply_text("That doesn't seem right — try again.")
        return COACH_APPLY_YEARS
    context.user_data.setdefault("coach_apply", {})["years"] = years
    await update.message.reply_text(
        "*Certifications / qualifications* (one message, free text — list whatever's relevant):",
        parse_mode="Markdown",
    )
    return COACH_APPLY_CERTS


async def coach_apply_certs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    certs = (update.message.text or "").strip()[:1500]
    if len(certs) < 3:
        await update.message.reply_text("Please send a brief list of certifications.")
        return COACH_APPLY_CERTS
    context.user_data.setdefault("coach_apply", {})["certifications"] = certs
    await update.message.reply_text(
        "Now *upload your CV* as a PDF (paperclip → File). "
        "Or type /skip to continue without one.",
        parse_mode="Markdown",
    )
    return COACH_APPLY_CV


async def coach_apply_cv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Accept a PDF upload (or /skip) then move to optional portfolio text."""
    cv_file_id: str | None = None
    if update.message.document is not None:
        doc = update.message.document
        mime = (doc.mime_type or "").lower()
        if "pdf" not in mime and not (doc.file_name or "").lower().endswith(".pdf"):
            await update.message.reply_text(
                "Please send a PDF (or /skip)."
            )
            return COACH_APPLY_CV
        cv_file_id = doc.file_id
    elif update.message.text and update.message.text.strip().lower() == "/skip":
        cv_file_id = None
    else:
        await update.message.reply_text("Send a PDF document, or /skip.")
        return COACH_APPLY_CV

    context.user_data.setdefault("coach_apply", {})["cv_file_id"] = cv_file_id
    await update.message.reply_text(
        "Last step — *short portfolio note* (one paragraph: who you train, results, "
        "anything else relevant). Or /skip.",
        parse_mode="Markdown",
    )
    return COACH_APPLY_PORTFOLIO


async def coach_apply_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = (update.message.text or "").strip()
    portfolio = None if raw.lower() == "/skip" else raw[:2000]
    data = context.user_data.get("coach_apply", {})
    user_id = update.effective_user.id

    with Session(engine, expire_on_commit=False) as session:
        # Re-check on race: another submission might have inserted while we collected.
        existing = session.get(CoachProfile, user_id)
        if existing is not None:
            await update.message.reply_text("It looks like you already have an application — try later.")
            return ConversationHandler.END

        coach = CoachProfile(
            telegram_user_id=user_id,
            name=data.get("name", "—"),
            email=data.get("email", "—"),
            mobile=data.get("mobile", "—"),
            specialty=data.get("specialty", "gen_pop"),
            years_experience=int(data.get("years", 0)),
            certifications=data.get("certifications", "—"),
            cv_file_id=data.get("cv_file_id"),
            portfolio_text=portfolio,
            status="pending",
            applied_at=datetime.now(timezone.utc),
        )
        session.add(coach)
        session.commit()
        session.refresh(coach)

    logging.info("coach_application_submitted user_id=%s name=%s", user_id, data.get("name"))

    sa_id = auth_roles.super_admin_user_id()
    if sa_id is not None:
        spec_label = dict(_COACH_SPECIALTIES).get(coach.specialty, coach.specialty)
        _e = lambda s: _html.escape(str(s or ""))
        bundle = (
            "🧑‍🏫 <b>New coach application</b>\n"
            f"• Name: <b>{_e(coach.name)}</b>\n"
            f"• Email: <code>{_e(coach.email)}</code>\n"
            f"• Mobile: <code>{_e(coach.mobile)}</code>\n"
            f"• Specialty: {_e(spec_label)}\n"
            f"• Experience: {coach.years_experience} years\n"
            f"• Certifications: {_e(coach.certifications)}\n"
            f"• Portfolio: {_e(portfolio) or '—'}\n"
            f"• Telegram user id: <code>{user_id}</code>"
        )
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Approve", callback_data=f"coach_verify:{user_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"coach_reject:{user_id}"),
        ]])
        try:
            await context.bot.send_message(
                chat_id=sa_id, text=bundle, parse_mode="HTML", reply_markup=keyboard,
            )
            if coach.cv_file_id is not None:
                await context.bot.send_document(
                    chat_id=sa_id,
                    document=coach.cv_file_id,
                    caption=f"CV — {coach.name}",
                )
        except Exception as err:
            logging.warning("coach_application admin notify failed: %s", err)

    await update.message.reply_text(
        "✅ Submitted! Coach Shoaib will reach out to your mobile number for the interview."
    )
    context.user_data.pop("coach_apply", None)
    return ConversationHandler.END


# ── Admin coach approve/reject ────────────────────────────────────────────────


async def handle_coach_verify(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not auth_roles.is_super_admin(update.effective_user.id):
        return

    coach_user_id = int(query.data.split(":", 1)[1])
    with Session(engine, expire_on_commit=False) as session:
        coach = session.get(CoachProfile, coach_user_id)
        if coach is None:
            try:
                await query.edit_message_text("⚠️ Coach record vanished.")
            except Exception:
                pass
            return
        if coach.status != "pending":
            try:
                await query.edit_message_text(f"Already {coach.status}.")
            except Exception:
                pass
            return
        coach.status = "approved"
        coach.decided_at = datetime.now(timezone.utc)
        coach.decided_by = str(update.effective_user.id)
        session.add(coach)
        session.commit()

    auth_roles.invalidate_coach_cache(coach_user_id)
    logging.info("coach_approved user_id=%s by=%s", coach_user_id, update.effective_user.id)

    try:
        await context.bot.send_message(
            chat_id=coach_user_id,
            text=f"✅ Welcome aboard, <b>{_html.escape(coach.name)}</b>! "
                 "You've been approved as a coach.\n"
                 "You'll receive client plans for review here.",
            parse_mode="HTML",
        )
    except Exception as err:
        logging.warning("coach_approve dm_failed user_id=%s err=%s", coach_user_id, err)

    try:
        await query.edit_message_text(f"✅ {coach.name} approved.")
    except Exception:
        pass


async def handle_coach_reject_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if not auth_roles.is_super_admin(update.effective_user.id):
        return ConversationHandler.END
    coach_user_id = int(query.data.split(":", 1)[1])
    context.user_data["reject_coach_user_id"] = coach_user_id
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"Reason for rejecting coach `{coach_user_id}`? (free text)",
        parse_mode="Markdown",
    )
    return COACH_REJECT_REASON


async def handle_coach_reject_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    coach_user_id = context.user_data.pop("reject_coach_user_id", None)
    if coach_user_id is None:
        await update.message.reply_text("Lost track — re-tap the Reject button on the message.")
        return ConversationHandler.END
    reason = (update.message.text or "").strip()[:500]

    with Session(engine, expire_on_commit=False) as session:
        coach = session.get(CoachProfile, coach_user_id)
        if coach is None:
            await update.message.reply_text("Coach vanished.")
            return ConversationHandler.END
        if coach.status != "pending":
            await update.message.reply_text(f"Already {coach.status}.")
            return ConversationHandler.END
        coach.status = "rejected"
        coach.rejection_reason = reason
        coach.decided_at = datetime.now(timezone.utc)
        coach.decided_by = str(update.effective_user.id)
        session.add(coach)
        session.commit()

    auth_roles.invalidate_coach_cache(coach_user_id)
    logging.info("coach_rejected user_id=%s reason=%r", coach_user_id, reason[:100])

    try:
        await context.bot.send_message(
            chat_id=coach_user_id,
            text=f"Your coach application wasn't approved this time.\n\nReason: {reason}",
        )
    except Exception as err:
        logging.warning("coach_reject dm_failed err=%s", err)

    await update.message.reply_text(f"❌ Coach `{coach_user_id}` rejected.", parse_mode="Markdown")
    return ConversationHandler.END


# ── Coach picker (Phase E) ────────────────────────────────────────────────────


async def _send_coach_picker(bot, *, client_id: str, chat_id: int, with_change: bool) -> None:
    """DM the client with the coach picker root buttons."""
    rows = [
        [InlineKeyboardButton("👀 Pick a coach", callback_data=f"cp_list:{client_id}")],
        [InlineKeyboardButton("🤝 Let coach Shoaib choose for me", callback_data=f"cp_admin:{client_id}")],
    ]
    if with_change:
        rows.insert(1, [InlineKeyboardButton("🔄 Change coach", callback_data=f"cp_list:{client_id}")])
    text = (
        "*Pick your coach.*\n\n"
        "• *See the list* and choose one yourself.\n"
        "• Or *let Coach Shoaib match you* with the most-fitting coach."
    )
    await bot.send_message(
        chat_id=chat_id, text=text, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def handle_coach_picker_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Client clicked 'Pick a coach' — render the list of approved coaches."""
    query = update.callback_query
    await query.answer()
    client_id = query.data.split(":", 1)[1]

    # Sanity: caller's chat must be bound to this client.
    bound = auth_roles.get_authenticated_client(query.message.chat_id)
    if bound is None or bound.client_id != client_id:
        await query.edit_message_text("This coach picker isn't yours.")
        return

    with Session(engine) as session:
        coaches = session.exec(
            select(CoachProfile).where(CoachProfile.status == "approved")
        ).all()

    if not coaches:
        await query.edit_message_text(
            "No coaches are available yet — Coach Shoaib will assign you personally. "
            "Hold tight, you'll get a message soon."
        )
        # Auto-route to admin-pick.
        await _notify_admin_for_assignment(context.bot, client_id)
        return

    rows = [
        [InlineKeyboardButton(
            f"{dict(_COACH_SPECIALTIES).get(c.specialty, c.specialty)} — {c.name}",
            callback_data=f"cp_pick:{client_id}:{c.telegram_user_id}",
        )]
        for c in coaches
    ]
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"cp_back:{client_id}")])

    await query.edit_message_text(
        "Pick a coach:",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def handle_coach_picker_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, client_id, coach_id_str = query.data.split(":", 2)
    coach_id = int(coach_id_str)

    bound = auth_roles.get_authenticated_client(query.message.chat_id)
    if bound is None or bound.client_id != client_id:
        await query.edit_message_text("This coach picker isn't yours.")
        return

    with Session(engine, expire_on_commit=False) as session:
        coach = session.get(CoachProfile, coach_id)
        if coach is None or coach.status != "approved":
            await query.edit_message_text("That coach is no longer available — pick another.")
            return
        client = session.get(ClientProfile, client_id)
        if client is None:
            await query.edit_message_text("Client record vanished. /start over.")
            return
        client.assigned_coach_id = coach_id
        session.add(client)
        session.commit()

    logging.info("coach_assigned client_id=%s coach_id=%s", client_id, coach_id)

    spec = dict(_COACH_SPECIALTIES).get(coach.specialty, coach.specialty)
    await query.edit_message_text(
        f"✅ Assigned to <b>{_html.escape(coach.name)}</b> ({_html.escape(spec)}).",
        parse_mode="HTML",
    )

    # Now offer to begin profile setup (only if not yet set up).
    if not (client.email and client.training_days):
        try:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="Tap below to finish setting up your profile.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("👉 Begin setup", callback_data="setup_begin"),
                ]]),
            )
        except Exception as err:
            logging.warning("coach_pick begin_setup dm_failed err=%s", err)


async def handle_coach_picker_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Client clicked 'Let admin choose' — notify super-admin."""
    query = update.callback_query
    await query.answer()
    client_id = query.data.split(":", 1)[1]

    bound = auth_roles.get_authenticated_client(query.message.chat_id)
    if bound is None or bound.client_id != client_id:
        await query.edit_message_text("This coach picker isn't yours.")
        return

    await _notify_admin_for_assignment(context.bot, client_id)
    await query.edit_message_text(
        "🤝 Got it — Coach Shoaib will pick the best match and assign you. "
        "You'll get a message here once it's done."
    )


async def handle_coach_picker_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    client_id = query.data.split(":", 1)[1]
    bound = auth_roles.get_authenticated_client(query.message.chat_id)
    if bound is None or bound.client_id != client_id:
        return
    # Determine if client already has a coach (to show Change option).
    with Session(engine) as session:
        client = session.get(ClientProfile, client_id)
    with_change = bool(client and client.assigned_coach_id)
    rows = [
        [InlineKeyboardButton("👀 Pick a coach", callback_data=f"cp_list:{client_id}")],
        [InlineKeyboardButton("🤝 Let coach Shoaib choose for me", callback_data=f"cp_admin:{client_id}")],
    ]
    if with_change:
        rows.insert(1, [InlineKeyboardButton("🔄 Change coach", callback_data=f"cp_list:{client_id}")])
    text = (
        "*Pick your coach.*\n\n"
        "• *See the list* and choose one yourself.\n"
        "• Or *let Coach Shoaib match you* with the most-fitting coach."
    )
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows))


async def _notify_admin_for_assignment(bot, client_id: str) -> None:
    """DM the super-admin with the list of approved coaches as quick-assign buttons."""
    sa_id = auth_roles.super_admin_user_id()
    if sa_id is None:
        logging.warning("admin_pick requested but no super_admin configured")
        return

    with Session(engine) as session:
        client = session.get(ClientProfile, client_id)
        coaches = session.exec(
            select(CoachProfile).where(CoachProfile.status == "approved")
        ).all()

    name = (client and client.name) or client_id
    if not coaches:
        await bot.send_message(
            chat_id=sa_id,
            text=(
                f"⚠️ Client *{name}* (`{client_id}`) needs a coach but none are approved yet. "
                "Approve a CoachProfile first, then re-run the picker."
            ),
            parse_mode="Markdown",
        )
        return

    rows = [
        [InlineKeyboardButton(
            f"{dict(_COACH_SPECIALTIES).get(c.specialty, c.specialty)} — {c.name}",
            callback_data=f"admin_assign:{client_id}:{c.telegram_user_id}",
        )]
        for c in coaches
    ]
    text = (
        f"🤝 *Coach assignment needed* — client *{name}* (`{client_id}`) "
        "wants you to pick. Tap a coach to assign:"
    )
    await bot.send_message(
        chat_id=sa_id, text=text, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def handle_admin_assign(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Super-admin assigns a coach from the notification message."""
    query = update.callback_query
    await query.answer()
    if not auth_roles.is_super_admin(update.effective_user.id):
        return
    _, client_id, coach_id_str = query.data.split(":", 2)
    coach_id = int(coach_id_str)

    with Session(engine, expire_on_commit=False) as session:
        coach = session.get(CoachProfile, coach_id)
        client = session.get(ClientProfile, client_id)
        if coach is None or coach.status != "approved":
            await query.edit_message_text("That coach is no longer approved.")
            return
        if client is None:
            await query.edit_message_text("Client record vanished.")
            return
        client.assigned_coach_id = coach_id
        session.add(client)
        session.commit()

    logging.info("coach_assigned_by_admin client_id=%s coach_id=%s", client_id, coach_id)

    await query.edit_message_text(
        f"✅ Assigned <b>{_html.escape(coach.name)}</b> to "
        f"{_html.escape(client.name or client_id)}.",
        parse_mode="HTML",
    )

    # Notify the client.
    chat_id = auth_roles.resolve_primary_chat_id(client_id)
    if chat_id is not None:
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ Coach Shoaib paired you with <b>{_html.escape(coach.name)}</b>.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("👉 Begin setup", callback_data="setup_begin"),
                ]]),
            )
        except Exception as err:
            logging.warning("admin_assign client dm_failed err=%s", err)


@auth_roles.requires_active_sub
async def cmd_pick_coach(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/pick_coach — re-open the coach picker for an authenticated client."""
    chat_id = update.effective_chat.id
    client = auth_roles.get_authenticated_client(chat_id)
    if client is None:
        await update.message.reply_text("Your chat isn't linked to a client account. /start over.")
        return
    await _send_coach_picker(
        context.bot,
        client_id=client.client_id,
        chat_id=chat_id,
        with_change=bool(client.assigned_coach_id),
    )


# ── Subscription expiry + renewal reminders (Phase F) ─────────────────────────


from app.models import ReminderLog  # noqa: E402  (kept near job code for locality)


_REMINDER_KINDS = (("d7", 7), ("d3", 3), ("d1", 1))


def _utc_naive_now() -> datetime:
    """Canonical naive-UTC clock for columns stored as `timestamp without time zone`.

    Subscription.ends_at, ReminderLog.sent_at and friends are stored naive on
    Postgres. Comparing them to tz-aware values from datetime.now(timezone.utc)
    is implementation-defined across drivers — always use this helper.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _as_naive(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


async def send_renewal_reminders(context) -> None:
    """Daily job: DM clients whose subscription ends in 7/3/1 days. Idempotent
    via ReminderLog UNIQUE(subscription_id, kind)."""
    bot = context.bot
    now = _utc_naive_now()
    for kind, days in _REMINDER_KINDS:
        window_start = now + timedelta(days=days)
        window_end = window_start + timedelta(days=1)
        await _emit_reminder_window(bot, kind, window_start, window_end)


async def _emit_reminder_window(bot, kind: str, window_start: datetime, window_end: datetime) -> None:
    with Session(engine) as session:
        sent_ids = {
            r.subscription_id for r in session.exec(
                select(ReminderLog).where(ReminderLog.kind == kind)
            )
        }
        candidates = session.exec(
            select(Subscription).where(
                Subscription.status == "active",
                Subscription.ends_at >= window_start,
                Subscription.ends_at < window_end,
            )
        ).all()
        candidates = [c for c in candidates if c.id not in sent_ids]

    for sub in candidates:
        chat_id = auth_roles.resolve_primary_chat_id(sub.client_id)
        if chat_id is None:
            continue
        ends_naive = _as_naive(sub.ends_at)
        days_left = max(0, (ends_naive - _utc_naive_now()).days) if ends_naive else 0
        msg = _renewal_message(kind, days_left)
        try:
            await bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
        except Exception as err:
            logging.warning("renewal_reminder send_failed sub_id=%s err=%s", sub.id, err)
            continue
        with Session(engine) as session:
            try:
                session.add(ReminderLog(
                    subscription_id=sub.id, kind=kind,
                    sent_at=_utc_naive_now(),
                ))
                session.commit()
                logging.info(
                    "renewal_reminder_sent client_id=%s kind=%s sub_id=%s",
                    sub.client_id, kind, sub.id,
                )
            except Exception as err:
                # UNIQUE collision = another worker beat us; safe.
                session.rollback()
                logging.info("renewal_reminder duplicate sub_id=%s kind=%s (%s)", sub.id, kind, err)


def _renewal_message(kind: str, days_left: int) -> str:
    if kind == "d7":
        return (
            f"⏳ Heads up — your subscription expires in *{days_left} days*.\n"
            "Renew with /start → Subscribe to keep your plan running."
        )
    if kind == "d3":
        return (
            f"⏳ *3 days left* on your subscription.\n"
            "Renew now to avoid losing access — /start → Subscribe."
        )
    if kind == "d1":
        return (
            "⚠️ *Your subscription expires tomorrow.*\n"
            "Renew today to keep getting plans — /start → Subscribe."
        )
    return f"Subscription reminder ({kind}, {days_left}d)."


async def expire_subscriptions(context) -> None:
    """Daily job: mark subs whose ends_at has passed as expired + DM the client."""
    bot = context.bot
    now = _utc_naive_now()
    expired_ids: list[int] = []
    expired_clients: list[tuple[int, str]] = []  # (sub_id, client_id)

    with Session(engine, expire_on_commit=False) as session:
        rows = session.exec(
            select(Subscription).where(
                Subscription.status == "active",
                Subscription.ends_at < now,
            )
        ).all()
        for sub in rows:
            sub.status = "expired"
            session.add(sub)
            expired_ids.append(sub.id)
            expired_clients.append((sub.id, sub.client_id))
        session.commit()

    sent_kind = "expired"
    for sub_id, client_id in expired_clients:
        chat_id = auth_roles.resolve_primary_chat_id(client_id)
        if chat_id is None:
            continue
        # Idempotency on the "expired" DM as well.
        with Session(engine) as session:
            already = session.exec(
                select(ReminderLog).where(
                    ReminderLog.subscription_id == sub_id,
                    ReminderLog.kind == sent_kind,
                )
            ).first()
        if already is not None:
            continue
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=(
                    "⛔ *Your subscription has expired.*\n\n"
                    "Service is paused. /start → Subscribe to renew."
                ),
                parse_mode="Markdown",
            )
        except Exception as err:
            logging.warning("expire_dm send_failed sub_id=%s err=%s", sub_id, err)
            continue
        with Session(engine) as session:
            try:
                session.add(ReminderLog(
                    subscription_id=sub_id, kind=sent_kind,
                    sent_at=_utc_naive_now(),
                ))
                session.commit()
            except Exception:
                session.rollback()
        logging.info("subscription_expired sub_id=%s client_id=%s", sub_id, client_id)


async def handle_avatar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data['avatar'] = query.data
    display = {"powerlifter": "Powerlifter", "powerbuilder": "Powerbuilder", "gen_pop": "General Fitness"}.get(query.data, "General Fitness")

    keyboard = [[
        InlineKeyboardButton("3 Days", callback_data="3"),
        InlineKeyboardButton("4 Days", callback_data="4"),
    ], [
        InlineKeyboardButton("5 Days", callback_data="5"),
        InlineKeyboardButton("6 Days", callback_data="6"),
    ]]
    await query.edit_message_text(
        f"Great, {display}!\n\nHow many days a week can you train?",
        reply_markup=_with_back(InlineKeyboardMarkup(keyboard), ASK_DAYS),
    )
    return ASK_DAYS


async def handle_days(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data['days'] = int(query.data)

    await query.edit_message_text(
        "What equipment do you have access to?",
        reply_markup=_with_back(_equipment_preset_keyboard(), ASK_EQUIPMENT),
    )
    return ASK_EQUIPMENT


def _equipment_preset_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏢 Commercial gym (everything)", callback_data="equip_preset:commercial")],
        [InlineKeyboardButton("🏠 Home gym — customize", callback_data="equip_preset:home")],
        [InlineKeyboardButton("🧰 Minimal (bodyweight + pull-up bar)", callback_data="equip_preset:minimal")],
        [InlineKeyboardButton("🧍 Bodyweight only", callback_data="equip_preset:bodyweight")],
        [InlineKeyboardButton("⚙️ Custom — pick each item", callback_data="equip_preset:custom")],
    ])


def _equipment_checklist_keyboard(selected: set) -> InlineKeyboardMarkup:
    from app.domain.workout.equipment import CHECKLIST_TOKENS
    rows = []
    for i in range(0, len(CHECKLIST_TOKENS), 2):
        row = []
        for tok in CHECKLIST_TOKENS[i:i + 2]:
            label = f"✓ {tok}" if tok in selected else tok
            row.append(InlineKeyboardButton(label, callback_data=f"equip_toggle_{tok}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("✅ Done", callback_data="equip_confirm")])
    return InlineKeyboardMarkup(rows)


def _pullup_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes", callback_data="equip_pullup:yes"),
        InlineKeyboardButton("❌ No", callback_data="equip_pullup:no"),
    ]])


async def _prompt_experience(send) -> None:
    keyboard = [
        [InlineKeyboardButton("Beginner", callback_data="beginner")],
        [InlineKeyboardButton("Intermediate", callback_data="intermediate")],
        [InlineKeyboardButton("Advanced", callback_data="advanced")],
    ]
    await send("What is your experience level?",
               reply_markup=_with_back(InlineKeyboardMarkup(keyboard), ASK_EXPERIENCE))


async def handle_equipment_preset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from app.domain.workout.equipment import EQUIPMENT_PRESETS
    query = update.callback_query
    await query.answer()
    preset = query.data.split(":", 1)[1]
    context.user_data["equip_preset"] = preset
    if preset == "commercial":
        context.user_data["available_equipment"] = list(EQUIPMENT_PRESETS["commercial"])
        await _prompt_experience(query.edit_message_text)
        return ASK_EXPERIENCE
    if preset == "minimal":
        context.user_data["available_equipment"] = list(EQUIPMENT_PRESETS["minimal"])
        await _prompt_experience(query.edit_message_text)
        return ASK_EXPERIENCE
    if preset == "bodyweight":
        await query.edit_message_text(
            "Do you have a pull-up bar? It unlocks all your back/pull training.",
            reply_markup=_with_back(_pullup_keyboard(), ASK_EQUIPMENT_PULLUP),
        )
        return ASK_EQUIPMENT_PULLUP
    # home (pre-checked) or custom (empty) -> open the checklist
    selected = set(EQUIPMENT_PRESETS["home"]) if preset == "home" else set()
    selected.discard("bodyweight")  # bodyweight is implicit, not a checkbox
    context.user_data["equip_selected"] = selected
    await query.edit_message_text(
        "Check everything you have, then tap Done:",
        reply_markup=_with_back(_equipment_checklist_keyboard(selected), ASK_EQUIPMENT_CUSTOM),
    )
    return ASK_EQUIPMENT_CUSTOM


async def handle_equipment_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tok = query.data[len("equip_toggle_"):]
    selected: set = context.user_data.get("equip_selected", set())
    if tok in selected:
        selected.discard(tok)
    else:
        selected.add(tok)
    context.user_data["equip_selected"] = selected
    await query.edit_message_reply_markup(
        reply_markup=_with_back(_equipment_checklist_keyboard(selected), ASK_EQUIPMENT_CUSTOM))
    return ASK_EQUIPMENT_CUSTOM


async def handle_equipment_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    selected = sorted(context.user_data.get("equip_selected", set()))
    # bodyweight is always available; persist it alongside the picked machines.
    tokens = floor_equipment(selected + ["bodyweight"] if selected else [])
    context.user_data["available_equipment"] = tokens
    await _prompt_experience(query.edit_message_text)
    return ASK_EXPERIENCE


async def handle_equipment_pullup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    answer = query.data.split(":", 1)[1]
    if answer == "yes":
        context.user_data["available_equipment"] = ["bodyweight", "pull_up_bar"]
        await _prompt_experience(query.edit_message_text)
    else:
        context.user_data["available_equipment"] = ["bodyweight"]
        await query.edit_message_text(
            "Heads up: bodyweight-only means *no back/pull training* until you get a "
            "pull-up bar or your coach adds bands. Your coach will see this.",
            parse_mode="Markdown",
        )
        await _prompt_experience(query.message.reply_text)
    return ASK_EXPERIENCE


_LIMITATION_OPTIONS = [
    "lower_back_pain",
    "knee_pain",
    "shoulder_impingement",
    "wrist_pain",
    "hip_flexor_tightness",
    "none",
]


def _build_limitations_keyboard(selected: set) -> InlineKeyboardMarkup:
    rows = []
    options = [o for o in _LIMITATION_OPTIONS if o != "none"]
    for i in range(0, len(options), 2):
        row = []
        for opt in options[i:i + 2]:
            label = f"✓ {opt}" if opt in selected else opt
            row.append(InlineKeyboardButton(label, callback_data=f"lim_toggle_{opt}"))
        rows.append(row)
    none_label = "✓ none (no limitations)" if "none" in selected else "none (no limitations)"
    rows.append([InlineKeyboardButton(none_label, callback_data="lim_toggle_none")])
    other_label = "✓ 📝 Other (describe)" if "other" in selected else "📝 Other (describe)"
    rows.append([InlineKeyboardButton(other_label, callback_data="lim_toggle_other")])
    rows.append([InlineKeyboardButton("✅ Done", callback_data="lim_confirm")])
    return InlineKeyboardMarkup(rows)


def _parse_baseline_set(text: str):
    """Parse 'WxR' (weight x reps) like '100x5'. Returns (weight, reps) or None.

    Rejects unparseable input, non-positive weight, and reps > 10 (the e1RM
    formula is unreliable past 10 reps — re-ask rather than seed garbage).
    """
    if not text:
        return None
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*[xX*]\s*(\d+)\s*$", text.strip())
    if not m:
        return None
    weight = float(m.group(1))
    reps = int(m.group(2))
    if weight <= 0 or reps < 1 or reps > 10:
        return None
    return (weight, reps)


def _ability_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌱 New / can't yet", callback_data="abil:1")],
        [InlineKeyboardButton("💪 I can do the standard version", callback_data="abil:2")],
        [InlineKeyboardButton("🏋️ Strong — barbell/loaded", callback_data="abil:3")],
        [InlineKeyboardButton("⏭️ Skip — use my experience level", callback_data="abil_skip")],
    ])


async def _prompt_ability(send, idx: int) -> None:
    fam = _ABILITY_FAMILIES[idx]
    await send(
        f"Quick ability check ({idx + 1}/6) — how's {_ABILITY_FAMILY_PROMPT[fam]}?",
        reply_markup=_with_back(_ability_keyboard(), ASK_ABILITY),
    )


async def _prompt_limitations(send, context: ContextTypes.DEFAULT_TYPE) -> None:
    selected = context.user_data.get("selected_limitations", set())
    await send(
        "Select any injuries or limitations:",
        reply_markup=_with_back(_build_limitations_keyboard(selected), ASK_LIMITATIONS),
    )


async def handle_ability(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from app.domain.workout.ability import global_ability
    query = update.callback_query
    await query.answer()
    context.user_data.setdefault("exercise_ability", {})
    idx = context.user_data.get("ability_idx", 0)

    if query.data == "abil_skip":
        default = global_ability(context.user_data.get("experience_level", "beginner"))
        for fam in _ABILITY_FAMILIES:
            context.user_data["exercise_ability"].setdefault(fam, default)
        await _prompt_limitations(query.edit_message_text, context)
        return ASK_LIMITATIONS

    level = _ABILITY_LEVEL[query.data.split(":", 1)[1]]
    context.user_data["exercise_ability"][_ABILITY_FAMILIES[idx]] = level
    idx += 1
    context.user_data["ability_idx"] = idx
    if idx >= len(_ABILITY_FAMILIES):
        await _prompt_limitations(query.edit_message_text, context)
        return ASK_LIMITATIONS
    await _prompt_ability(query.edit_message_text, idx)
    return ASK_ABILITY


async def handle_experience(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data['experience_level'] = query.data
    context.user_data['selected_limitations'] = set()
    context.user_data["ability_idx"] = 0
    context.user_data["exercise_ability"] = {}
    await _prompt_ability(query.edit_message_text, 0)
    return ASK_ABILITY


async def handle_limitations_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Toggle a limitation option on/off."""
    query = update.callback_query
    await query.answer()

    opt = query.data[len("lim_toggle_"):]
    selected: set = context.user_data.get('selected_limitations', set())

    if opt == "none":
        selected = {"none"} if "none" not in selected else set()
    else:
        selected.discard("none")
        if opt in selected:
            selected.discard(opt)
        else:
            selected.add(opt)

    context.user_data['selected_limitations'] = selected
    await query.edit_message_reply_markup(
        reply_markup=_with_back(_build_limitations_keyboard(selected), ASK_LIMITATIONS))
    return ASK_LIMITATIONS


async def handle_limitations_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Confirm limitation selection and advance to email step (or ask for 'Other' description)."""
    query = update.callback_query
    await query.answer()

    selected: set = context.user_data.get('selected_limitations', set())

    if "other" in selected:
        selected.discard("other")
        context.user_data['limitations'] = sorted(s for s in selected if s != "none")
        context.user_data['_ask_limitations_other'] = True
        await query.edit_message_text(
            "Please describe your limitation in one sentence (e.g. 'recovering from ankle sprain'):",
            reply_markup=_with_back(InlineKeyboardMarkup([]), ASK_LIMITATIONS_OTHER),
        )
        return ASK_LIMITATIONS_OTHER

    context.user_data['_ask_limitations_other'] = False        # idempotent: always set
    context.user_data.pop('limitations_notes', None)            # drop stale 'other' note on replay
    if "none" in selected or not selected:
        context.user_data['limitations'] = []
    else:
        context.user_data['limitations'] = sorted(selected)

    await _prompt_baseline(query.edit_message_text, "SQUAT", back_state=ASK_BASE_SQUAT)
    return ASK_BASE_SQUAT


async def handle_limitations_other(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store free-text limitation note and proceed to baseline intake."""
    context.user_data['limitations_notes'] = update.message.text.strip()
    await _prompt_baseline(update.message.reply_text, "SQUAT", back_state=ASK_BASE_SQUAT)
    return ASK_BASE_SQUAT


async def handle_limitations(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Legacy free-text fallback for limitations (kept for backwards compat)."""
    text = update.message.text.strip().lower()
    context.user_data['limitations'] = [] if text == "none" else [l.strip() for l in text.split(",")]
    await _prompt_baseline(update.message.reply_text, "SQUAT", back_state=ASK_BASE_SQUAT)
    return ASK_BASE_SQUAT


# ── Intake back navigation (SP-A C3) ──────────────────────────────────────────

def _with_back(markup: InlineKeyboardMarkup, leaving) -> InlineKeyboardMarkup:
    """Append a Back row that encodes the state being left."""
    rows = list(markup.inline_keyboard)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"intake_back:{leaving}")])
    return InlineKeyboardMarkup(rows)


def _intake_predecessor(leaving, context: ContextTypes.DEFAULT_TYPE):
    """Return the state that precedes `leaving` in the intake flow."""
    # Normalize: callback_data is always a string, but int-valued states
    # (ASK_AVATAR=0, ASK_DAYS=1, ASK_EXPERIENCE=2, ASK_LIMITATIONS=3, ASK_EMAIL=4)
    # arrive as their str representation and must be coerced back.
    if isinstance(leaving, str) and leaving.lstrip("-").isdigit():
        leaving = int(leaving)

    if leaving == ASK_EQUIPMENT:
        return ASK_DAYS
    if leaving in (ASK_EQUIPMENT_CUSTOM, ASK_EQUIPMENT_PULLUP):
        return ASK_EQUIPMENT
    if leaving == ASK_EXPERIENCE:
        return ASK_EQUIPMENT
    if leaving == ASK_ABILITY:
        return ASK_EXPERIENCE
    if leaving == ASK_LIMITATIONS:
        return ASK_ABILITY
    if leaving == ASK_LIMITATIONS_OTHER:
        return ASK_LIMITATIONS
    if leaving == ASK_BASE_SQUAT:
        return ASK_LIMITATIONS_OTHER if context.user_data.get("_ask_limitations_other") else ASK_LIMITATIONS
    if leaving == ASK_BASE_BENCH:
        return ASK_BASE_SQUAT
    if leaving == ASK_BASE_DEADLIFT:
        return ASK_BASE_BENCH
    if leaving == ASK_EMAIL:
        return ASK_BASE_DEADLIFT
    return ASK_AVATAR


async def _render_intake_step(state, query, context: ContextTypes.DEFAULT_TYPE):
    """Re-render a step pre-filled from committed user_data, and return its state."""
    ud = context.user_data
    if state == ASK_DAYS:
        keyboard = [[InlineKeyboardButton("3 Days", callback_data="3"),
                     InlineKeyboardButton("4 Days", callback_data="4")],
                    [InlineKeyboardButton("5 Days", callback_data="5"),
                     InlineKeyboardButton("6 Days", callback_data="6")]]
        await query.edit_message_text("How many days a week can you train?",
                                      reply_markup=_with_back(InlineKeyboardMarkup(keyboard), ASK_DAYS))
        return ASK_DAYS
    if state == ASK_EQUIPMENT:
        await query.edit_message_text("What equipment do you have access to?",
                                      reply_markup=_with_back(_equipment_preset_keyboard(), ASK_EQUIPMENT))
        return ASK_EQUIPMENT
    if state == ASK_EXPERIENCE:
        await _prompt_experience(query.edit_message_text)
        return ASK_EXPERIENCE
    if state == ASK_ABILITY:
        # clamp: after the 6th answer ability_idx == len(families); re-prompt the last family
        idx = min(ud.get("ability_idx", 0), len(_ABILITY_FAMILIES) - 1)
        await _prompt_ability(query.edit_message_text, idx)
        return ASK_ABILITY
    if state == ASK_LIMITATIONS:
        await _prompt_limitations(query.edit_message_text, context)
        return ASK_LIMITATIONS
    if state == ASK_LIMITATIONS_OTHER:
        await query.edit_message_text(
            "Please describe your limitation in one sentence (e.g. 'recovering from ankle sprain'):",
            reply_markup=_with_back(InlineKeyboardMarkup([]), ASK_LIMITATIONS_OTHER))
        return ASK_LIMITATIONS_OTHER
    if state in (ASK_BASE_SQUAT, ASK_BASE_BENCH, ASK_BASE_DEADLIFT):
        lift = {ASK_BASE_SQUAT: "SQUAT", ASK_BASE_BENCH: "BENCH PRESS",
                ASK_BASE_DEADLIFT: "DEADLIFT"}[state]
        await _prompt_baseline(query.edit_message_text, lift, back_state=state)
        return state
    # Fallback: re-render avatar step (no Back button at the first step)
    keyboard = [[InlineKeyboardButton("Powerlifter", callback_data="powerlifter")],
                [InlineKeyboardButton("Powerbuilder", callback_data="powerbuilder")],
                [InlineKeyboardButton("General Fitness", callback_data="gen_pop")]]
    await query.edit_message_text("What is your primary training goal?",
                                  reply_markup=InlineKeyboardMarkup(keyboard))
    return ASK_AVATAR


async def handle_intake_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Go back one intake step (forward-replay model). The state being LEFT is encoded
    in callback_data as 'intake_back:<STATE>'; we compute its predecessor from
    context.user_data and re-render that step pre-filled."""
    query = update.callback_query
    await query.answer()
    leaving = query.data.split(":", 1)[1]
    target = _intake_predecessor(leaving, context)
    return await _render_intake_step(target, query, context)


# ── Baseline-lift handlers (A.4) ──────────────────────────────────────────────

def _baseline_keyboard(back_state=None) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("Skip", callback_data="base_skip")]]
    if back_state is not None:
        rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"intake_back:{back_state}")])
    return InlineKeyboardMarkup(rows)


async def _prompt_baseline(target, lift: str, back_state=None) -> None:
    await target(
        f"Optional — your best recent {lift} set? Reply like 100x5 (weight×reps, "
        f"reps ≤ 10), or tap Skip.",
        reply_markup=_baseline_keyboard(back_state=back_state),
    )


# Maps a baseline field to the state that re-asks it (used on parse failure).
_CURRENT_BASELINE_STATE = {
    "squat_e1rm": ASK_BASE_SQUAT,
    "bench_e1rm": ASK_BASE_BENCH,
    "deadlift_e1rm": ASK_BASE_DEADLIFT,
}


async def _store_baseline_and_next(update, context, field: str, next_state, next_lift):
    """Shared logic for the baseline handlers. Stores e1RM (or None) then prompts next."""
    query = update.callback_query
    if query is not None:                 # Skip button
        await query.answer()
        context.user_data[field] = None
        send = query.edit_message_text
    else:                                  # text reply
        parsed = _parse_baseline_set(update.message.text)
        if parsed is None:
            # Re-ask same state — keep current back button (back to predecessor)
            current_state = _CURRENT_BASELINE_STATE[field]
            await update.message.reply_text(
                "Couldn't read that. Use weight×reps, e.g. 100x5 (reps ≤ 10), or tap Skip.",
                reply_markup=_baseline_keyboard(back_state=current_state),
            )
            return current_state   # re-ask same state
        weight, reps = parsed
        from app.domain.workout.loadseed import brzycki_e1rm
        context.user_data[field] = round(brzycki_e1rm(weight, reps), 1)
        send = update.message.reply_text
    if next_lift is not None:
        # next_state is the state we're moving TO — that's the back_state for that step
        await _prompt_baseline(send, next_lift, back_state=next_state)
    else:
        # Email prompt — add a back-only keyboard so user can go back to deadlift
        await send(
            "Almost there! What's your email address? (We'll send your plan PDF here.)",
            reply_markup=_with_back(InlineKeyboardMarkup([]), ASK_EMAIL),
        )
    return next_state


async def handle_base_squat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await _store_baseline_and_next(update, context, "squat_e1rm", ASK_BASE_BENCH, "BENCH PRESS")


async def handle_base_bench(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await _store_baseline_and_next(update, context, "bench_e1rm", ASK_BASE_DEADLIFT, "DEADLIFT")


async def handle_base_deadlift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await _store_baseline_and_next(update, context, "deadlift_e1rm", ASK_EMAIL, None)


async def handle_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    email = update.message.text.strip()
    context.user_data['email'] = email

    updating = context.user_data.get('update_profile_mode', False)
    # Post-verify intake stashes the real client_id; otherwise look up by chat binding.
    intake_client_id = context.user_data.get('intake_client_id')
    client = auth_roles.get_authenticated_client(update.effective_chat.id)
    client_id = intake_client_id or (client.client_id if client else None)
    if client_id is None:
        await update.message.reply_text(
            "Your chat isn't linked to an account yet. Tap /start → Subscribe to pay, "
            "or /start → I have an account already to log in with your access code."
        )
        return ConversationHandler.END

    # If the row was created at pay_verify, it already exists — treat as update.
    with Session(engine, expire_on_commit=False) as session:
        existing = session.get(ClientProfile, client_id)
    if existing is not None and not updating:
        updating = True

    with Session(engine, expire_on_commit=False) as session:
        first_name = update.effective_user.first_name or ""
        if updating:
            profile = session.get(ClientProfile, client_id)
            if profile:
                profile.avatar = context.user_data.get('avatar', profile.avatar)
                profile.training_days = context.user_data.get('days', profile.training_days)
                profile.experience_level = context.user_data.get('experience_level', profile.experience_level)
                profile.limitations = context.user_data.get('limitations', profile.limitations)
                profile.email = email
                profile.name = first_name
                profile.limitations_notes = context.user_data.get('limitations_notes', profile.limitations_notes)
                if context.user_data.get('squat_e1rm') is not None:
                    profile.squat_e1rm = context.user_data['squat_e1rm']
                if context.user_data.get('bench_e1rm') is not None:
                    profile.bench_e1rm = context.user_data['bench_e1rm']
                if context.user_data.get('deadlift_e1rm') is not None:
                    profile.deadlift_e1rm = context.user_data['deadlift_e1rm']
                if context.user_data.get('available_equipment'):
                    profile.available_equipment = floor_equipment(context.user_data['available_equipment'])
                else:
                    profile.available_equipment = profile.available_equipment or ["full_gym"]
                if context.user_data.get('exercise_ability'):
                    profile.exercise_ability = context.user_data['exercise_ability']
                session.add(profile)
                session.commit()
                session.refresh(profile)
            else:
                updating = False

        if not updating:
            await update.message.reply_text("⏳ Building your custom protocol... Coach Shoaib will review it shortly!")
            profile = ClientProfile(
                client_id=client_id,
                avatar=context.user_data.get('avatar', 'gen_pop'),
                training_days=context.user_data.get('days', 3),
                experience_level=context.user_data.get('experience_level', 'intermediate'),
                limitations=context.user_data.get('limitations', []),
                available_equipment=floor_equipment(context.user_data.get('available_equipment')),
                week_number=1,
                email=email,
                name=first_name,
                limitations_notes=context.user_data.get('limitations_notes'),
                squat_e1rm=context.user_data.get('squat_e1rm'),
                bench_e1rm=context.user_data.get('bench_e1rm'),
                deadlift_e1rm=context.user_data.get('deadlift_e1rm'),
                exercise_ability=context.user_data.get('exercise_ability'),
            )
            session.add(profile)
            session.commit()

    if updating:
        await update.message.reply_text("✅ Profile updated! Generating a new plan with your changes...")

    await run_generation_and_dispatch(
        context=context,
        client_chat_id=update.effective_chat.id,
        client_user_id=client_id,
        client_first_name=update.effective_user.first_name,
        client_email=email,
        profile=profile,
    )
    return ConversationHandler.END


_AVATAR_LABEL = {
    "powerlifter": "Powerlifter",
    "powerbuilder": "Powerbuilder",
    "gen_pop": "General Fitness",
}


def _upd_pick_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎯 Training goal", callback_data="upd:goal")],
        [InlineKeyboardButton("📅 Days / week", callback_data="upd:days")],
        [InlineKeyboardButton("💪 Experience", callback_data="upd:exp")],
        [InlineKeyboardButton("⚠️ Limitations", callback_data="upd:limit")],
        [InlineKeyboardButton("📧 Email", callback_data="upd:email")],
        [InlineKeyboardButton("🏋️ Equipment", callback_data="upd:equip")],
        [InlineKeyboardButton("🔄 Regenerate plan with current settings", callback_data="upd:regen")],
        [InlineKeyboardButton("✅ Done", callback_data="upd:done")],
    ])


def _upd_summary_line(profile: ClientProfile) -> str:
    return (
        f"Current: *{_AVATAR_LABEL.get(profile.avatar, profile.avatar)}* · "
        f"*{profile.training_days}d/wk* · *{profile.experience_level}* · "
        f"limitations: {', '.join(profile.limitations) if profile.limitations else 'none'} · "
        f"email: {profile.email or '—'} · "
        f"equipment: {', '.join(profile.available_equipment) if profile.available_equipment else 'full_gym'}"
    )


@auth_roles.requires_active_sub
async def start_update_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show a field-picker menu so the client can update one thing at a time."""
    client_id = _current_client_id(update)
    with Session(engine) as session:
        profile = session.get(ClientProfile, client_id)

    if not profile:
        await update.message.reply_text("No profile found. Use /start to create one first.")
        return ConversationHandler.END

    context.user_data["upd_client_id"] = client_id
    context.user_data["upd_dirty"] = False
    await update.message.reply_text(
        f"What would you like to update?\n\n{_upd_summary_line(profile)}",
        parse_mode="Markdown",
        reply_markup=_upd_pick_keyboard(),
    )
    return UPD_PICK


async def _upd_show_menu(query, client_id: str, dirty_note: "str | None" = None) -> None:
    with Session(engine) as session:
        profile = session.get(ClientProfile, client_id)
    if profile is None:
        await query.edit_message_text("Profile vanished. /start to recreate.")
        return
    head = (dirty_note + "\n\n") if dirty_note else ""
    await query.edit_message_text(
        f"{head}What else would you like to update?\n\n{_upd_summary_line(profile)}",
        parse_mode="Markdown",
        reply_markup=_upd_pick_keyboard(),
    )


async def upd_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    choice = query.data.split(":", 1)[1]
    if choice == "done":
        if context.user_data.pop("upd_dirty", False):
            await query.edit_message_text(
                "Saved. Tap /update_profile and pick *🔄 Regenerate plan* if you want a fresh plan.",
                parse_mode="Markdown",
            )
        else:
            await query.edit_message_text("No changes. Have a good one!")
        context.user_data.pop("upd_client_id", None)
        return ConversationHandler.END

    if choice == "regen":
        return await _upd_regen(update, context)

    if choice == "goal":
        await query.edit_message_text(
            "What is your training goal?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Powerlifter", callback_data="upd_goal:powerlifter")],
                [InlineKeyboardButton("Powerbuilder", callback_data="upd_goal:powerbuilder")],
                [InlineKeyboardButton("General Fitness", callback_data="upd_goal:gen_pop")],
                [InlineKeyboardButton("↩ Back", callback_data="upd_goal:back")],
            ]),
        )
        return UPD_AVATAR

    if choice == "days":
        await query.edit_message_text(
            "How many days per week can you train?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("3", callback_data="upd_days:3"),
                 InlineKeyboardButton("4", callback_data="upd_days:4")],
                [InlineKeyboardButton("5", callback_data="upd_days:5"),
                 InlineKeyboardButton("6", callback_data="upd_days:6")],
                [InlineKeyboardButton("↩ Back", callback_data="upd_days:back")],
            ]),
        )
        return UPD_DAYS

    if choice == "exp":
        await query.edit_message_text(
            "What is your experience level?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Beginner", callback_data="upd_exp:beginner")],
                [InlineKeyboardButton("Intermediate", callback_data="upd_exp:intermediate")],
                [InlineKeyboardButton("Advanced", callback_data="upd_exp:advanced")],
                [InlineKeyboardButton("↩ Back", callback_data="upd_exp:back")],
            ]),
        )
        return UPD_EXP

    if choice == "limit":
        context.user_data["selected_limitations"] = set(
            _load_profile_limitations(context.user_data["upd_client_id"])
        )
        await query.edit_message_text(
            "Select any injuries or limitations:",
            reply_markup=_build_limitations_keyboard(context.user_data["selected_limitations"]),
        )
        return UPD_LIM

    if choice == "email":
        await query.edit_message_text(
            "Send your new email address (we'll use it for the plan PDF). Type /cancel to abort."
        )
        return UPD_EMAIL

    if choice == "equip":
        with Session(engine) as session:
            _p = session.get(ClientProfile, context.user_data["upd_client_id"])
        current = set(_p.available_equipment or []) if _p else set()
        # Pre-seed from the client's CURRENT kit so editing adds/removes rather than
        # wiping it. full_gym (wildcard) and bodyweight (implicit) are never checkboxes.
        context.user_data["equip_selected"] = {t for t in current if t not in ("full_gym", "bodyweight")}
        await query.edit_message_text(
            "Check everything you have, then tap Done:",
            reply_markup=_equipment_checklist_keyboard(context.user_data["equip_selected"]),
        )
        return UPD_EQUIPMENT

    return UPD_PICK


def _load_profile_limitations(client_id: str) -> list:
    with Session(engine) as session:
        profile = session.get(ClientProfile, client_id)
    return list(profile.limitations or []) if profile else []


def _save_profile_field(client_id: str, **kwargs) -> None:
    with Session(engine, expire_on_commit=False) as session:
        profile = session.get(ClientProfile, client_id)
        if profile is None:
            return
        for k, v in kwargs.items():
            setattr(profile, k, v)
        session.add(profile)
        session.commit()


async def upd_set_goal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    pick = query.data.split(":", 1)[1]
    client_id = context.user_data["upd_client_id"]
    if pick == "back":
        await _upd_show_menu(query, client_id)
        return UPD_PICK
    _save_profile_field(client_id, avatar=pick)
    context.user_data["upd_dirty"] = True
    await _upd_show_menu(query, client_id, dirty_note=f"✅ Goal set to *{_AVATAR_LABEL.get(pick, pick)}*.")
    return UPD_PICK


async def upd_set_days(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    pick = query.data.split(":", 1)[1]
    client_id = context.user_data["upd_client_id"]
    if pick == "back":
        await _upd_show_menu(query, client_id)
        return UPD_PICK
    _save_profile_field(client_id, training_days=int(pick))
    context.user_data["upd_dirty"] = True
    await _upd_show_menu(query, client_id, dirty_note=f"✅ Training days set to *{pick}/wk*.")
    return UPD_PICK


async def upd_set_exp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    pick = query.data.split(":", 1)[1]
    client_id = context.user_data["upd_client_id"]
    if pick == "back":
        await _upd_show_menu(query, client_id)
        return UPD_PICK
    _save_profile_field(client_id, experience_level=pick)
    context.user_data["upd_dirty"] = True
    await _upd_show_menu(query, client_id, dirty_note=f"✅ Experience set to *{pick}*.")
    return UPD_PICK


async def upd_lim_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    opt = query.data[len("lim_toggle_"):]
    selected: set = context.user_data.get("selected_limitations", set())
    if opt == "none":
        selected = {"none"} if "none" not in selected else set()
    else:
        selected.discard("none")
        if opt in selected:
            selected.discard(opt)
        else:
            selected.add(opt)
    context.user_data["selected_limitations"] = selected
    await query.edit_message_reply_markup(reply_markup=_build_limitations_keyboard(selected))
    return UPD_LIM


async def upd_lim_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    selected: set = context.user_data.get("selected_limitations", set())
    client_id = context.user_data["upd_client_id"]
    if "other" in selected:
        selected.discard("other")
        context.user_data["_upd_lim_pending"] = sorted(s for s in selected if s != "none")
        await query.edit_message_text(
            "Describe your limitation in one sentence (e.g. 'recovering from ankle sprain'):"
        )
        return UPD_LIM_OTHER
    new_limits = [] if ("none" in selected or not selected) else sorted(selected)
    _save_profile_field(client_id, limitations=new_limits, limitations_notes=None)
    context.user_data["upd_dirty"] = True
    label = "none" if not new_limits else ", ".join(new_limits)
    await _upd_show_menu(query, client_id, dirty_note=f"✅ Limitations set to: *{label}*.")
    return UPD_PICK


async def upd_lim_other(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    note = (update.message.text or "").strip()[:200]
    client_id = context.user_data["upd_client_id"]
    base = context.user_data.pop("_upd_lim_pending", [])
    _save_profile_field(client_id, limitations=base, limitations_notes=note)
    context.user_data["upd_dirty"] = True
    with Session(engine) as session:
        profile = session.get(ClientProfile, client_id)
    if profile is None:
        await update.message.reply_text("Profile vanished.")
        return ConversationHandler.END
    await update.message.reply_text(
        f"✅ Limitation note saved.\n\nWhat else would you like to update?\n\n{_upd_summary_line(profile)}",
        parse_mode="Markdown",
        reply_markup=_upd_pick_keyboard(),
    )
    return UPD_PICK


async def upd_set_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    email = (update.message.text or "").strip()
    if not _looks_like_email(email):
        await update.message.reply_text("That doesn't look like an email. Send again or /cancel.")
        return UPD_EMAIL
    client_id = context.user_data["upd_client_id"]
    _save_profile_field(client_id, email=email)
    context.user_data["upd_dirty"] = True
    with Session(engine) as session:
        profile = session.get(ClientProfile, client_id)
    if profile is None:
        await update.message.reply_text("Profile vanished.")
        return ConversationHandler.END
    await update.message.reply_text(
        f"✅ Email updated.\n\nWhat else?\n\n{_upd_summary_line(profile)}",
        parse_mode="Markdown",
        reply_markup=_upd_pick_keyboard(),
    )
    return UPD_PICK


async def upd_equipment_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    query = update.callback_query
    await query.answer()
    tok = query.data[len("equip_toggle_"):]
    selected: set = context.user_data.get("equip_selected", set())
    if tok in selected:
        selected.discard(tok)
    else:
        selected.add(tok)
    context.user_data["equip_selected"] = selected
    await query.edit_message_reply_markup(reply_markup=_equipment_checklist_keyboard(selected))
    return UPD_EQUIPMENT


async def upd_equipment_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    query = update.callback_query
    await query.answer()
    selected = sorted(context.user_data.get("equip_selected", set()))
    tokens = floor_equipment(selected + ["bodyweight"] if selected else [])
    client_id = context.user_data["upd_client_id"]
    _save_profile_field(client_id, available_equipment=tokens)
    context.user_data["upd_dirty"] = True
    await _upd_show_menu(query, client_id, dirty_note=f"✅ Equipment set to: *{', '.join(tokens)}*.")
    return UPD_PICK


async def _upd_regen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    client_id = context.user_data["upd_client_id"]
    with Session(engine) as session:
        profile = session.get(ClientProfile, client_id)
    if profile is None:
        await query.edit_message_text("Profile vanished.")
        return ConversationHandler.END
    await query.edit_message_text("⏳ Generating a fresh plan with your current settings...")
    await run_generation_and_dispatch(
        context=context,
        client_chat_id=update.effective_chat.id,
        client_user_id=client_id,
        client_first_name=update.effective_user.first_name or "",
        client_email=profile.email or "",
        profile=profile,
    )
    context.user_data.pop("upd_client_id", None)
    context.user_data.pop("upd_dirty", None)
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Cancelled. Type /start to begin again.")
    return ConversationHandler.END


# ── CHECK-IN FLOW (free-form, single-turn) ────────────────────────────────────

def _make_llm_client() -> OpenRouterClient:
    """Build an OpenRouterClient from env vars."""
    return OpenRouterClient(
        api_key=os.getenv("OPENROUTER_API_KEY", ""),
        base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        model_id=os.getenv("LLM_MODEL_ID", "google/gemini-2.5-flash"),
    )


def _build_lift_catalog(week: WorkoutWeek) -> list[str]:
    """Lift catalog handed to the extractor. Each entry MUST lead with the
    canonical exercise_id (the schema's `exercise_canonical`, which telemetry is
    matched on), with the display name in parens so the model can map raw
    mentions like "bench" to the id. Passing bare names made the LLM echo names
    that never matched slot.exercise_id, silently dropping all telemetry."""
    return [
        f"{slot.exercise_id} ({slot.exercise_name})"
        for day in week.days
        for slot in day.slots
        if slot.slot_type in ("main_compound", "secondary_compound")
    ]


@auth_roles.requires_assigned_coach
async def start_checkin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    client_id = _current_client_id(update)

    # Check for a resumable in-progress structured check-in (<2h old)
    with Session(engine) as session:
        in_progress = session.exec(
            select(CheckIn).where(
                CheckIn.client_id == client_id,
                CheckIn.structured_progress != None,  # noqa: E711
                CheckIn.extraction_json == None,  # noqa: E711
            ).order_by(CheckIn.created_at.desc())
        ).first()
        if in_progress and in_progress.created_at:
            age_s = (
                datetime.now(timezone.utc)
                - in_progress.created_at.replace(tzinfo=timezone.utc)
            ).total_seconds()
            if age_s < 7200:
                context.user_data["_resume_checkin_id"] = in_progress.id
                keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton("▶️ Resume", callback_data=f"ci_resume:{in_progress.id}"),
                    InlineKeyboardButton("🔄 Start over", callback_data="ci_restart"),
                ]])
                await update.message.reply_text(
                    "You have an unfinished check-in from earlier. Resume or start over?",
                    reply_markup=keyboard,
                )
                return CHECKIN_RESUME

    with Session(engine, expire_on_commit=False) as session:
        # Accept the most recent history regardless of status — a pending plan
        # (awaiting admin approval) is still valid for check-in.
        history = session.exec(
            select(WorkoutHistory)
            .where(WorkoutHistory.client_id == client_id)
            .order_by(WorkoutHistory.week_number.desc())
        ).first()

        if not history:
            await update.message.reply_text("No active plan found. Type /start to generate your first plan!")
            return ConversationHandler.END

        week = WorkoutWeek.model_validate_json(history.workout_json)
        client = session.get(ClientProfile, client_id)

    context.user_data["checkin_history_id"] = history.history_id
    context.user_data["checkin_week_number"] = week.week_number
    context.user_data["checkin_messages"] = []
    context.user_data["checkin_lift_catalog"] = _build_lift_catalog(week)
    context.user_data["checkin_prior_profile"] = (
        client.model_dump_json(indent=2) if client else ""
    )

    # Collect main_compound slots for structured mode; skip already-logged ones
    all_main_slots = _select_checkin_slots(week)
    already_logged = [(d, s) for d, s in all_main_slots if s.actual_rpe is not None]
    main_slots = [(d, s) for d, s in all_main_slots if s.actual_rpe is None]

    if already_logged:
        logged_names = ", ".join(s.exercise_name for _, s in already_logged)
        await update.message.reply_text(
            f"Already logged: {logged_names}. Skipping those — use /log to edit."
        )

    if main_slots:
        # Structured mode: iterate per exercise
        context.user_data["checkin_structured_slots"] = _checkin_slot_dicts(main_slots)
        context.user_data["checkin_current_slot_idx"] = 0
        context.user_data["checkin_structured_results"] = {}

        first = context.user_data["checkin_structured_slots"][0]
        return await _prompt_checkin_slot(update.message.reply_text, first, week.week_number)

    # If all main slots were already logged, go straight to general notes
    if all_main_slots and not main_slots:
        context.user_data["checkin_structured_slots"] = []
        context.user_data["checkin_structured_results"] = {}
        await update.message.reply_text(
            "All main lifts are already logged. Any other notes — sleep, energy, "
            "life stress? (or type /skip)"
        )
        return CHECKIN_GENERAL

    # Fallback: free-text mode
    await update.message.reply_text(
        f"📋 *Week {week.week_number} Check-in*\n\n"
        "Tell me about your week — how sessions went, any weights/RPEs, "
        "pain, sleep, energy, life stuff. Whatever feels relevant.\n\n"
        "Send as many messages as you like, then type /done when finished. "
        "I'll also wrap up automatically after 90 seconds of silence.",
        parse_mode="Markdown",
    )
    return CHECKIN_COLLECTING


async def handle_checkin_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle Resume / Start-over choice for an in-progress structured check-in."""
    query = update.callback_query
    await query.answer()

    if query.data == "ci_restart":
        await query.edit_message_text("Starting fresh check-in...")
        context.user_data.pop("_resume_checkin_id", None)
        # Re-invoke start_checkin via a pseudo-update — clear resume state and let
        # the user re-trigger /checkin. For now just end the conversation.
        await query.message.reply_text("Type /checkin to start a fresh check-in.")
        return ConversationHandler.END

    checkin_id = int(query.data.split(":")[1])
    with Session(engine) as session:
        ci = session.get(CheckIn, checkin_id)
        if not ci or not ci.structured_progress:
            await query.edit_message_text("Couldn't find the saved progress. Starting fresh.")
            return ConversationHandler.END
        progress = ci.structured_progress

    context.user_data.update(progress)
    idx = context.user_data.get("checkin_current_slot_idx", 0)
    slots = context.user_data.get("checkin_structured_slots", [])
    if idx < len(slots):
        slot = slots[idx]
        return await _prompt_checkin_slot(query.edit_message_text, slot)

    await query.edit_message_text("All lifts already logged. Any final notes? (or /skip)")
    return CHECKIN_GENERAL


def _persist_checkin_progress(client_id: str, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Save structured check-in progress to DB so it can be resumed."""
    progress = {
        k: context.user_data[k]
        for k in ("checkin_structured_slots", "checkin_structured_results",
                  "checkin_current_slot_idx", "checkin_history_id", "checkin_week_number",
                  "checkin_prior_profile", "checkin_lift_catalog", "checkin_messages")
        if k in context.user_data
    }
    with Session(engine) as session:
        existing = session.exec(
            select(CheckIn).where(
                CheckIn.client_id == client_id,
                CheckIn.extraction_json == None,  # noqa: E711
            ).order_by(CheckIn.created_at.desc())
        ).first()
        if existing:
            existing.structured_progress = progress
            session.add(existing)
        else:
            session.add(CheckIn(
                client_id=client_id,
                raw_text="",
                structured_progress=progress,
                created_at=datetime.now(timezone.utc),
            ))
        session.commit()


async def handle_checkin_collecting(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Accumulate free-form messages from the client."""
    text = update.message.text.strip()
    context.user_data.setdefault("checkin_messages", []).append(text)
    return CHECKIN_COLLECTING


async def handle_checkin_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Client typed /done — process the accumulated messages."""
    return await _process_checkin(update, context)


async def handle_checkin_timeout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """90-second inactivity timeout — process whatever was collected."""
    if context.user_data.get("checkin_messages"):
        return await _process_checkin(update, context)
    return ConversationHandler.END


async def handle_checkin_clarifying(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Client answered the clarifying questions — merge and finalise."""
    context.user_data.setdefault("checkin_messages", []).append(update.message.text.strip())
    return await _process_checkin(update, context, skip_clarify=True)


def _structured_advance(context: ContextTypes.DEFAULT_TYPE) -> "dict | None":
    """Move to the next structured slot. Returns the next slot dict, or None if done."""
    idx = context.user_data.get("checkin_current_slot_idx", 0) + 1
    context.user_data["checkin_current_slot_idx"] = idx
    slots = context.user_data.get("checkin_structured_slots", [])
    return slots[idx] if idx < len(slots) else None


async def handle_structured_weight(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Accept weight for the current main lift."""
    try:
        weight = float(update.message.text.strip())
    except ValueError:
        slot = context.user_data["checkin_structured_slots"][context.user_data["checkin_current_slot_idx"]]
        await update.message.reply_text(
            f"Please enter a number in kg (e.g. `100`) for *{slot['exercise_name']}*.",
            parse_mode="Markdown",
        )
        return CHECKIN_EX_WEIGHT

    idx = context.user_data["checkin_current_slot_idx"]
    slot = context.user_data["checkin_structured_slots"][idx]
    context.user_data["checkin_structured_results"].setdefault(slot["exercise_id"], {})["weight"] = weight

    await update.message.reply_text(
        f"*{slot['exercise_name']}* — what was your top-set RPE? (1–10, where 10 = absolute max)",
        parse_mode="Markdown",
    )
    return CHECKIN_EX_RPE


async def handle_structured_rpe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Accept RPE for the current main lift."""
    try:
        rpe_val = float(update.message.text.strip())
        if not (1 <= rpe_val <= 10):
            raise ValueError
    except ValueError:
        slot = context.user_data["checkin_structured_slots"][context.user_data["checkin_current_slot_idx"]]
        await update.message.reply_text(
            f"Please enter an RPE between 1 and 10 for *{slot['exercise_name']}*.",
            parse_mode="Markdown",
        )
        return CHECKIN_EX_RPE

    idx = context.user_data["checkin_current_slot_idx"]
    slot = context.user_data["checkin_structured_slots"][idx]
    context.user_data["checkin_structured_results"].setdefault(slot["exercise_id"], {})["rpe"] = rpe_val

    # Persist progress so check-in can be resumed
    _persist_checkin_progress(_current_client_id(update), context)

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ No pain", callback_data="pain_none"),
        InlineKeyboardButton("⚠️ Some discomfort", callback_data="pain_mild"),
        InlineKeyboardButton("🚨 Sharp pain", callback_data="pain_sharp"),
    ]])
    await update.message.reply_text(
        f"*{slot['exercise_name']}* — any pain or discomfort?",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )
    return CHECKIN_EX_PAIN


async def handle_structured_pain(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Accept pain flag for the current main lift; then ask about set adherence."""
    query = update.callback_query
    await query.answer()

    idx = context.user_data["checkin_current_slot_idx"]
    slot = context.user_data["checkin_structured_slots"][idx]
    context.user_data["checkin_structured_results"].setdefault(slot["exercise_id"], {})["pain"] = query.data

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ All sets", callback_data="sets_all"),
        InlineKeyboardButton("⚠️ Missed 1–2", callback_data="sets_partial"),
        InlineKeyboardButton("❌ Cut short", callback_data="sets_cut"),
    ]])
    await query.edit_message_text(
        f"*{slot['exercise_name']}* — did you hit all your sets?",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )
    return CHECKIN_EX_SETS


async def handle_structured_sets(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Accept set adherence for the current main lift; advance to next slot or general note."""
    query = update.callback_query
    await query.answer()

    idx = context.user_data["checkin_current_slot_idx"]
    slot = context.user_data["checkin_structured_slots"][idx]
    context.user_data["checkin_structured_results"].setdefault(slot["exercise_id"], {})["sets"] = query.data

    next_slot = _structured_advance(context)
    if next_slot:
        return await _prompt_checkin_slot(query.edit_message_text, next_slot)

    await query.edit_message_text(
        "Almost done! Any other notes — sleep, energy, life stress, or anything else "
        "you want your coach to know? (or type /skip)"
    )
    return CHECKIN_GENERAL


async def handle_structured_general(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Accept general notes and finalize structured check-in."""
    text = update.message.text.strip()
    if not text.startswith("/"):
        context.user_data.setdefault("checkin_messages", []).append(text)

    # Synthesize structured results into the checkin_messages list
    results = context.user_data.get("checkin_structured_results", {})
    slots = context.user_data.get("checkin_structured_slots", [])
    for slot_info in slots:
        ex_id = slot_info["exercise_id"]
        ex_name = slot_info["exercise_name"]
        res = results.get(ex_id, {})
        w = res.get("weight")
        r = res.get("rpe")
        p = res.get("pain", "pain_none")
        if w is not None or r is not None:
            pain_str = " (some discomfort)" if p == "pain_mild" else (" (sharp pain!)" if p == "pain_sharp" else "")
            line = f"{ex_name}: {w}kg @ RPE {r}{pain_str}" if w and r else f"{ex_name}: recorded"
            context.user_data["checkin_messages"].append(line)

    return await _process_checkin(update, context, skip_clarify=True)


async def _process_checkin(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    skip_clarify: bool = False,
) -> int:
    """Extract, optionally clarify, write telemetry, run generation."""
    client_id = _current_client_id(update)
    raw_text = "\n".join(context.user_data.get("checkin_messages", []))

    if not raw_text.strip():
        await update.message.reply_text("No check-in text received. Type /checkin to try again.")
        return ConversationHandler.END

    await update.message.reply_text("✅ Got it — running extraction, back in a moment...")

    lift_catalog: list[str] = context.user_data.get("checkin_lift_catalog", [])
    prior_profile: str = context.user_data.get("checkin_prior_profile", "")

    try:
        llm = _make_llm_client()
        extraction = extract_checkin(llm, raw_text, lift_catalog, prior_profile)
    except Exception as exc:
        logging.getLogger(__name__).warning("extract_checkin failed: %s", exc)
        extraction = None

    # Ask clarifying questions (only once)
    if (
        not skip_clarify
        and extraction is not None
        and extraction.clarifying_questions_for_client
    ):
        questions_text = "\n".join(
            f"{i+1}. {q}"
            for i, q in enumerate(extraction.clarifying_questions_for_client[:3])
        )
        await update.message.reply_text(
            f"Just a couple of quick questions:\n\n{questions_text}\n\n"
            "Reply with your answers and I'll finish up.",
        )
        return CHECKIN_CLARIFYING

    # Extraction failed entirely — do NOT advance the week or discard telemetry.
    # The raw messages are already persisted (CheckIn row); tell the client to retry.
    if extraction is None:
        logging.getLogger(__name__).warning(
            "checkin_extraction_failed client_id=%s raw=%r", client_id, raw_text[:500]
        )
        await update.message.reply_text(
            "⚠️ I couldn't read your check-in just now. Your progress is saved — "
            "please type /checkin and try again in a moment."
        )
        return ConversationHandler.END

    # Write telemetry back onto the workout JSON
    with Session(engine, expire_on_commit=False) as session:
        history = session.get(WorkoutHistory, context.user_data["checkin_history_id"])
        if history is None:
            logging.warning("client_not_found: WorkoutHistory %s", context.user_data.get("checkin_history_id"))
            return ConversationHandler.END
        prior_week = WorkoutWeek.model_validate_json(history.workout_json)

        if extraction and extraction.exercises:
            week_obj = WorkoutWeek.model_validate_json(history.workout_json)
            for ex_fb in extraction.exercises:
                if ex_fb.exercise_canonical is None:
                    continue
                for day in week_obj.days:
                    for slot in day.slots:
                        if slot.exercise_id == ex_fb.exercise_canonical:
                            if ex_fb.actual_load_kg is not None:
                                slot.actual_weight = ex_fb.actual_load_kg
                            if ex_fb.rpe is not None:
                                slot.actual_rpe = ex_fb.rpe
            history.workout_json = week_obj.model_dump_json()
            session.add(history)
            session.commit()
            prior_week = week_obj

        client = session.get(ClientProfile, client_id)
        if client is None:
            logging.warning("client_not_found: %s", client_id)
            return ConversationHandler.END
        client.week_number += 1
        session.add(client)
        session.commit()
        session.refresh(client)
        email = client.email or "client@example.com"

    # Derive plan delta and decide force_deload
    force_deload = False
    delta_notes_text = ""
    if extraction is not None:
        delta = derive_plan_delta(extraction, prior_week)
        force_deload = delta.trigger_deload
        if delta.notes:
            delta_notes_text = "\n".join(f"• {n}" for n in delta.notes)

    # Send single combined check-in message to admin
    admin_chat_id = _admin_chat_id()
    if admin_chat_id is not None:
        summary = _build_client_summary(client_id)

        try:
            digest = render_digest(
                llm,
                raw_text,
                extraction,
                update.effective_user.first_name,
                context.user_data.get("checkin_week_number", client.week_number),
            ) if extraction is not None else raw_text
        except Exception:
            digest = raw_text

        # Action badge — priority: pain/adherence > deload > high-RPE > normal
        pain_flags = (extraction.pain_flags if extraction else None) or []
        sets_cut = any(
            v.get("sets") == "sets_cut"
            for v in context.user_data.get("checkin_structured_results", {}).values()
        )
        new_week_rpe = context.user_data.get("checkin_week_number", client.week_number)
        prior_avg_rpe: "float | None" = None
        if extraction and extraction.exercises:
            rpes = [ex.rpe for ex in extraction.exercises if ex.rpe is not None]
            prior_avg_rpe = sum(rpes) / len(rpes) if rpes else None
        new_avg_rpe_badge: "float | None" = None
        if prior_avg_rpe is not None:
            new_avg_rpe_badge = prior_avg_rpe  # approximation for jump detection

        if pain_flags or sets_cut:
            action_badge = "🔴"
        elif force_deload or (new_week_rpe % 5 == 0):
            action_badge = "🟢"
        elif (
            prior_avg_rpe is not None
            and new_avg_rpe_badge is not None
            and new_avg_rpe_badge - prior_avg_rpe > 1.5
        ):
            action_badge = "🔴"
        else:
            action_badge = "🟡"

        admin_text = (
            f"{action_badge} *Check-in — Week {prior_week.week_number}*\n\n"
            f"{summary}\n\n"
            f"────────────────────\n"
            f"*Coach digest:*\n{digest}"
        )
        if delta_notes_text:
            admin_text += f"\n\n*Auto-regulation:*\n{delta_notes_text}"
        if force_deload:
            admin_text += "\n\n⚠️ *Reactive deload triggered for next week.*"

        if len(admin_text) > 4000:
            admin_text = admin_text[:3950] + "\n…[truncated]"

        await safe_send_markdown(context.bot, admin_chat_id, admin_text)

    await run_generation_and_dispatch(
        context=context,
        client_chat_id=update.effective_chat.id,
        client_user_id=client_id,
        client_first_name=update.effective_user.first_name,
        client_email=email,
        profile=client,
        prior_workout=prior_week,
        force_deload=force_deload,
    )

    keyboard = [[
        InlineKeyboardButton("✅ Done", callback_data="pm_done"),
        InlineKeyboardButton("📋 Send update", callback_data="pm_updates"),
        InlineKeyboardButton("📹 Form check", callback_data="pm_formcheck"),
    ]]
    await update.message.reply_text(
        "What would you like to do next?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return POST_MENU


# ── POST-MENU ──────────────────────────────────────────────────────────────────

async def handle_post_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "pm_done":
        await query.edit_message_text("All done! Keep up the great work 💪")
        return ConversationHandler.END

    if query.data == "pm_updates":
        await query.edit_message_text(
            "What would you like your coach to know? Type your message below."
        )
        return UPDATES_TEXT

    if query.data == "pm_formcheck":
        return await _ask_formcheck_exercise(query, context, edit=True)

    return ConversationHandler.END


async def handle_updates_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    admin_chat_id = _admin_chat_id()
    if admin_chat_id is not None:
        summary = _build_client_summary(_current_client_id(update))
        admin_text = (
            f"📬 *Message from client*\n\n"
            f"{summary}\n\n"
            f"────────────────────\n"
            f"*Question / message:*\n{update.message.text.strip()}"
        )
        await safe_send_markdown(context.bot, admin_chat_id, admin_text)
    await update.message.reply_text("✅ Message sent to your coach!")
    return ConversationHandler.END


# ── FORM CHECK FLOW ────────────────────────────────────────────────────────────

async def _ask_formcheck_exercise(msg_or_query, context, edit: bool) -> int:
    """Build exercise list from the client's current plan and present as inline keyboard."""
    chat_id = msg_or_query.message.chat_id if hasattr(msg_or_query, "message") else msg_or_query.chat.id
    client = auth_roles.get_authenticated_client(chat_id)
    if client is None:
        text = "Your chat isn't linked to an account yet. Tap /start to subscribe or log in."
        if edit:
            await msg_or_query.edit_message_text(text)
        else:
            await msg_or_query.message.reply_text(text)
        return ConversationHandler.END
    client_id = client.client_id

    exercises = []
    with Session(engine, expire_on_commit=False) as session:
        history = session.exec(
            select(WorkoutHistory)
            .where(WorkoutHistory.client_id == client_id, WorkoutHistory.status == "active")
            .order_by(WorkoutHistory.week_number.desc())
        ).first()
        if history:
            week = WorkoutWeek.model_validate_json(history.workout_json)
            seen = set()
            for day in week.days:
                for slot in day.slots:
                    if slot.exercise_id not in seen:
                        exercises.append((slot.exercise_id, slot.exercise_name))
                        seen.add(slot.exercise_id)

    if not exercises:
        text = "No active plan found. Generate a plan first with /start."
        if edit:
            await msg_or_query.edit_message_text(text)
        else:
            await msg_or_query.message.reply_text(text)
        return ConversationHandler.END

    # Up to 5 exercises per row, max 20 exercises shown
    keyboard = []
    for i in range(0, min(len(exercises), 20), 2):
        row = []
        for ex_id, ex_name in exercises[i:i+2]:
            short = ex_name[:28]
            row.append(InlineKeyboardButton(short, callback_data=f"fc_ex_{ex_id}"))
        keyboard.append(row)

    context.user_data["formcheck_exercises"] = {ex_id: ex_name for ex_id, ex_name in exercises}
    text = "📹 *Form Check*\n\nWhich exercise would you like help with?"
    if edit:
        await msg_or_query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await msg_or_query.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    return FORMCHECK_EXERCISE


async def handle_formcheck_exercise(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    ex_id = query.data.replace("fc_ex_", "")
    ex_name = context.user_data.get("formcheck_exercises", {}).get(ex_id, ex_id)
    context.user_data["formcheck_exercise_id"] = ex_id
    context.user_data["formcheck_exercise_name"] = ex_name

    keyboard = [[
        InlineKeyboardButton("💡 How to do it (tips)", callback_data="fc_mode_tips"),
        InlineKeyboardButton("🎥 Send a video for review", callback_data="fc_mode_video"),
    ]]
    await query.edit_message_text(
        f"*{ex_name}*\n\nHow would you like help?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return FORMCHECK_MODE


async def handle_formcheck_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    ex_name = context.user_data.get("formcheck_exercise_name", "the exercise")

    if query.data == "fc_mode_tips":
        await query.edit_message_text(f"⏳ Generating technique tips for *{ex_name}*...", parse_mode="Markdown")

        client = auth_roles.get_authenticated_client(query.message.chat_id)
        client_id = client.client_id if client else ""
        with Session(engine, expire_on_commit=False) as session:
            profile = session.get(ClientProfile, client_id) if client_id else None
            exp = profile.experience_level if profile else "intermediate"
            avatar = profile.avatar if profile else "gen_pop"

        llm = FlashCommunicationService()
        tips = llm.generate_exercise_tips(ex_name, exp, avatar)

        # Store pending tip for admin confirmation
        tip_uuid = str(uuid.uuid4())
        context.application.bot_data.setdefault("pending_tips", {})[tip_uuid] = {
            "client_chat_id": query.message.chat_id,
            "client_name": query.from_user.first_name,
            "exercise_name": ex_name,
            "tips": tips,
        }

        admin_chat_id = _admin_chat_id()
        if admin_chat_id is not None:
            keyboard = [[
                InlineKeyboardButton("✅ Send to client", callback_data=f"fc_confirm_{tip_uuid}"),
                InlineKeyboardButton("✏️ Edit reply", callback_data=f"fc_edit_{tip_uuid}"),
            ]]
            await context.bot.send_message(
                chat_id=admin_chat_id,
                text=(
                    f"💡 Form tips request from *{query.from_user.first_name}* "
                    f"(@{query.from_user.username or client_id}) — *{ex_name}*\n\n"
                    f"Generated tips:\n{tips}"
                ),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )

        await query.edit_message_text(
            f"✅ Tips for *{ex_name}* have been sent to Coach Shoaib for review. "
            "You'll receive them shortly!",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    if query.data == "fc_mode_video":
        await query.edit_message_text(
            f"🎥 Please send your *{ex_name}* video now. "
            "It will be forwarded directly to Coach Shoaib for feedback.",
            parse_mode="Markdown",
        )
        return FORMCHECK_VIDEO

    return ConversationHandler.END


async def handle_formcheck_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    ex_name = context.user_data.get("formcheck_exercise_name", "exercise")
    fallback_id = _current_client_id(update)

    if not update.message.video and not update.message.document:
        await update.message.reply_text("Please send a video file. Try again or /cancel.")
        return FORMCHECK_VIDEO

    # Resolve actual client_id via ChatBinding (Phase B/C); fall back to tg user id.
    client = auth_roles.get_authenticated_client(update.effective_chat.id)
    client_id = client.client_id if client else fallback_id
    review_recipient = _resolve_review_recipient(client_id) if client else _admin_chat_id()
    if review_recipient is None:
        await update.message.reply_text("Could not reach your coach right now. Try again later.")
        return ConversationHandler.END

    # Forward the video
    caption = (
        f"🎥 Form check: *{ex_name}*\n"
        f"From: {update.effective_user.first_name} "
        f"(@{update.effective_user.username or client_id})\n\n"
        "Reply to this message with your feedback to send it directly to the client."
    )
    if update.message.video:
        fwd = await context.bot.send_video(
            chat_id=review_recipient,
            video=update.message.video.file_id,
            caption=caption,
            parse_mode="Markdown",
        )
    else:
        fwd = await context.bot.send_document(
            chat_id=review_recipient,
            document=update.message.document.file_id,
            caption=caption,
            parse_mode="Markdown",
        )

    # Map forwarded message ID → routing info so the coach's reply finds the client.
    context.application.bot_data.setdefault("video_reviews", {})[fwd.message_id] = {
        "client_chat_id": update.effective_chat.id,
        "client_id": client_id,
        "client_name": update.effective_user.first_name,
        "exercise_name": ex_name,
    }

    await update.message.reply_text(
        "✅ Video sent to your coach. You'll receive feedback here once they review it."
    )
    return ConversationHandler.END


# ── NUTRITION INTAKE FLOW ─────────────────────────────────────────────────────

def _dn(context: ContextTypes.DEFAULT_TYPE) -> dict:
    if "dn_data" not in context.user_data:
        context.user_data["dn_data"] = {}
    return context.user_data["dn_data"]


@auth_roles.requires_assigned_coach
async def start_diet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["dn_data"] = {}
    # /diet quick — skip biometrics, use safe defaults
    if context.args and context.args[0].lower() == "quick":
        context.user_data["dn_data"] = {
            "weight_kg": 80.0,
            "height_cm": 175.0,
            "age": 30,
            "sex": "male",
            "goal": "maintain",
            "aggressiveness": "moderate",
            "activity_level": "moderately_active",
        }
        await update.message.reply_text(
            "⚡ *Quick diet setup* — using safe defaults for biometrics.\n\n"
            "*Step 6 of 18:* What is your primary nutrition goal?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔥 Fat Loss", callback_data="dn_goal_fat_loss"),
                 InlineKeyboardButton("💪 Lean Bulk", callback_data="dn_goal_lean_bulk")],
                [InlineKeyboardButton("📈 Bulk", callback_data="dn_goal_bulk"),
                 InlineKeyboardButton("⚖️ Recomp", callback_data="dn_goal_recomp")],
                [InlineKeyboardButton("✅ Maintain", callback_data="dn_goal_maintain")],
            ]),
        )
        return DN_GOAL

    await update.message.reply_text(
        "🥗 *Nutrition Profile Setup* (18 questions)\n\n"
        "Quick Q&A to build your personalised plan — takes ~2 minutes.\n\n"
        "*Step 1 of 18:* What is your current bodyweight? (kg, e.g. `82.5`)",
        parse_mode="Markdown",
    )
    return DN_WEIGHT


async def dn_weight(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        _dn(context)["weight_kg"] = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Please enter a number in kg (e.g. `82.5`)", parse_mode="Markdown")
        return DN_WEIGHT
    await update.message.reply_text("*Step 2 of 18:* What is your height? (cm, e.g. `178`)", parse_mode="Markdown")
    return DN_HEIGHT


async def dn_height(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        _dn(context)["height_cm"] = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Please enter height in cm (e.g. `178`)")
        return DN_HEIGHT
    await update.message.reply_text("*Step 3 of 18:* How old are you? (e.g. `28`)", parse_mode="Markdown")
    return DN_AGE


async def dn_age(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        _dn(context)["age"] = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Please enter a whole number (e.g. `28`)")
        return DN_AGE
    keyboard = [[
        InlineKeyboardButton("♂️ Male", callback_data="dn_sex_male"),
        InlineKeyboardButton("♀️ Female", callback_data="dn_sex_female"),
    ]]
    await update.message.reply_text(
        "*Step 4 of 18:* What is your biological sex? (used for calorie calculations)",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return DN_SEX


async def dn_sex(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    _dn(context)["sex"] = query.data.replace("dn_sex_", "")
    await query.edit_message_text(
        "*Step 5 of 18:* Optional: What is your estimated body fat %? (e.g. `18`)\n"
        "Type /skip if you don't know.",
        parse_mode="Markdown",
    )
    return DN_BODYFAT


async def dn_bodyfat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.startswith("/"):
        try:
            _dn(context)["body_fat_pct"] = float(text)
        except ValueError:
            await update.message.reply_text("Please enter a number (e.g. `18`) or /skip", parse_mode="Markdown")
            return DN_BODYFAT
    keyboard = [
        [InlineKeyboardButton("🔥 Fat Loss", callback_data="dn_goal_fat_loss"),
         InlineKeyboardButton("💪 Lean Bulk", callback_data="dn_goal_lean_bulk")],
        [InlineKeyboardButton("📈 Bulk", callback_data="dn_goal_bulk"),
         InlineKeyboardButton("⚖️ Recomp", callback_data="dn_goal_recomp")],
        [InlineKeyboardButton("✅ Maintain", callback_data="dn_goal_maintain")],
    ]
    await update.message.reply_text(
        "*Step 6 of 18:* What is your primary nutrition goal?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return DN_GOAL


async def dn_goal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    _dn(context)["goal"] = query.data.replace("dn_goal_", "")
    keyboard = [
        [InlineKeyboardButton("🐢 Conservative", callback_data="dn_agg_conservative")],
        [InlineKeyboardButton("⚡ Moderate", callback_data="dn_agg_moderate")],
        [InlineKeyboardButton("🚀 Aggressive", callback_data="dn_agg_aggressive")],
    ]
    await query.edit_message_text(
        "*Step 7 of 18:* How aggressively do you want to pursue this goal?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return DN_AGGRESSIVENESS


async def dn_aggressiveness(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    _dn(context)["aggressiveness"] = query.data.replace("dn_agg_", "")
    keyboard = [
        [InlineKeyboardButton("🪑 Sedentary", callback_data="dn_act_sedentary")],
        [InlineKeyboardButton("🚶 Lightly active (1–3×/wk)", callback_data="dn_act_lightly_active")],
        [InlineKeyboardButton("🏃 Moderately active (3–5×/wk)", callback_data="dn_act_moderately_active")],
        [InlineKeyboardButton("🏋️ Very active (6–7×/wk)", callback_data="dn_act_very_active")],
        [InlineKeyboardButton("⚡ Extremely active (physical job + training)", callback_data="dn_act_extremely_active")],
    ]
    await query.edit_message_text(
        "*Step 8 of 18:* How active are you *outside* of training sessions?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return DN_ACTIVITY


async def dn_activity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    _dn(context)["activity_level"] = query.data.replace("dn_act_", "")

    goal = _dn(context).get("goal", "maintain")
    if goal in ("fat_loss", "lean_bulk", "bulk"):
        await query.edit_message_text(
            "*Step 9 of 18:* Target rate of change per week (% of bodyweight)?\n"
            "Typical: fat loss 0.5–1.0%, lean bulk 0.25–0.5%\n\n"
            "e.g. `0.5` — or /skip for the goal default.",
            parse_mode="Markdown",
        )
        return DN_TARGET_RATE

    return await _dn_ask_diet_style(query, context, edit=True)


async def dn_target_rate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.startswith("/"):
        try:
            _dn(context)["target_rate_pct_per_week"] = float(text)
        except ValueError:
            await update.message.reply_text("Please enter a number (e.g. `0.5`) or /skip", parse_mode="Markdown")
            return DN_TARGET_RATE
    return await _dn_ask_diet_style(update, context, edit=False)


async def _dn_ask_diet_style(msg_or_query, context, edit: bool = False) -> int:
    # Single balanced diet style — macros shift by goal (fat-loss leans lower-carb).
    # No separate vegan/keto/vegetarian/pescatarian styles by product decision.
    keyboard = [
        [InlineKeyboardButton("⚖️ Balanced", callback_data="dn_diet_balanced")],
    ]
    text = (
        "*Step 10 of 18:* Your plan uses a single *balanced* approach, tuned to your "
        "goal (a fat-loss goal automatically leans lower-carb). Tap to continue."
    )
    if edit:
        await msg_or_query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await msg_or_query.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    return DN_DIET_STYLE


async def dn_diet_style(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    _dn(context)["diet_style"] = query.data.replace("dn_diet_", "")
    await query.edit_message_text(
        "*Step 11 of 18:* Any food allergies? (e.g. `nuts, dairy`)\nType /skip if none.",
        parse_mode="Markdown",
    )
    return DN_ALLERGIES


async def dn_allergies(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.startswith("/"):
        _dn(context)["allergies"] = [a.strip() for a in text.split(",") if a.strip()]
    await update.message.reply_text(
        "*Step 12 of 18:* Foods you strongly dislike? (e.g. `brussels sprouts, liver`)\nType /skip if none.",
        parse_mode="Markdown",
    )
    return DN_DISLIKES


async def dn_dislikes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.startswith("/"):
        _dn(context)["dislikes"] = [d.strip() for d in text.split(",") if d.strip()]
    await update.message.reply_text(
        "*Step 13 of 18:* Religious or cultural dietary restrictions? (e.g. `halal, kosher`)\nType /skip if none.",
        parse_mode="Markdown",
    )
    return DN_RELIGIOUS


async def dn_religious(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.startswith("/"):
        _dn(context)["religious_restrictions"] = [r.strip() for r in text.split(",") if r.strip()]
    keyboard = [[
        InlineKeyboardButton("2", callback_data="dn_meals_2"),
        InlineKeyboardButton("3", callback_data="dn_meals_3"),
        InlineKeyboardButton("4", callback_data="dn_meals_4"),
        InlineKeyboardButton("5", callback_data="dn_meals_5"),
    ]]
    await update.message.reply_text(
        "*Step 14 of 18:* How many meals do you prefer per day?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return DN_MEALS


async def dn_meals(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    _dn(context)["meals_per_day"] = int(query.data.replace("dn_meals_", ""))
    keyboard = [
        [InlineKeyboardButton("1 — Minimal (heat & eat)", callback_data="dn_skill_1"),
         InlineKeyboardButton("2 — Basic", callback_data="dn_skill_2")],
        [InlineKeyboardButton("3 — Comfortable", callback_data="dn_skill_3"),
         InlineKeyboardButton("4 — Confident chef", callback_data="dn_skill_4")],
    ]
    await query.edit_message_text(
        "*Step 15 of 18:* How would you rate your cooking skill?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return DN_COOKING_SKILL


async def dn_cooking_skill(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    _dn(context)["cooking_skill"] = int(query.data.replace("dn_skill_", ""))
    keyboard = [
        [InlineKeyboardButton("⚡ 15 min", callback_data="dn_time_15"),
         InlineKeyboardButton("🕐 30 min", callback_data="dn_time_30")],
        [InlineKeyboardButton("🕑 45 min", callback_data="dn_time_45"),
         InlineKeyboardButton("🕒 60+ min", callback_data="dn_time_60")],
    ]
    await query.edit_message_text(
        "*Step 16 of 18:* Max time available for meal prep (per meal)?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return DN_COOKING_TIME


async def dn_cooking_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    _dn(context)["cooking_time_min"] = int(query.data.replace("dn_time_", ""))
    keyboard = [
        [InlineKeyboardButton("💰 Budget-friendly", callback_data="dn_budget_1")],
        [InlineKeyboardButton("💳 Mid-range", callback_data="dn_budget_2")],
        [InlineKeyboardButton("💎 Premium", callback_data="dn_budget_3")],
    ]
    await query.edit_message_text(
        "*Step 17 of 18:* What is your grocery budget tier?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return DN_BUDGET


async def dn_budget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    _dn(context)["budget_tier"] = int(query.data.replace("dn_budget_", ""))
    await query.edit_message_text(
        "*Step 18 of 18:* Any medical conditions that affect your diet? "
        "(e.g. `type2_diabetes, high_cholesterol, ibs`)\nType /skip if none.",
        parse_mode="Markdown",
    )
    return DN_MEDICAL


async def dn_medical(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.startswith("/"):
        _dn(context)["medical_conditions"] = [m.strip() for m in text.split(",") if m.strip()]
    return await _submit_nutrition(update, context)


async def _submit_nutrition(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Persist NutritionProfile, generate plan, notify admin."""
    from app.services.nutrition_service import NutritionService

    client_id = _current_client_id(update)
    data = _dn(context)

    await update.message.reply_text("⏳ Building your personalised nutrition plan...")

    with Session(engine, expire_on_commit=False) as session:
        existing = session.exec(
            select(NutritionProfile).where(NutritionProfile.client_id == client_id)
        ).first()
        if existing:
            for k, v in data.items():
                setattr(existing, k, v)
            existing.updated_at = datetime.now(timezone.utc)
            session.add(existing)
        else:
            np = NutritionProfile(
                client_id=client_id,
                updated_at=datetime.now(timezone.utc),
                **data,
            )
            session.add(np)
        session.commit()

        plan = NutritionService(session).generate(client_id)
        if not plan:
            await update.message.reply_text(
                "⚠️ Could not generate a plan — profile may be incomplete. "
                "Please try /diet again."
            )
            return ConversationHandler.END

    review_recipient = _resolve_review_recipient(plan.client_id)
    if review_recipient is not None:
        keyboard = [[
            InlineKeyboardButton("✅ Activate plan", callback_data=f"nutrapprove:{plan.id}"),
            InlineKeyboardButton("❌ Discard", callback_data=f"nutrdiscard:{plan.id}"),
        ]]
        summary = _build_client_summary(_current_client_id(update))
        admin_text = (
            f"🥗 *Nutrition plan ready for approval*\n\n"
            f"{summary}\n\n"
            f"────────────────────\n"
            f"Targets: *{(plan.kcal_target or 0):.0f} kcal*  ·  "
            f"P {(plan.protein_g or 0):.0f}g  ·  F {(plan.fat_g or 0):.0f}g  ·  "
            f"C {(plan.carb_g or 0):.0f}g  ·  Fibre {(plan.fiber_g or 0):.0f}g\n"
            f"Rationale: {plan.rationale or '—'}"
        )
        await safe_send_markdown(
            context.bot, review_recipient, admin_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    nutr_text = (
        f"✅ Your nutrition plan is ready!\n\n"
        f"📊 Daily targets:\n"
        f"• Calories: {plan.kcal_target:.0f} kcal\n"
        f"• Protein: {plan.protein_g:.0f}g\n"
        f"• Fat: {plan.fat_g:.0f}g\n"
        f"• Carbs: {plan.carb_g:.0f}g\n"
        f"• Fibre: {plan.fiber_g:.0f}g\n\n"
        "Coach Shoaib will review and activate it shortly 🙌"
    )
    await update.message.reply_text(nutr_text)
    return ConversationHandler.END


def _is_super_admin_user(user_id: int) -> bool:
    legacy_admin = _admin_chat_id()
    return auth_roles.is_super_admin(user_id) or (legacy_admin is not None and user_id == legacy_admin)


def _coach_authorized_for_client(user_id: int, client_id: str, session: Session) -> bool:
    """True if user is super-admin or the APPROVED assigned coach of this client."""
    if _is_super_admin_user(user_id):
        return True
    if not client_id:
        return False
    client = session.get(ClientProfile, client_id)
    coach = session.get(CoachProfile, user_id)
    if client is None or coach is None or coach.status != "approved":
        return False
    return client.assigned_coach_id == user_id


async def handle_nutrition_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin activates a nutrition plan, generates PDF and emails/notifies client."""
    query = update.callback_query
    await query.answer()
    plan_id = int(query.data.split(":")[1])

    with Session(engine) as session:
        plan = session.get(NutritionPlan, plan_id)
        if not plan:
            await query.edit_message_text("⚠️ Plan not found.")
            return

        if not _coach_authorized_for_client(update.effective_user.id, plan.client_id, session):
            await query.edit_message_text("🔒 Not authorized for this client.")
            return

        profile = session.get(ClientProfile, plan.client_id)
        if not profile:
            await query.edit_message_text("⚠️ Client profile not found.")
            return

        client_display = profile.name or profile.client_id
        await query.edit_message_text(f"Generating nutrition PDF for {client_display}...")

        for old in session.exec(
            select(NutritionPlan).where(
                NutritionPlan.client_id == plan.client_id,
                NutritionPlan.status == "active",
            )
        ).all():
            old.status = "superseded"
            session.add(old)
        plan.status = "active"
        plan.approved_at = datetime.now(timezone.utc)
        session.add(plan)
        session.commit()
        session.refresh(plan)
        session.refresh(profile)

    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / "nutrition_plan.pdf"
            render_plan_pdf(
                client=profile,
                out_path=pdf_path,
                nutrition_plan=plan,
                draft_watermark=False,
            )
            pdf_bytes = pdf_path.read_bytes()
    except Exception as err:
        logging.warning("Nutrition PDF render failed (%s), skipping PDF", err)
        pdf_bytes = None

    client_chat_id = auth_roles.resolve_primary_chat_id(plan.client_id)
    client_display = profile.name or profile.client_id

    if client_chat_id is None:
        await query.edit_message_text(
            f"✅ Approved, but no Telegram chat is bound to {client_display} yet. "
            "Their plan will be sent once they bind a device."
        )
        return

    if pdf_bytes:
        await context.bot.send_document(
            chat_id=client_chat_id,
            document=pdf_bytes,
            filename="nutrition_plan.pdf",
            caption="🥗 Your nutrition plan is ready! Here's your PDF 🙌",
        )
        await query.edit_message_text(f"✅ Nutrition plan activated. PDF sent to {client_display} via Telegram!")
    else:
        await context.bot.send_message(
            chat_id=client_chat_id,
            text="🥗 Your nutrition plan has been activated! Ask your coach for details.",
        )
        await query.edit_message_text("✅ Nutrition plan activated. PDF generation failed — client notified via text.")


async def handle_nutrition_discard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin discards a nutrition plan draft."""
    query = update.callback_query
    await query.answer()
    plan_id = int(query.data.split(":")[1])

    with Session(engine) as session:
        plan = session.get(NutritionPlan, plan_id)
        if plan:
            if not _coach_authorized_for_client(update.effective_user.id, plan.client_id, session):
                await query.edit_message_text("🔒 Not authorized for this client.")
                return
            plan.status = "rejected"
            session.add(plan)
            session.commit()

    await query.edit_message_text("❌ Nutrition plan discarded.")


# ── ADMIN: VIDEO REPLY ROUTING ─────────────────────────────────────────────────

async def handle_admin_video_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route admin/coach's reply to a form-check video back to the client.

    Permitted senders: super-admin (all videos) + assigned coach (only videos
    for their own clients). Phase H runtime check replaces the old static
    filters.Chat(admin) gate so multiple coaches can route feedback.
    """
    if not update.message.reply_to_message:
        return

    user_id = update.effective_user.id
    legacy_admin = _admin_chat_id()
    is_super = auth_roles.is_super_admin(user_id) or (legacy_admin is not None and user_id == legacy_admin)
    is_coach_user = auth_roles.is_coach(user_id)
    if not (is_super or is_coach_user):
        return

    replied_id = update.message.reply_to_message.message_id
    video_reviews = context.application.bot_data.get("video_reviews", {})
    entry = video_reviews.get(replied_id)
    if not entry:
        # Most common cause: bot was restarted between the forward and the
        # reply, so the in-memory map evaporated. Tell the coach instead of
        # silently dropping their feedback.
        logging.warning(
            "video_review_entry_missing replied_id=%s coach_user_id=%s — likely lost on restart",
            replied_id, user_id,
        )
        await update.message.reply_text(
            "⚠️ I couldn't find the video this reply belongs to (the bot may have "
            "restarted since the video was forwarded). Ask the client to resend "
            "the form-check video so I can re-link your feedback."
        )
        return

    # Coach scope: only videos for their assigned clients, and only while still approved.
    if not is_super:
        client_id = entry.get("client_id")
        with Session(engine) as session:
            client = session.get(ClientProfile, client_id) if client_id else None
            coach = session.get(CoachProfile, user_id)
        if coach is None or coach.status != "approved":
            await update.message.reply_text(
                "🔒 Your coach account is no longer approved — feedback not delivered."
            )
            logging.warning(
                "video_reply_blocked_coach_not_approved user_id=%s status=%s",
                user_id, coach.status if coach else "missing",
            )
            return
        if client is None or client.assigned_coach_id != user_id:
            await update.message.reply_text("🔒 Not your client.")
            return

    client_chat_id = entry["client_chat_id"]
    ex_name = entry["exercise_name"]
    coach_name = update.effective_user.first_name or "your coach"
    feedback_text = update.message.text or ""

    await context.bot.send_message(
        chat_id=client_chat_id,
        text=(
            f"🎥 <b>Form check feedback from Coach {_html.escape(coach_name)}</b>\n"
            f"Exercise: <i>{_html.escape(ex_name)}</i>\n\n"
            f"{_html.escape(feedback_text)}"
        ),
        parse_mode="HTML",
    )
    await update.message.reply_text(f"✅ Feedback sent to {entry['client_name']}.")


# ── ADMIN: FORM-CHECK TIP CONFIRMATION ────────────────────────────────────────

async def handle_fc_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin confirms generated tips — send them directly to the client."""
    query = update.callback_query
    await query.answer()

    tip_uuid = query.data.replace("fc_confirm_", "")
    entry = context.application.bot_data.get("pending_tips", {}).pop(tip_uuid, None)
    if not entry:
        await query.edit_message_text("⚠️ Tips already sent or expired.")
        return

    await context.bot.send_message(
        chat_id=entry["client_chat_id"],
        text=(
            f"💡 *Technique tips for {entry['exercise_name']}*\n\n"
            f"{entry['tips']}"
        ),
        parse_mode="Markdown",
    )
    await query.edit_message_text(
        f"✅ Tips for {entry['exercise_name']} sent to {entry['client_name']}."
    )


async def handle_fc_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Admin wants to edit the tips before sending."""
    query = update.callback_query
    await query.answer()

    tip_uuid = query.data.replace("fc_edit_", "")
    entry = context.application.bot_data.get("pending_tips", {}).get(tip_uuid)
    if not entry:
        await query.edit_message_text("⚠️ Tips already sent or expired.")
        return ConversationHandler.END

    context.user_data["editing_tip_uuid"] = tip_uuid
    await query.edit_message_text(
        f"✏️ Type your edited tips for *{entry['exercise_name']}* below.\n\n"
        f"Original:\n{entry['tips']}",
        parse_mode="Markdown",
    )
    return FORMCHECK_TIPS_CONFIRM


async def handle_fc_tip_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Send admin's edited tips to the client."""
    tip_uuid = context.user_data.pop("editing_tip_uuid", None)
    entry = context.application.bot_data.get("pending_tips", {}).pop(tip_uuid, None) if tip_uuid else None

    if not entry:
        await update.message.reply_text("⚠️ Could not find the original tip request.")
        return ConversationHandler.END

    await context.bot.send_message(
        chat_id=entry["client_chat_id"],
        text=(
            f"💡 *Technique tips for {entry['exercise_name']}*\n\n"
            f"{update.message.text.strip()}"
        ),
        parse_mode="Markdown",
    )
    await update.message.reply_text(f"✅ Edited tips sent to {entry['client_name']}.")
    return ConversationHandler.END


# ── ADMIN: WORKOUT PLAN APPROVE / REJECT ──────────────────────────────────────

async def handle_admin_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show confirmation step only when needed; otherwise approve directly."""
    query = update.callback_query
    await query.answer()

    approval_id = query.data.split(":")[1]

    with Session(engine) as session:
        pending = session.get(PendingApproval, approval_id)
        if not pending:
            await query.edit_message_text("❌ Plan no longer pending.")
            return
        if not _user_can_act_on_client(update.effective_user.id, pending.client_id):
            logging.warning(
                "coach_scope_violation handler=approve user_id=%s client_id=%s approval_id=%s",
                update.effective_user.id, pending.client_id, approval_id,
            )
            await query.edit_message_text("🔒 Not authorized for this client.")
            return
        client_name = pending.client_name or pending.client_id
        workout = WorkoutWeek.model_validate_json(pending.workout_json)
        edit_count = len(pending.edit_log or [])

        recent_active = session.exec(
            select(WorkoutHistory).where(
                WorkoutHistory.client_id == pending.client_id,
                WorkoutHistory.status == "active",
            ).order_by(WorkoutHistory.week_number.desc())
        ).first()

    superseding_recent = False
    if recent_active and recent_active.plan_started_at:
        age_days = (datetime.now(timezone.utc) - recent_active.plan_started_at.replace(tzinfo=timezone.utc)).days
        superseding_recent = age_days < 3

    needs_confirm = edit_count >= 2 or superseding_recent

    if not needs_confirm:
        # Delegate directly to the confirmed approval logic
        await _do_approve_confirmed(query, approval_id, context)
        return

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes, send it", callback_data=f"approve_confirmed:{approval_id}"),
        InlineKeyboardButton("↩️ Go back", callback_data=f"reject:{approval_id}"),
    ]])
    reason = f"{edit_count} edits" if edit_count >= 2 else "supersedes a plan <3 days old"
    await query.edit_message_text(
        f"⚠️ Confirm approval for *{client_name}* — Week {workout.week_number}? ({reason})\n"
        "This will generate and deliver the PDF to the client.",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


def _select_checkin_slots(week: WorkoutWeek) -> list[tuple[str, WorkoutSlot]]:
    """Returns (day_name, slot) tuples for all main_compound slots in the week.

    Single source of truth for the /checkin loop. The generator only sets
    slot_type='main_compound'; a previously-accepted dead literal that never
    matched anything has been removed.
    """
    return [
        (day.day_name, slot)
        for day in week.days
        for slot in day.slots
        if slot.slot_type == "main_compound"
    ]


# Equipment tokens that carry an external, progressable load. A "bodyweight" main is one
# with NO such token (air squat, push-up, pull-up, inverted row) — NOT merely a slot whose
# target_weight is None: an UNSEEDED barbell main (optional baselines skipped) also has
# target_weight None, and must still be asked its weight so the autoregulator can progress it.
_LOADABLE_EQUIP = {
    "barbell", "dumbbells", "kettlebell", "ez_bar", "trap_bar", "cable_machine",
    "smith_machine", "leg_press_machine", "leg_extension_machine", "leg_curl_machine",
}


def _checkin_slot_dicts(main_slots) -> list[dict]:
    """Build the structured check-in slot dicts; flag bodyweight mains by EQUIPMENT (no
    loadable token), not by target_weight (unseeded barbell mains also have None)."""
    from app.exercise_db import get_exercise_db
    eq_by_id = {e["exercise_id"]: e["equipment_required"] for e in get_exercise_db()}
    out = []
    for d, s in main_slots:
        eq = eq_by_id.get(s.exercise_id, [])
        bodyweight = "bodyweight" in eq and not any(t in _LOADABLE_EQUIP for t in eq)
        out.append({"day": d, "exercise_id": s.exercise_id, "exercise_name": s.exercise_name,
                    "rpe": s.rpe, "bodyweight": bodyweight})
    return out


async def _prompt_checkin_slot(send, slot: dict, week_number: int = None) -> int:
    """Ask weight for a loaded slot, or RPE for a bodyweight slot. Returns the next state."""
    head = f"📋 *Week {week_number} Check-in*\n\n" if week_number is not None else ""
    if slot.get("bodyweight"):
        await send(f"{head}*{slot['exercise_name']}* ({slot['day']}) — what RPE was your top set? "
                   "(1–10)", parse_mode="Markdown")
        return CHECKIN_EX_RPE
    await send(f"{head}*{slot['exercise_name']}* ({slot['day']}) — what was your top-set weight? "
               "(kg, e.g. `100`)", parse_mode="Markdown")
    return CHECKIN_EX_WEIGHT


def _format_plan_summary(workout: WorkoutWeek) -> str:
    """Compact text summary of a workout week.

    Sent as a Telegram message alongside the PDF so the client sees the plan
    inline without opening the PDF on a small screen.
    """
    lines = [f"📋 *Week {workout.week_number}* — {len(workout.days)} day(s)"]
    if not workout.days:
        return "\n".join(lines)
    for day in workout.days:
        lines.append("")
        lines.append(f"*{day.day_name}*")
        for slot in day.slots:
            lines.append(
                f"• {slot.exercise_name} — {slot.sets}×{slot.reps} @ RPE {slot.rpe}"
            )
    return "\n".join(lines)


# ── DB helper extraction (added for bot-only refactor) ────────────────────
def _load_pending_and_profile(approval_id: str):
    """Read PendingApproval + its ClientProfile in one session.

    Returns (pending, profile) or (None, None) if either is missing.
    """
    with Session(engine) as session:
        pending = session.get(PendingApproval, approval_id)
        if not pending:
            return None, None
        profile = session.get(ClientProfile, pending.client_id)
        return pending, profile


def _safe_render_pdf(profile: ClientProfile, pending: PendingApproval) -> bytes:
    """Render the professional PDF; on failure, fall back to Markdown→PDF."""
    transient_history = WorkoutHistory(
        client_id=pending.client_id,
        week_number=WorkoutWeek.model_validate_json(pending.workout_json).week_number,
        workout_json=pending.workout_json,
        status="active",
    )
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / "plan.pdf"
            render_plan_pdf(
                client=profile,
                out_path=pdf_path,
                workout_history=transient_history,
                draft_watermark=False,
            )
            return pdf_path.read_bytes()
    except Exception as err:
        logging.warning("Professional PDF render failed (%s), falling back", err)
        return PdfService.generate_pdf(pending.coaching_message)


def _atomic_finalise_history(pending: PendingApproval) -> None:
    """Supersede old active plan, insert new active, delete pending. One transaction."""
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        for old in session.exec(
            select(WorkoutHistory).where(
                WorkoutHistory.client_id == pending.client_id,
                WorkoutHistory.status == "active",
            )
        ).all():
            old.status = "superseded"
            session.add(old)

        new_history = WorkoutHistory(
            client_id=pending.client_id,
            week_number=WorkoutWeek.model_validate_json(pending.workout_json).week_number,
            workout_json=pending.workout_json,
            status="active",
            plan_started_at=now,
        )
        session.add(new_history)

        stale_pending = session.get(PendingApproval, pending.approval_uuid)
        if stale_pending:
            session.delete(stale_pending)
        session.commit()


async def _safe_edit(query, text: str) -> None:
    """edit_message_text that swallows the 'Message is not modified' 400.

    Telegram raises BadRequest when the new text+markup are identical to
    the current ones. That happens on double-click of the approve button
    or when the same status text gets re-emitted. Harmless; ignore.
    """
    from telegram.error import BadRequest
    try:
        await query.edit_message_text(text)
    except BadRequest as e:
        if "not modified" in str(e).lower():
            return
        raise


async def _do_approve_confirmed(query, approval_id: str, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shared approval logic called by both the direct and confirmation-step paths."""
    pending, profile = _load_pending_and_profile(approval_id)
    if pending is None:
        await _safe_edit(query, "❌ Plan no longer pending.")
        return
    if profile is None:
        logging.warning("client_not_found: %s", pending.client_id)
        await _safe_edit(query, "❌ Client profile not found — cannot approve.")
        return

    client_name = pending.client_name or pending.client_id
    await _safe_edit(query, f"Generating PDF for {client_name}...")

    workout = WorkoutWeek.model_validate_json(pending.workout_json)

    pdf_bytes = _safe_render_pdf(profile, pending)

    await context.bot.send_document(
        chat_id=pending.client_chat_id,
        document=pdf_bytes,
        filename=f"workout_plan_week{workout.week_number}.pdf",
        caption="🎉 Coach Shoaib has approved your plan! Here's your PDF 💪",
    )

    summary = _format_plan_summary(workout)
    if summary:
        try:
            await context.bot.send_message(
                chat_id=pending.client_chat_id,
                text=summary,
                parse_mode="Markdown",
            )
        except Exception as send_err:
            logging.warning("Inline summary send failed (non-fatal): %s", send_err)

    _atomic_finalise_history(pending)

    await _safe_edit(query, f"✅ Approved. PDF sent to {client_name} via Telegram!")


async def handle_admin_approve_confirmed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Execute approval (called from the explicit confirmation step)."""
    query = update.callback_query
    await query.answer()
    approval_id = query.data.split(":")[1]
    with Session(engine) as session:
        pending = session.get(PendingApproval, approval_id)
    if pending is None:
        await query.edit_message_text("❌ Plan no longer pending.")
        return
    if not _user_can_act_on_client(update.effective_user.id, pending.client_id):
        logging.warning(
            "coach_scope_violation handler=approve_confirmed user_id=%s client_id=%s approval_id=%s",
            update.effective_user.id, pending.client_id, approval_id,
        )
        await query.edit_message_text("🔒 Not authorized for this client.")
        return
    await _do_approve_confirmed(query, approval_id, context)


async def handle_admin_reject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    approval_id = query.data.split(":")[1]
    with Session(engine) as session:
        pending = session.get(PendingApproval, approval_id)
        if not pending:
            await query.edit_message_text("❌ Plan no longer pending.")
            return ConversationHandler.END
        if not _user_can_act_on_client(update.effective_user.id, pending.client_id):
            logging.warning(
                "coach_scope_violation handler=reject user_id=%s client_id=%s approval_id=%s",
                update.effective_user.id, pending.client_id, approval_id,
            )
            await query.edit_message_text("🔒 Not authorized for this client.")
            return ConversationHandler.END

    context.user_data['reject_uuid'] = approval_id
    await query.edit_message_text("Type your requested changes (e.g. 'Swap squats for leg press').")
    return ADMIN_FEEDBACK


async def handle_admin_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    feedback = update.message.text
    approval_id = context.user_data.get('reject_uuid')

    with Session(engine) as session:
        pending = session.get(PendingApproval, approval_id)
        if not pending:
            await update.message.reply_text("❌ Session expired.")
            return ConversationHandler.END
        if not _user_can_act_on_client(update.effective_user.id, pending.client_id):
            logging.warning(
                "coach_scope_violation handler=feedback user_id=%s client_id=%s approval_id=%s",
                update.effective_user.id, pending.client_id, approval_id,
            )
            await update.message.reply_text("🔒 Not authorized for this client.")
            return ConversationHandler.END

        await update.message.reply_text("⏳ Applying edits...")

        try:
            llm = FlashCommunicationService()
            mutated_json = llm.apply_coach_edits(pending.workout_json, feedback)
            new_workout = WorkoutWeek.model_validate_json(mutated_json)
            _feedback_client = session.get(ClientProfile, pending.client_id)
            if _feedback_client is None:
                logging.warning("client_not_found: %s", pending.client_id)
                await update.message.reply_text("❌ Client profile not found.")
                return ConversationHandler.END
            from app.domain.workout.equipment import validate_equipment, equipment_alternatives
            _violations = validate_equipment(new_workout, _feedback_client.available_equipment)
            if _violations:
                v = _violations[0]
                if v.missing == ["<unknown exercise>"]:
                    await update.message.reply_text(
                        f"🚫 `{v.exercise_id}` isn't a recognized exercise in our database — "
                        f"I can't add it. Plan NOT changed.",
                        parse_mode="Markdown",
                    )
                else:
                    alts = equipment_alternatives(v.exercise_id, _feedback_client.available_equipment)
                    alt_txt = "\n".join(f"• {a['name']} (`{a['exercise_id']}`)" for a in alts) or "(none in DB)"
                    await update.message.reply_text(
                        f"🚫 This plan contains *{v.exercise_name}*, which needs "
                        f"*{', '.join(v.missing)}* — the client doesn't have it. "
                        f"Plan NOT changed.\n\nEquipment-valid alternatives:\n{alt_txt}",
                        parse_mode="Markdown",
                    )
                return ConversationHandler.END
            new_msg = llm.generate_coaching_message(_feedback_client, new_workout)

            pending.workout_json = new_workout.model_dump_json()
            pending.coaching_message = new_msg
            log_entry = {"ts": datetime.now(timezone.utc).isoformat(), "feedback": feedback}
            pending.edit_log = (pending.edit_log or []) + [log_entry]
            session.add(pending)
            session.commit()

            keyboard = [[
                InlineKeyboardButton("✅ Approve", callback_data=f"approve:{approval_id}"),
                InlineKeyboardButton("❌ Reject again", callback_data=f"reject:{approval_id}"),
                InlineKeyboardButton("➕ Add core", callback_data=f"addcore:{approval_id}"),
            ]]
            edit_log = pending.edit_log or []
            edits_section = ""
            if edit_log:
                last2 = edit_log[-2:]
                edits_section = "**Previous edits:**\n" + "\n".join(
                    f"• {e['ts'][:16]}: {e['feedback'][:80]}" for e in last2
                ) + "\n\n"
            await update.message.reply_text(
                f"🔔 REVISED PLAN\n\n{edits_section}{new_msg}",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        except Exception as exc:
            logging.exception(
                "apply_coach_edits failed approval_id=%s client_id=%s feedback=%r",
                approval_id, pending.client_id, feedback,
            )
            kind = type(exc).__name__
            if isinstance(exc, ValueError) and "invalid JSON" in str(exc):
                reason = "LLM returned malformed JSON."
            elif isinstance(exc, ValidationError):
                reason = "LLM output didn't match the workout schema."
            else:
                reason = f"{kind}: {str(exc)[:120]}"
            await update.message.reply_text(
                f"⚠️ Edit failed — {reason}\n\nTry again with a more specific instruction "
                f"(e.g. name the day, lift, sets×reps, RPE explicitly)."
            )

    return ConversationHandler.END


async def cancel_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


# ── ADMIN: /review COMMAND ─────────────────────────────────────────────────────

@auth_roles.requires_assigned_coach
async def client_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show today's session by default; /plan week shows the full week."""
    client_id = _current_client_id(update)
    show_week = (
        context.args
        and context.args[0].lower() == "week"
        if context.args else False
    )

    with Session(engine) as session:
        history = session.exec(
            select(WorkoutHistory)
            .where(WorkoutHistory.client_id == client_id, WorkoutHistory.status == "active")
            .order_by(WorkoutHistory.week_number.desc())
        ).first()

    if not history:
        await update.message.reply_text(
            "No active plan yet. Use /start to set up your profile and receive a plan."
        )
        return

    week = WorkoutWeek.model_validate_json(history.workout_json)

    if not show_week:
        # Compute today's training day using plan_started_at offset; fall back to weekday
        if history.plan_started_at:
            started = history.plan_started_at.replace(tzinfo=timezone.utc)
            day_offset = (datetime.now(timezone.utc) - started).days
            today_idx = day_offset % max(len(week.days), 1)
        else:
            today_idx = datetime.now().weekday() % max(len(week.days), 1)

        today_day = week.days[today_idx] if today_idx < len(week.days) else None
        if today_day is None:
            await update.message.reply_text("🛌 Today is a rest day. /plan week to see the full schedule.")
            return
        if today_day:
            lines = [f"*Today's Session — {today_day.day_name}*  (Week {week.week_number})\n"]
            for slot in sorted(today_day.slots, key=lambda s: s.slot_order):
                rpe_str = f" @ RPE {slot.rpe}" if slot.rpe else ""
                wt_str = f" → {slot.target_weight}kg" if slot.target_weight else ""
                lines.append(
                    f"  {slot.slot_order}. {slot.exercise_name} — "
                    f"{slot.sets}×{slot.reps}{rpe_str}{wt_str}"
                )
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("📅 Full Week", callback_data="plan_full_week"),
            ]])
            await safe_send_markdown(
                context.bot, update.effective_chat.id,
                "\n".join(lines).strip(),
                reply_markup=keyboard,
            )
            return

    lines = [f"*Week {week.week_number} Training Plan*\n"]
    for day in week.days:
        lines.append(f"*{day.day_name}*")
        for slot in sorted(day.slots, key=lambda s: s.slot_order):
            rpe_str = f" @ RPE {slot.rpe}" if slot.rpe else ""
            lines.append(
                f"  {slot.slot_order}. {slot.exercise_name} — "
                f"{slot.sets}×{slot.reps}{rpe_str}"
            )
        lines.append("")

    await safe_send_markdown(context.bot, update.effective_chat.id, "\n".join(lines).strip())


async def handle_plan_full_week(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the full week plan when client taps [Full Week] on the today's session card."""
    query = update.callback_query
    await query.answer()

    client_id = _current_client_id(update)
    with Session(engine) as session:
        history = session.exec(
            select(WorkoutHistory)
            .where(WorkoutHistory.client_id == client_id, WorkoutHistory.status == "active")
            .order_by(WorkoutHistory.week_number.desc())
        ).first()

    if not history:
        await query.edit_message_text("No active plan found.")
        return

    week = WorkoutWeek.model_validate_json(history.workout_json)
    lines = [f"*Week {week.week_number} Training Plan*\n"]
    for day in week.days:
        lines.append(f"*{day.day_name}*")
        for slot in sorted(day.slots, key=lambda s: s.slot_order):
            rpe_str = f" @ RPE {slot.rpe}" if slot.rpe else ""
            lines.append(
                f"  {slot.slot_order}. {slot.exercise_name} — "
                f"{slot.sets}×{slot.reps}{rpe_str}"
            )
        lines.append("")

    await safe_send_markdown(context.bot, query.message.chat_id, "\n".join(lines).strip())


async def admin_review(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show index card of pending approvals.

    Super-admin sees everything. Coaches see only plans for their assigned
    clients (ClientProfile.assigned_coach_id == coach.telegram_user_id).
    """
    user_id = update.effective_user.id
    legacy_admin = _admin_chat_id()
    is_super = auth_roles.is_super_admin(user_id) or (legacy_admin is not None and user_id == legacy_admin)
    is_coach_user = auth_roles.is_coach(user_id)
    if not (is_super or is_coach_user):
        return

    with Session(engine) as session:
        if is_super:
            pending_workouts = session.exec(
                select(PendingApproval).order_by(PendingApproval.created_at)
            ).all()
            pending_nutrition = session.exec(
                select(NutritionPlan).where(NutritionPlan.status == "draft")
            ).all()
        else:
            scoped_client_ids = list(session.exec(
                select(ClientProfile.client_id).where(
                    ClientProfile.assigned_coach_id == user_id
                )
            ).all())
            pending_workouts = session.exec(
                select(PendingApproval)
                .where(PendingApproval.client_id.in_(scoped_client_ids))
                .order_by(PendingApproval.created_at)
            ).all() if scoped_client_ids else []
            pending_nutrition = session.exec(
                select(NutritionPlan).where(
                    NutritionPlan.status == "draft",
                    NutritionPlan.client_id.in_(scoped_client_ids),
                )
            ).all() if scoped_client_ids else []

    total = len(pending_workouts) + len(pending_nutrition)
    if total == 0:
        await update.message.reply_text("No pending approvals.")
        return

    lines = [f"📋 *Pending Plans ({total})*", "━━━━━━━━━━━━━━━━━"]
    keyboard_rows = []

    for i, pending in enumerate(pending_workouts, 1):
        workout = WorkoutWeek.model_validate_json(pending.workout_json)
        with Session(engine) as session:
            profile = session.get(ClientProfile, pending.client_id)
        name = (profile.name if profile else None) or pending.client_name or pending.client_id
        avatar = profile.avatar if profile else "?"
        days = profile.training_days if profile else "?"
        lines.append(f"{i}. {name}  ·  {avatar}  ·  {days}d  ·  Week {workout.week_number}")
        keyboard_rows.append([InlineKeyboardButton(
            f"Open #{i}", callback_data=f"open_pending:{pending.approval_uuid}"
        )])

    for j, plan in enumerate(pending_nutrition, len(pending_workouts) + 1):
        lines.append(f"{j}. 🥗 Nutrition — {plan.client_id}")
        keyboard_rows.append([InlineKeyboardButton(
            f"Open #{j}", callback_data=f"nutrapprove:{plan.id}"
        )])

    # Silent clients section: no check-in in >10 days
    now_utc = datetime.now(timezone.utc)
    with Session(engine) as session:
        if is_super:
            all_profiles = session.exec(select(ClientProfile)).all()
        else:
            all_profiles = session.exec(
                select(ClientProfile).where(ClientProfile.assigned_coach_id == user_id)
            ).all()
        silent_names = []
        for p in all_profiles:
            last_ci = session.exec(
                select(CheckIn).where(CheckIn.client_id == p.client_id)
                .order_by(CheckIn.created_at.desc())
            ).first()
            if last_ci is None or (
                last_ci.created_at and
                (now_utc - last_ci.created_at.replace(tzinfo=timezone.utc)).days > 10
            ):
                silent_names.append(p.name or p.client_id)

    if silent_names:
        lines.append("")
        lines.append(f"🔇 *Silent (no check-in >10d):* {', '.join(silent_names)}")

    keyboard_rows.append([InlineKeyboardButton("🗂 Group by type", callback_data="review_toggle_batch")])

    await safe_send_markdown(
        context.bot, update.effective_chat.id,
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(keyboard_rows),
    )


# ── Coach "add core at verification" ───────────────────────────────────────────

def _core_choices_for_client(client: ClientProfile) -> list[dict]:
    """Core exercises whose equipment the client has, deterministically sorted.
    Falls back to bodyweight core if the client's equipment yields none."""
    from app.exercise_db import get_exercise_db
    avail = set(client.available_equipment or [])
    full = "full_gym" in avail
    core = [e for e in get_exercise_db() if e.get("primary_muscle") == "core"]

    def _has_equipment(e: dict) -> bool:
        return full or all(eq in avail for eq in e["equipment_required"])

    choices = [e for e in core if _has_equipment(e)]
    if not choices:
        choices = [e for e in core if "bodyweight" in e["equipment_required"]]
    return sorted(choices, key=lambda e: e["exercise_id"])


def _add_core_to_day(week: WorkoutWeek, day_index: int, exercise: dict) -> WorkoutWeek:
    """Append a deterministic core slot to a day (in place) and return the week."""
    day = week.days[day_index]
    rpe = day.slots[0].rpe if day.slots else 7
    order = max((s.slot_order for s in day.slots), default=0) + 1
    day.slots.append(WorkoutSlot(
        slot_order=order,
        slot_type="isolation",
        exercise_id=exercise["exercise_id"],
        exercise_name=exercise["name"],
        sets=3,
        reps="10-15",
        rpe=rpe,
        rest_seconds=60,
        coaching_cues=[],
        warmup_sets=[],
        biomechanical_focus=exercise.get("biomechanical_focus"),
    ))
    day.total_fatigue = day.total_fatigue + exercise.get("fatigue_cost", 1)
    return week


def _review_keyboard(approval_id: str) -> InlineKeyboardMarkup:
    """Approve / Reject / Add-core keyboard shown on a plan under review."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Approve", callback_data=f"approve:{approval_id}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"reject:{approval_id}"),
        InlineKeyboardButton("➕ Add core", callback_data=f"addcore:{approval_id}"),
    ]])


def _render_pending_plan_text(pending: "PendingApproval") -> str:
    """Markdown body for a pending plan under review."""
    workout = WorkoutWeek.model_validate_json(pending.workout_json)
    client_summary = _build_client_summary(pending.client_id)
    submitted = pending.created_at.strftime('%Y-%m-%d %H:%M') if pending.created_at else 'unknown'
    day_lines = []
    for day in workout.days:
        day_lines.append(f"  *{day.day_name}*")
        for slot in sorted(day.slots, key=lambda s: s.slot_order):
            wt = f" → {slot.target_weight}kg" if slot.target_weight else ""
            day_lines.append(
                f"    {slot.slot_order}. {slot.exercise_name} {slot.sets}×{slot.reps} RPE{slot.rpe}{wt}"
            )
    plan_body = "\n".join(day_lines)
    return (
        f"🏋️ *Workout Plan — Week {workout.week_number}*  ·  Submitted {submitted}\n\n"
        f"{client_summary}\n\n"
        f"────────────────────\n"
        f"*Programme:*\n{plan_body}"
    )


async def _safe_edit_markdown(query, text, reply_markup=None) -> None:
    """Edit a callback message as Markdown, falling back to plain text."""
    try:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=reply_markup)
    except Exception:
        await query.edit_message_text(text, reply_markup=reply_markup)


async def handle_add_core_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Step 1: coach tapped 'Add core' — show a day picker."""
    query = update.callback_query
    await query.answer()
    approval_id = query.data.split(":", 1)[1]
    with Session(engine) as session:
        pending = session.get(PendingApproval, approval_id)
        if not pending:
            await query.edit_message_text("❌ Plan no longer pending.")
            return
        if not _user_can_act_on_client(update.effective_user.id, pending.client_id):
            await query.edit_message_text("🔒 Not authorized for this client.")
            return
        week = WorkoutWeek.model_validate_json(pending.workout_json)
    rows = [
        [InlineKeyboardButton(f"{i + 1}. {d.day_name}", callback_data=f"addcore_d:{approval_id}:{i}")]
        for i, d in enumerate(week.days)
    ]
    rows.append([InlineKeyboardButton("↩️ Back", callback_data=f"addcore_back:{approval_id}")])
    await query.edit_message_reply_markup(InlineKeyboardMarkup(rows))


async def handle_add_core_day(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Step 2: coach picked a day — show core-exercise picker for the client's kit."""
    query = update.callback_query
    await query.answer()
    _, approval_id, di = query.data.split(":")
    with Session(engine) as session:
        pending = session.get(PendingApproval, approval_id)
        if not pending:
            await query.edit_message_text("❌ Plan no longer pending.")
            return
        if not _user_can_act_on_client(update.effective_user.id, pending.client_id):
            await query.edit_message_text("🔒 Not authorized for this client.")
            return
        client = session.get(ClientProfile, pending.client_id)
    choices = _core_choices_for_client(client) if client else []
    rows = [
        [InlineKeyboardButton(e["name"], callback_data=f"addcore_x:{approval_id}:{di}:{xi}")]
        for xi, e in enumerate(choices)
    ]
    rows.append([InlineKeyboardButton("↩️ Back", callback_data=f"addcore:{approval_id}")])
    await query.edit_message_reply_markup(InlineKeyboardMarkup(rows))


async def handle_add_core_exercise(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Step 3: coach picked an exercise — insert it and re-render the plan."""
    query = update.callback_query
    await query.answer()
    _, approval_id, di, xi = query.data.split(":")
    di, xi = int(di), int(xi)
    added_name = None
    with Session(engine) as session:
        pending = session.get(PendingApproval, approval_id)
        if not pending:
            await query.edit_message_text("❌ Plan no longer pending.")
            return
        if not _user_can_act_on_client(update.effective_user.id, pending.client_id):
            await query.edit_message_text("🔒 Not authorized for this client.")
            return
        client = session.get(ClientProfile, pending.client_id)
        choices = _core_choices_for_client(client) if client else []
        week = WorkoutWeek.model_validate_json(pending.workout_json)
        if xi >= len(choices) or di >= len(week.days):
            await query.answer("That option is no longer valid.", show_alert=True)
            return
        exercise = choices[xi]
        added_name = exercise["name"]
        _add_core_to_day(week, di, exercise)
        pending.workout_json = week.model_dump_json()
        session.add(pending)
        session.commit()
        session.refresh(pending)
        text = f"✅ Added *{added_name}* to *{week.days[di].day_name}*.\n\n" + _render_pending_plan_text(pending)
    await _safe_edit_markdown(query, text, reply_markup=_review_keyboard(approval_id))


async def handle_add_core_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cancel the add-core flow — restore the plan review keyboard."""
    query = update.callback_query
    await query.answer()
    approval_id = query.data.split(":", 1)[1]
    await query.edit_message_reply_markup(_review_keyboard(approval_id))


async def handle_open_pending_item(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Expand a single pending workout plan for the admin to review."""
    query = update.callback_query
    await query.answer()

    approval_id = query.data.split(":")[1]

    with Session(engine) as session:
        pending = session.get(PendingApproval, approval_id)
        if not pending:
            await query.edit_message_text("❌ Plan no longer pending.")
            return
        if not _user_can_act_on_client(update.effective_user.id, pending.client_id):
            logging.warning(
                "coach_scope_violation handler=open_pending user_id=%s client_id=%s approval_id=%s",
                update.effective_user.id, pending.client_id, approval_id,
            )
            await query.edit_message_text("🔒 Not authorized for this client.")
            return

    workout = WorkoutWeek.model_validate_json(pending.workout_json)
    client_summary = _build_client_summary(pending.client_id)
    submitted = pending.created_at.strftime('%Y-%m-%d %H:%M') if pending.created_at else 'unknown'

    day_lines = []
    for day in workout.days:
        day_lines.append(f"  *{day.day_name}*")
        for slot in sorted(day.slots, key=lambda s: s.slot_order):
            wt = f" → {slot.target_weight}kg" if slot.target_weight else ""
            day_lines.append(
                f"    {slot.slot_order}. {slot.exercise_name} {slot.sets}×{slot.reps} RPE{slot.rpe}{wt}"
            )
    plan_body = "\n".join(day_lines)

    msg = (
        f"🏋️ *Workout Plan — Week {workout.week_number}*  ·  Submitted {submitted}\n\n"
        f"{client_summary}\n\n"
        f"────────────────────\n"
        f"*Programme:*\n{plan_body}"
    )
    await safe_send_markdown(context.bot, query.message.chat_id, msg,
                             reply_markup=_review_keyboard(approval_id))


async def admin_review_batch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/review_batch — groups pending plans by avatar+days bucket for efficient batch review.

    Same scoping as /review: super-admin sees all, coaches see only assigned clients.
    """
    user_id = update.effective_user.id
    legacy_admin = _admin_chat_id()
    is_super = auth_roles.is_super_admin(user_id) or (legacy_admin is not None and user_id == legacy_admin)
    is_coach_user = auth_roles.is_coach(user_id)
    if not (is_super or is_coach_user):
        return

    with Session(engine) as session:
        if is_super:
            pending_workouts = session.exec(
                select(PendingApproval).order_by(PendingApproval.created_at)
            ).all()
        else:
            scoped_client_ids = list(session.exec(
                select(ClientProfile.client_id).where(
                    ClientProfile.assigned_coach_id == user_id
                )
            ).all())
            pending_workouts = session.exec(
                select(PendingApproval)
                .where(PendingApproval.client_id.in_(scoped_client_ids))
                .order_by(PendingApproval.created_at)
            ).all() if scoped_client_ids else []

    if not pending_workouts:
        await update.message.reply_text("No pending workout approvals.")
        return

    # Group by (avatar, training_days)
    buckets: dict[tuple, list] = {}
    for pending in pending_workouts:
        with Session(engine) as session:
            profile = session.get(ClientProfile, pending.client_id)
        key = (
            profile.avatar if profile else "unknown",
            profile.training_days if profile else 0,
        )
        buckets.setdefault(key, []).append((pending, profile))

    for (avatar, days), items in buckets.items():
        lines = [f"*{avatar} {days}-day ({len(items)} pending):*"]
        keyboard_rows = []
        for pending, profile in items:
            workout = WorkoutWeek.model_validate_json(pending.workout_json)
            name = (profile.name if profile else None) or pending.client_name or pending.client_id
            lines.append(f"• {name} W{workout.week_number}")
            keyboard_rows.append([InlineKeyboardButton(
                f"Open {name} W{workout.week_number}",
                callback_data=f"open_pending:{pending.approval_uuid}",
            )])
        await safe_send_markdown(
            context.bot, update.effective_chat.id,
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(keyboard_rows),
        )


async def handle_review_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggle /review between list view and batch-grouped view."""
    query = update.callback_query
    await query.answer()
    await admin_review_batch(update, context)


# ── RATE LIMITER ──────────────────────────────────────────────────────────────

_generation_timestamps: dict[str, float] = defaultdict(float)
_error_last_sent: dict[str, float] = {}
_error_message_ids: dict[str, int] = {}
_error_counts: dict[str, int] = {}
_GENERATION_COOLDOWN_SECONDS = 60  # 1 minute between generations per client (prevents double-tap)
_MAX_AGE_SECONDS = 86400  # 24h — entries older than this are pruned


def _prune_old_entries(timestamps: dict, *companions: dict) -> None:
    """Remove entries whose timestamp is older than _MAX_AGE_SECONDS from timestamps and all companion dicts."""
    cutoff = time.monotonic() - _MAX_AGE_SECONDS
    stale = [k for k, t in timestamps.items() if t < cutoff]
    for k in stale:
        timestamps.pop(k, None)
        for d in companions:
            d.pop(k, None)


def _check_rate_limit(client_id: str) -> bool:
    """Return True if client is allowed to generate; False if still in cooldown."""
    now = time.monotonic()
    last = _generation_timestamps[client_id]
    if now - last < _GENERATION_COOLDOWN_SECONDS:
        return False
    _generation_timestamps[client_id] = now
    _prune_old_entries(_generation_timestamps)
    return True


# ── GLOBAL PTB ERROR HANDLER ──────────────────────────────────────────────────

async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log all unhandled exceptions and notify the admin (deduplicated, count-edited within 5-min window).

    Two error classes are handled specially before the generic traceback-DM path,
    because both are non-actionable noise that would otherwise flood the admin:

    - ``NetworkError`` (incl. ``TimedOut`` and wrapped ``httpx.ReadError``):
      transient polling blips. PTB's network_retry_loop already retries and the
      bot self-recovers — log only, never DM.
    - ``Conflict`` ("terminated by other getUpdates request"): two processes are
      polling the same bot token. Operational, not a code bug — send one concise
      alert (rate-limited 30 min), never the raw traceback.
    """
    err = context.error
    now = time.monotonic()
    admin_id = _admin_chat_id()

    # Transient network errors: PTB auto-retries. Log, don't alarm.
    # NOTE: PTB's BadRequest subclasses NetworkError (e.g. "Can't parse entities")
    # — those are real bugs and must stay on the traceback-DM path, so exclude them.
    if isinstance(err, NetworkError) and not isinstance(err, BadRequest):
        logging.warning("transient polling network error: %s", err)
        return

    # Two pollers on one token. One concise alert per 30 min, no traceback.
    if isinstance(err, Conflict):
        logging.error("getUpdates Conflict — another process is polling this token: %s", err)
        conflict_key = "__conflict__"
        last = _error_last_sent.get(conflict_key)
        if last is not None and now - last < 1800:
            return
        _error_last_sent[conflict_key] = now
        _prune_old_entries(_error_last_sent, _error_message_ids, _error_counts)
        if admin_id is not None:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=(
                        "⚠️ Conflict: another process is polling this bot token (getUpdates).\n\n"
                        "Only ONE poller may run per token. Stop any local `python -m app.bot` "
                        "using the prod token, or remove a duplicate/orphaned container. "
                        "Use a separate @BotFather dev token for local testing."
                    ),
                )
            except Exception:
                pass
        return

    tb = "".join(traceback.format_exception(type(err), err, err.__traceback__))
    logging.error("Unhandled exception:\n%s", tb)

    sig = hashlib.md5(str(err)[:200].encode()).hexdigest()
    short_tb = tb[-3000:] if len(tb) > 3000 else tb

    if sig in _error_last_sent and now - _error_last_sent[sig] < 300:
        _error_counts[sig] = _error_counts.get(sig, 1) + 1
        msg_id = _error_message_ids.get(sig)
        if admin_id is not None and msg_id:
            try:
                await context.bot.edit_message_text(
                    chat_id=admin_id,
                    message_id=msg_id,
                    text=f"⚠️ Bot error (×{_error_counts[sig]}):\n```\n{short_tb}\n```",
                    parse_mode="Markdown",
                )
            except Exception:
                pass
        return

    _error_last_sent[sig] = now
    _error_counts[sig] = 1
    _prune_old_entries(_error_last_sent, _error_message_ids, _error_counts)

    if admin_id is not None:
        try:
            sent = await context.bot.send_message(
                chat_id=admin_id,
                text=f"⚠️ Bot error:\n```\n{short_tb}\n```",
                parse_mode="Markdown",
            )
            _error_message_ids[sig] = sent.message_id
        except Exception:
            pass


# ── /log COMMAND — manual set logging ────────────────────────────────────────

@auth_roles.requires_assigned_coach
async def start_log(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """/log — manually log weight/RPE for any exercise in the active plan."""
    client_id = _current_client_id(update)

    with Session(engine) as session:
        history = session.exec(
            select(WorkoutHistory)
            .where(WorkoutHistory.client_id == client_id, WorkoutHistory.status == "active")
            .order_by(WorkoutHistory.week_number.desc())
        ).first()

    if not history:
        await update.message.reply_text("No active plan. Use /start to set up your profile.")
        return ConversationHandler.END

    week = WorkoutWeek.model_validate_json(history.workout_json)
    context.user_data["log_history_id"] = history.history_id
    context.user_data["log_week"] = week.model_dump_json()

    keyboard_rows = [
        [InlineKeyboardButton(day.day_name, callback_data=f"log_day_{i}")]
        for i, day in enumerate(week.days)
    ]
    await update.message.reply_text(
        "Which training day would you like to log?",
        reply_markup=InlineKeyboardMarkup(keyboard_rows),
    )
    return LOG_SELECT_DAY


async def handle_log_select_day(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    day_idx = int(query.data.split("_")[-1])
    week = WorkoutWeek.model_validate_json(context.user_data["log_week"])
    day = week.days[day_idx]

    context.user_data["log_day_idx"] = day_idx
    keyboard_rows = [
        [InlineKeyboardButton(slot.exercise_name, callback_data=f"log_ex_{slot.slot_order}")]
        for slot in sorted(day.slots, key=lambda s: s.slot_order)
    ]
    await query.edit_message_text(
        f"*{day.day_name}* — which exercise?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard_rows),
    )
    return LOG_SELECT_EXERCISE


async def handle_log_select_exercise(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    slot_order = int(query.data.split("_")[-1])
    week = WorkoutWeek.model_validate_json(context.user_data["log_week"])
    day = week.days[context.user_data["log_day_idx"]]
    slot = next(s for s in day.slots if s.slot_order == slot_order)

    context.user_data["log_slot_order"] = slot_order
    await query.edit_message_text(
        f"*{slot.exercise_name}* — what weight did you use? (kg, e.g. `100`)\nType /skip to skip.",
        parse_mode="Markdown",
    )
    return LOG_WEIGHT


async def handle_log_weight(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.startswith("/"):
        try:
            context.user_data["log_weight"] = float(text)
        except ValueError:
            await update.message.reply_text("Please enter a number (e.g. `100`) or /skip", parse_mode="Markdown")
            return LOG_WEIGHT
    await update.message.reply_text("And your RPE? (1–10, e.g. `8`) — or /skip")
    return LOG_RPE


async def handle_log_rpe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.startswith("/"):
        try:
            context.user_data["log_rpe"] = float(text)
        except ValueError:
            await update.message.reply_text("Please enter RPE 1–10 or /skip", parse_mode="Markdown")
            return LOG_RPE

    # Write back to WorkoutHistory
    with Session(engine) as session:
        history = session.get(WorkoutHistory, context.user_data["log_history_id"])
        if history:
            week = WorkoutWeek.model_validate_json(history.workout_json)
            day = week.days[context.user_data["log_day_idx"]]
            slot_order = context.user_data["log_slot_order"]
            for slot in day.slots:
                if slot.slot_order == slot_order:
                    if "log_weight" in context.user_data:
                        slot.actual_weight = context.user_data["log_weight"]
                    if "log_rpe" in context.user_data:
                        slot.actual_rpe = context.user_data["log_rpe"]
                    break
            history.workout_json = week.model_dump_json()
            session.add(history)
            session.commit()

    await update.message.reply_text("✅ Logged! Use /log again to record another set.")
    return ConversationHandler.END


# ── 24h PLAN ACKNOWLEDGMENT ────────────────────────────────────────────────────

async def check_plan_acknowledgment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """On any client message, check if their plan needs a 24h follow-up nudge."""
    _active_conversation_keys = {"checkin_history_id", "log_history_id", "avatar", "dn_weight"}
    if any(k in context.user_data for k in _active_conversation_keys):
        return

    client_id = _current_client_id(update)
    now = datetime.now(timezone.utc)

    with Session(engine) as session:
        history = session.exec(
            select(WorkoutHistory).where(
                WorkoutHistory.client_id == client_id,
                WorkoutHistory.status == "active",
                WorkoutHistory.acknowledged_at == None,  # noqa: E711
            ).order_by(WorkoutHistory.week_number.desc())
        ).first()

        if not history or history.history_id is None:
            return

        created = history.created_at
        if created is None:
            return

        # Only nudge if plan was created more than 24h ago
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if (now - created).total_seconds() < 86400:
            return

        # Mark acknowledged immediately so we don't double-send
        history.acknowledged_at = now
        session.add(history)
        session.commit()

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("👍 Good", callback_data="ack_good"),
        InlineKeyboardButton("😐 OK", callback_data="ack_ok"),
        InlineKeyboardButton("❓ Question", callback_data="ack_question"),
    ]])
    await update.message.reply_text(
        "👋 Quick check-in on your new plan — how's it feeling so far?",
        reply_markup=keyboard,
    )


async def handle_plan_ack(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the 24h acknowledgment button press."""
    query = update.callback_query
    await query.answer()

    if query.data == "ack_question":
        # Dead-end branch — now handled by the /ask ConversationHandler entry point.
        # Kept for safety but should never be reached after the pattern change.
        await query.edit_message_text(
            "Feel free to ask your question anytime — your coach will reply here."
        )
    else:
        label = "Great!" if query.data == "ack_good" else "Noted — keep going!"
        await query.edit_message_text(label)


# ── /ask client question flow (SP-C) ─────────────────────────────────────────

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


async def handle_qa_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import uuid
    from datetime import datetime, timezone
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
    with Session(engine, expire_on_commit=False) as session:
        session.add(q); session.commit()

    await _dm_coach_question(context.bot, q)
    await update.message.reply_text("✅ Sent to your coach — they'll reply here.")
    return ConversationHandler.END


# ── /override COMMAND — coach exercise substitution ────────────────────────────

async def handle_override(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/override [client_id] [from_id] [to_id] — set, list, or remove exercise overrides.

    Coaches can only override exercises for their assigned clients.
    Super-admin can override for anyone.
    """
    user_id = update.effective_user.id
    legacy_admin = _admin_chat_id()
    is_super = auth_roles.is_super_admin(user_id) or (legacy_admin is not None and user_id == legacy_admin)
    is_coach_user = auth_roles.is_coach(user_id)
    if not (is_super or is_coach_user):
        return

    args = context.args or []

    if len(args) == 0:
        await update.message.reply_text(
            "Usage:\n"
            "  /override <client_id> — list overrides\n"
            "  /override <client_id> <from_id> <to_id> — set override\n"
            "Example: /override 123456 bb_squat goblet_squat"
        )
        return

    client_id = args[0]
    with Session(engine) as session:
        profile = session.get(ClientProfile, client_id)
        if profile is not None and not is_super and profile.assigned_coach_id != user_id:
            await update.message.reply_text(
                "🔒 You don't have access to that client (not assigned to you)."
            )
            return
        if not profile:
            await update.message.reply_text(f"No profile found for client {client_id}.")
            return

        if len(args) == 1:
            # List current overrides with Remove buttons
            overrides = profile.coach_overrides or {}
            if not overrides:
                await update.message.reply_text(f"No overrides set for {client_id}.")
                return
            lines = [f"*Overrides for {profile.name or client_id}:*"]
            keyboard_rows = []
            for from_ex, to_ex in overrides.items():
                lines.append(f"  `{from_ex}` → `{to_ex}`")
                keyboard_rows.append([InlineKeyboardButton(
                    f"Remove {from_ex}", callback_data=f"override_remove:{client_id}:{from_ex}"
                )])
            await safe_send_markdown(
                context.bot, update.effective_chat.id,
                "\n".join(lines),
                reply_markup=InlineKeyboardMarkup(keyboard_rows),
            )
            return

        if len(args) < 3:
            await update.message.reply_text("Usage: /override <client_id> <from_id> <to_id>")
            return

        from_id, to_id = args[1], args[2]
        from app.domain.workout.equipment import validate_equipment, equipment_alternatives
        from app.models import WorkoutWeek, WorkoutDay, WorkoutSlot
        probe = WorkoutWeek(week_number=1, days=[WorkoutDay(
            day_name="probe",
            slots=[WorkoutSlot(slot_order=0, slot_type="isolation", exercise_id=to_id,
                               exercise_name=to_id, sets=1, reps="1", rpe=1)],
            total_fatigue=1)])
        bad = validate_equipment(probe, profile.available_equipment)
        if bad and bad[0].missing == ["<unknown exercise>"]:
            await update.message.reply_text(
                f"🚫 Can't set that override: `{to_id}` isn't a recognized exercise "
                f"in our database.",
                parse_mode="Markdown",
            )
            return
        if bad:
            missing = ", ".join(bad[0].missing)
            alts = equipment_alternatives(to_id, profile.available_equipment)
            alt_txt = "\n".join(f"  `{a['exercise_id']}` — {a['name']}" for a in alts) or "  (none in DB)"
            await update.message.reply_text(
                f"🚫 Can't set that override: `{to_id}` needs *{missing}*, which "
                f"{profile.name or client_id} doesn't have.\n\nEquipment-valid alternatives:\n{alt_txt}",
                parse_mode="Markdown",
            )
            return
        overrides = dict(profile.coach_overrides or {})
        overrides[from_id] = to_id
        profile.coach_overrides = overrides
        session.add(profile)
        session.commit()

    await update.message.reply_text(
        f"✅ Override set for {client_id}: `{from_id}` → `{to_id}`\n"
        "Will take effect on their next plan generation.",
        parse_mode="Markdown",
    )


async def handle_override_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove a single coach override via inline button."""
    query = update.callback_query
    await query.answer()

    _, client_id, from_id = query.data.split(":", 2)

    with Session(engine) as session:
        profile = session.get(ClientProfile, client_id)
        if not profile:
            await query.edit_message_text("Profile not found.")
            return
        overrides = dict(profile.coach_overrides or {})
        overrides.pop(from_id, None)
        profile.coach_overrides = overrides or None
        session.add(profile)
        session.commit()

    await query.edit_message_text(f"✅ Override `{from_id}` removed for {client_id}.", parse_mode="Markdown")


# ── SAFETY CLEARANCE ─────────────────────────────────────────────────────────

async def handle_safety_clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin marks a client as cleared by physician, bypassing the safety gate.

    Medical safety override — restricted to the super-admin even for an
    assigned coach.
    """
    query = update.callback_query
    await query.answer()

    if not _is_super_admin_user(update.effective_user.id):
        await query.edit_message_text("🔒 Only the super-admin can clear a medical safety gate.")
        return

    parts = query.data.split(":", 2)
    client_id, condition_key = parts[1], parts[2]

    with Session(engine) as session:
        profile = session.get(ClientProfile, client_id)
        if not profile:
            await query.edit_message_text("Profile not found.")
            return
        profile.safety_override_note = (
            f"Cleared by physician for {condition_key} — {datetime.now(timezone.utc).date()}"
        )
        session.add(profile)
        session.commit()

    await query.edit_message_text(
        f"✅ Safety gate cleared for {client_id} (condition: {condition_key}). "
        "Their next plan generation will proceed normally."
    )


# ── /help COMMAND ─────────────────────────────────────────────────────────────

_CLIENT_HELP = (
    "/start — show menu (subscribe / log in / ask questions)\n"
    "/checkin — log this week's sessions (main lifts)\n"
    "/log — manually log weight/RPE for any exercise\n"
    "/plan — view your current plan (today's session by default)\n"
    "/diet — set up your nutrition profile\n"
    "/pick_coach — choose or change your coach\n"
    "/cancel — cancel the current action"
)

_COACH_HELP = (
    "/review — pending plans for your assigned clients\n"
    "/review_batch — group pending plans by training type\n"
    "/override &lt;client_id&gt; &lt;from_id&gt; &lt;to_id&gt; — substitute an exercise\n"
    "/override &lt;client_id&gt; — list/remove overrides\n"
    "/help — this message"
)

_SUPER_ADMIN_HELP = (
    "<i>(super-admin sees ALL clients across coaches)</i>\n"
    "/review — pending approvals (workout + nutrition)\n"
    "/review_batch — group pending plans by training type\n"
    "/override &lt;client_id&gt; &lt;from_id&gt; &lt;to_id&gt; — substitute an exercise\n"
    "Coach approvals + payment verification arrive as inline-button DMs"
)


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    legacy_admin = _admin_chat_id()
    is_super = auth_roles.is_super_admin(user_id) or (legacy_admin is not None and user_id == legacy_admin)
    is_coach_user = auth_roles.is_coach(user_id)

    text = f"<b>Client commands:</b>\n{_CLIENT_HELP}"
    if is_coach_user and not is_super:
        text += f"\n\n<b>Coach commands:</b>\n{_COACH_HELP}"
    if is_super:
        text += f"\n\n<b>Super-admin commands:</b>\n{_SUPER_ADMIN_HELP}"
    await update.message.reply_text(text, parse_mode="HTML")


# ── MAIN ───────────────────────────────────────────────────────────────────────

def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logging.error("No TELEGRAM_BOT_TOKEN found.")
        return

    # Production: refuse to boot on the insecure default JWT secret (forge-able tokens).
    get_settings().require_secure_secret()

    super_admin = auth_roles.super_admin_user_id()
    if super_admin is None:
        logging.error(
            "FATAL: neither SUPER_ADMIN_TELEGRAM_USER_ID nor ADMIN_CHAT_ID is set. "
            "Payment verifications, coach applications, and assignment requests "
            "cannot be routed. Refusing to start — set one of these env vars."
        )
        return
    logging.info("Super-admin telegram_user_id resolved to %s", super_admin)

    create_db_and_tables()
    app = ApplicationBuilder().token(token).build()

    # ── Daily renewal-reminder + expiry jobs (Phase F) ──
    if app.job_queue is not None:
        import datetime as _dt
        app.job_queue.run_daily(
            send_renewal_reminders,
            time=_dt.time(hour=9, minute=0, tzinfo=timezone.utc),
            name="send_renewal_reminders",
        )
        app.job_queue.run_daily(
            expire_subscriptions,
            time=_dt.time(hour=0, minute=5, tzinfo=timezone.utc),
            name="expire_subscriptions",
        )
    else:
        logging.warning(
            "JobQueue unavailable — install python-telegram-bot[job-queue]. "
            "Daily renewal reminders + expiry will NOT run."
        )

    _intake_states = {
        ASK_AVATAR: [CallbackQueryHandler(handle_avatar, pattern=r"^(powerlifter|powerbuilder|gen_pop)$")],
        ASK_DAYS: [
            CallbackQueryHandler(handle_intake_back, pattern=r"^intake_back:"),
            CallbackQueryHandler(handle_days, pattern=r"^(3|4|5|6)$"),
        ],
        ASK_EQUIPMENT: [
            CallbackQueryHandler(handle_intake_back, pattern=r"^intake_back:"),
            CallbackQueryHandler(handle_equipment_preset, pattern=r"^equip_preset:"),
        ],
        ASK_EQUIPMENT_CUSTOM: [
            CallbackQueryHandler(handle_intake_back, pattern=r"^intake_back:"),
            CallbackQueryHandler(handle_equipment_toggle, pattern=r"^equip_toggle_"),
            CallbackQueryHandler(handle_equipment_confirm, pattern=r"^equip_confirm$"),
        ],
        ASK_EQUIPMENT_PULLUP: [
            CallbackQueryHandler(handle_intake_back, pattern=r"^intake_back:"),
            CallbackQueryHandler(handle_equipment_pullup, pattern=r"^equip_pullup:"),
        ],
        ASK_EXPERIENCE: [
            CallbackQueryHandler(handle_intake_back, pattern=r"^intake_back:"),
            CallbackQueryHandler(handle_experience, pattern=r"^(beginner|intermediate|advanced)$"),
        ],
        ASK_ABILITY: [
            CallbackQueryHandler(handle_intake_back, pattern=r"^intake_back:"),
            CallbackQueryHandler(handle_ability, pattern=r"^(abil:[123]|abil_skip)$"),
        ],
        ASK_LIMITATIONS: [
            CallbackQueryHandler(handle_intake_back, pattern=r"^intake_back:"),
            CallbackQueryHandler(handle_limitations_toggle, pattern=r"^lim_toggle_"),
            CallbackQueryHandler(handle_limitations_confirm, pattern=r"^lim_confirm$"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_limitations),
        ],
        ASK_EMAIL: [
            CallbackQueryHandler(handle_intake_back, pattern=r"^intake_back:"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_email),
        ],
        ASK_LIMITATIONS_OTHER: [
            CallbackQueryHandler(handle_intake_back, pattern=r"^intake_back:"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_limitations_other),
        ],
        ASK_BASE_SQUAT: [
            CallbackQueryHandler(handle_intake_back, pattern=r"^intake_back:"),
            CallbackQueryHandler(handle_base_squat, pattern=r"^base_skip$"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_base_squat),
        ],
        ASK_BASE_BENCH: [
            CallbackQueryHandler(handle_intake_back, pattern=r"^intake_back:"),
            CallbackQueryHandler(handle_base_bench, pattern=r"^base_skip$"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_base_bench),
        ],
        ASK_BASE_DEADLIFT: [
            CallbackQueryHandler(handle_intake_back, pattern=r"^intake_back:"),
            CallbackQueryHandler(handle_base_deadlift, pattern=r"^base_skip$"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_base_deadlift),
        ],
    }

    _menu_states = {
        MENU_ROOT: [
            CallbackQueryHandler(handle_menu_subscribe, pattern=r"^menu_subscribe$"),
            CallbackQueryHandler(handle_menu_faq, pattern=r"^menu_faq$"),
            CallbackQueryHandler(handle_menu_login, pattern=r"^menu_login$"),
            CallbackQueryHandler(handle_menu_coach, pattern=r"^menu_coach$"),
        ],
        SUBSCRIBE_PICK_PLAN: [
            CallbackQueryHandler(handle_subscribe_pick_plan, pattern=r"^sub_pick:(1m|3m)$"),
            CallbackQueryHandler(handle_menu_back, pattern=r"^menu_back$"),
        ],
        SUBSCRIBE_AWAIT_SCREENSHOT: [
            MessageHandler(filters.PHOTO, handle_payment_screenshot),
            MessageHandler(filters.TEXT & ~filters.COMMAND,
                           lambda u, c: u.message.reply_text("Send the receipt as a photo, or /cancel.")),
        ],
        LOGIN_AWAIT_CODE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_login_code),
        ],
        FAQ_LOOP: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_faq_message),
        ],
        COACH_APPLY_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, coach_apply_name)],
        COACH_APPLY_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, coach_apply_email)],
        COACH_APPLY_MOBILE: [MessageHandler(filters.TEXT & ~filters.COMMAND, coach_apply_mobile)],
        COACH_APPLY_SPECIALTY: [CallbackQueryHandler(coach_apply_specialty, pattern=r"^coach_spec:")],
        COACH_APPLY_YEARS: [MessageHandler(filters.TEXT & ~filters.COMMAND, coach_apply_years)],
        COACH_APPLY_CERTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, coach_apply_certs)],
        COACH_APPLY_CV: [
            MessageHandler(filters.Document.ALL, coach_apply_cv),
            CommandHandler("skip", coach_apply_cv),
        ],
        COACH_APPLY_PORTFOLIO: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, coach_apply_portfolio),
            CommandHandler("skip", coach_apply_portfolio),
        ],
    }

    # ── Client intake (with new pre-payment menu) ──
    app.add_handler(ConversationHandler(
        entry_points=[
            CommandHandler("start", start_conversation),
            CallbackQueryHandler(handle_setup_begin, pattern=r"^setup_begin$"),
        ],
        states={**_intake_states, **_menu_states},
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
    ))

    # ── Update profile (field picker) ──
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("update_profile", start_update_profile)],
        states={
            UPD_PICK: [CallbackQueryHandler(upd_pick, pattern=r"^upd:")],
            UPD_AVATAR: [CallbackQueryHandler(upd_set_goal, pattern=r"^upd_goal:")],
            UPD_DAYS: [CallbackQueryHandler(upd_set_days, pattern=r"^upd_days:")],
            UPD_EXP: [CallbackQueryHandler(upd_set_exp, pattern=r"^upd_exp:")],
            UPD_LIM: [
                CallbackQueryHandler(upd_lim_toggle, pattern=r"^lim_toggle_"),
                CallbackQueryHandler(upd_lim_confirm, pattern=r"^lim_confirm$"),
            ],
            UPD_LIM_OTHER: [MessageHandler(filters.TEXT & ~filters.COMMAND, upd_lim_other)],
            UPD_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, upd_set_email)],
            UPD_EQUIPMENT: [
                CallbackQueryHandler(upd_equipment_toggle, pattern=r"^equip_toggle_"),
                CallbackQueryHandler(upd_equipment_confirm, pattern=r"^equip_confirm$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
    ))

    # ── Check-in + post-menu + form check ──
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("checkin", start_checkin)],
        states={
            CHECKIN_RESUME: [
                CallbackQueryHandler(handle_checkin_resume, pattern=r"^(ci_resume:|ci_restart$)"),
            ],
            CHECKIN_COLLECTING: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_checkin_collecting),
                CommandHandler("done", handle_checkin_done),
            ],
            CHECKIN_CLARIFYING: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_checkin_clarifying),
            ],
            CHECKIN_EX_WEIGHT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_structured_weight),
            ],
            CHECKIN_EX_RPE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_structured_rpe),
            ],
            CHECKIN_EX_PAIN: [
                CallbackQueryHandler(handle_structured_pain, pattern=r"^pain_"),
            ],
            CHECKIN_EX_SETS: [
                CallbackQueryHandler(handle_structured_sets, pattern=r"^sets_"),
            ],
            CHECKIN_GENERAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_structured_general),
                CommandHandler("skip", handle_structured_general),
            ],
            ConversationHandler.TIMEOUT: [
                MessageHandler(filters.ALL, handle_checkin_timeout),
            ],
            POST_MENU: [CallbackQueryHandler(handle_post_menu, pattern=r"^pm_")],
            UPDATES_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_updates_text)],
            FORMCHECK_EXERCISE: [CallbackQueryHandler(handle_formcheck_exercise, pattern=r"^fc_ex_")],
            FORMCHECK_MODE: [CallbackQueryHandler(handle_formcheck_mode, pattern=r"^fc_mode_")],
            FORMCHECK_VIDEO: [
                MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_formcheck_video)
            ],
        },
        conversation_timeout=90,
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
    ))

    # ── Client Q&A: /ask + rewired "❓ Question" button (SP-C) ──
    app.add_handler(ConversationHandler(
        entry_points=[
            CommandHandler("ask", start_ask),
            CallbackQueryHandler(start_ask, pattern=r"^ack_question$"),
        ],
        states={ASK_QA_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_qa_question)]},
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
    ))

    # ── Admin: workout reject + form-check tip editing ──
    app.add_handler(ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handle_admin_reject, pattern=r"^reject:"),
            CallbackQueryHandler(handle_fc_edit, pattern=r"^fc_edit_"),
        ],
        states={
            ADMIN_FEEDBACK: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_feedback)],
            FORMCHECK_TIPS_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_fc_tip_edit)],
        },
        fallbacks=[CommandHandler("cancel", cancel_admin)],
        per_message=False,
    ))

    # ── Admin: payment reject reason capture ──
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_payment_reject_start, pattern=r"^pay_reject:")],
        states={
            PAY_REJECT_REASON: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_payment_reject_reason),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_admin)],
        per_message=False,
    ))

    # ── Admin: coach reject reason capture ──
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_coach_reject_start, pattern=r"^coach_reject:")],
        states={
            COACH_REJECT_REASON: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_coach_reject_reason),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_admin)],
        per_message=False,
    ))

    # ── Nutrition intake ──
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("diet", start_diet)],
        states={
            DN_WEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, dn_weight)],
            DN_HEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, dn_height)],
            DN_AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, dn_age)],
            DN_SEX: [CallbackQueryHandler(dn_sex, pattern=r"^dn_sex_")],
            DN_BODYFAT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, dn_bodyfat),
                CommandHandler("skip", dn_bodyfat),
            ],
            DN_GOAL: [CallbackQueryHandler(dn_goal, pattern=r"^dn_goal_")],
            DN_AGGRESSIVENESS: [CallbackQueryHandler(dn_aggressiveness, pattern=r"^dn_agg_")],
            DN_ACTIVITY: [CallbackQueryHandler(dn_activity, pattern=r"^dn_act_")],
            DN_TARGET_RATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, dn_target_rate),
                CommandHandler("skip", dn_target_rate),
            ],
            DN_DIET_STYLE: [CallbackQueryHandler(dn_diet_style, pattern=r"^dn_diet_")],
            DN_ALLERGIES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, dn_allergies),
                CommandHandler("skip", dn_allergies),
            ],
            DN_DISLIKES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, dn_dislikes),
                CommandHandler("skip", dn_dislikes),
            ],
            DN_RELIGIOUS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, dn_religious),
                CommandHandler("skip", dn_religious),
            ],
            DN_MEALS: [CallbackQueryHandler(dn_meals, pattern=r"^dn_meals_")],
            DN_COOKING_SKILL: [CallbackQueryHandler(dn_cooking_skill, pattern=r"^dn_skill_")],
            DN_COOKING_TIME: [CallbackQueryHandler(dn_cooking_time, pattern=r"^dn_time_")],
            DN_BUDGET: [CallbackQueryHandler(dn_budget, pattern=r"^dn_budget_")],
            DN_MEDICAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, dn_medical),
                CommandHandler("skip", dn_medical),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
    ))

    # ── /log ConversationHandler ──
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("log", start_log)],
        states={
            LOG_SELECT_DAY: [CallbackQueryHandler(handle_log_select_day, pattern=r"^log_day_\d+$")],
            LOG_SELECT_EXERCISE: [CallbackQueryHandler(handle_log_select_exercise, pattern=r"^log_ex_\d+$")],
            LOG_WEIGHT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_log_weight),
                CommandHandler("skip", handle_log_weight),
            ],
            LOG_RPE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_log_rpe),
                CommandHandler("skip", handle_log_rpe),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
    ))

    # ── Client commands ──
    app.add_handler(CommandHandler("plan", client_plan))
    app.add_handler(CommandHandler("help", handle_help))
    app.add_handler(CommandHandler("pick_coach", cmd_pick_coach))

    # ── Admin commands ──
    app.add_handler(CommandHandler("review", admin_review))
    app.add_handler(CommandHandler("review_batch", admin_review_batch))
    app.add_handler(CommandHandler("override", handle_override))

    # ── Standalone callbacks / handlers ──
    app.add_handler(CallbackQueryHandler(handle_plan_full_week, pattern=r"^plan_full_week$"))
    app.add_handler(CallbackQueryHandler(handle_open_pending_item, pattern=r"^open_pending:"))
    app.add_handler(CallbackQueryHandler(handle_admin_approve, pattern=r"^approve:"))
    app.add_handler(CallbackQueryHandler(handle_admin_approve_confirmed, pattern=r"^approve_confirmed:"))
    # Coach "add core at verification": pick day -> pick exercise -> re-render review.
    app.add_handler(CallbackQueryHandler(handle_add_core_day, pattern=r"^addcore_d:"))
    app.add_handler(CallbackQueryHandler(handle_add_core_exercise, pattern=r"^addcore_x:"))
    app.add_handler(CallbackQueryHandler(handle_add_core_back, pattern=r"^addcore_back:"))
    app.add_handler(CallbackQueryHandler(handle_add_core_start, pattern=r"^addcore:"))
    app.add_handler(CallbackQueryHandler(handle_fc_confirm, pattern=r"^fc_confirm_"))
    app.add_handler(CallbackQueryHandler(handle_nutrition_approve, pattern=r"^nutrapprove:"))
    app.add_handler(CallbackQueryHandler(handle_nutrition_discard, pattern=r"^nutrdiscard:"))
    app.add_handler(CallbackQueryHandler(handle_plan_ack, pattern=r"^ack_(good|ok)$"))
    app.add_handler(CallbackQueryHandler(handle_review_toggle, pattern=r"^review_toggle_batch$"))
    app.add_handler(CallbackQueryHandler(handle_override_remove, pattern=r"^override_remove:"))
    app.add_handler(CallbackQueryHandler(handle_safety_clear, pattern=r"^safety_clear:"))
    app.add_handler(CallbackQueryHandler(handle_payment_verify, pattern=r"^pay_verify:"))
    app.add_handler(CallbackQueryHandler(handle_coach_verify, pattern=r"^coach_verify:"))
    app.add_handler(CallbackQueryHandler(handle_coach_picker_list, pattern=r"^cp_list:"))
    app.add_handler(CallbackQueryHandler(handle_coach_picker_pick, pattern=r"^cp_pick:"))
    app.add_handler(CallbackQueryHandler(handle_coach_picker_admin, pattern=r"^cp_admin:"))
    app.add_handler(CallbackQueryHandler(handle_coach_picker_back, pattern=r"^cp_back:"))
    app.add_handler(CallbackQueryHandler(handle_admin_assign, pattern=r"^admin_assign:"))

    # Route reply-to-forwarded-video messages back to clients. Filter is broad
    # (any reply); the handler does the role + scope check at runtime so super-
    # admin and any approved coach can both route feedback.
    app.add_handler(MessageHandler(
        filters.REPLY & filters.TEXT,
        handle_admin_video_reply,
    ))

    # 24h plan acknowledgment check (runs on all client messages, group=-1 = before other handlers)
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, check_plan_acknowledgment),
        group=-1,
    )

    # ── Global error handler ──
    app.add_error_handler(handle_error)

    # ── Graceful shutdown on SIGTERM/SIGINT ──
    def _shutdown(signum: int, frame: object) -> None:
        logging.info("Received signal %d — shutting down gracefully", signum)
        app.stop_running()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    logging.info("Bot starting…")
    app.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    main()
