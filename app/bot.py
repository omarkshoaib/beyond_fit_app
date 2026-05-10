import os
import uuid
import json
import signal
import hashlib
import logging
import traceback
import time
from collections import defaultdict
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
    AccessCode, Payment, Subscription, ChatBinding, CoachProfile,
)
from app.database import engine, create_db_and_tables
from app.auth import roles as auth_roles
from app.settings import get_settings
from app.adapters.llm.extractors import extract_checkin, render_digest
from app.adapters.llm.openrouter import OpenRouterClient
from app.domain.workout.autoregulation import derive_plan_delta, apply_delta

load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)


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


# ── FAQ rate limiter (5 questions / chat / hour) ───────────────────────────────
# Maps chat_id → list of monotonic timestamps within the rolling window.
_faq_recent_calls: dict[int, list[float]] = defaultdict(list)


def _faq_rate_check(chat_id: int) -> bool:
    """Return True if the chat is allowed another FAQ call. Side effect: records the call."""
    settings = get_settings()
    limit = max(1, settings.faq_rate_limit_per_hour)
    window_seconds = 3600.0
    now = time.monotonic()
    bucket = _faq_recent_calls[chat_id]
    # Drop expired timestamps.
    bucket[:] = [t for t in bucket if now - t < window_seconds]
    if len(bucket) >= limit:
        return False
    bucket.append(now)
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

        admin_chat_id = _admin_chat_id()
        if admin_chat_id is not None:
            keyboard = [[
                InlineKeyboardButton("✅ Approve", callback_data=f"approve:{approval_id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject:{approval_id}"),
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
                context.bot, admin_chat_id, admin_text,
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

async def start_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point for /start. Dispatches by chat-binding status:

      - Bound chat → "Welcome back" (legacy).
      - Unbound chat → 3-button pre-payment menu.
    """
    chat_id = update.effective_chat.id
    client = auth_roles.get_authenticated_client(chat_id)

    if client is not None:
        # Returning client (any device bound to this chat).
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
        f"💳 *Payment pending* (id `{payment_id}`)\n"
        f"From: *{sender_name}* (chat `{chat_id}`)\n"
        f"Plan: {months} — EGP {amount}\n"
        f"Tentative client_id: `{client_id}`"
    )
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Verify", callback_data=f"pay_verify:{payment_id}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"pay_reject:{payment_id}"),
    ]])
    await context.bot.send_photo(
        chat_id=sa_id,
        photo=file_id,
        caption=caption,
        parse_mode="Markdown",
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

        # 4. Bind the originating chat as primary.
        session.add(ChatBinding(
            chat_id=chat_id,
            client_id=client_id,
            bound_at=now,
            is_primary=True,
        ))

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

    # DM the client: code + warning + setup button.
    code_text = (
        "✅ *Payment verified!*\n\n"
        f"Your access code (don't share with anyone):\n\n`{code}`\n\n"
        "Save it somewhere safe. You can use it to log in from another device.\n\n"
        "Tap below to finish setting up your profile."
    )
    setup_btn = InlineKeyboardMarkup([[InlineKeyboardButton("👉 Begin setup", callback_data="setup_begin")]])
    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=code_text,
            parse_mode="Markdown",
            reply_markup=setup_btn,
        )
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
    if "@" not in email or " " in email or len(email) > 120:
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
        bundle = (
            "🧑‍🏫 *New coach application*\n"
            f"• Name: *{coach.name}*\n"
            f"• Email: `{coach.email}`\n"
            f"• Mobile: `{coach.mobile}`\n"
            f"• Specialty: {spec_label}\n"
            f"• Experience: {coach.years_experience} years\n"
            f"• Certifications: {coach.certifications}\n"
            f"• Portfolio: {portfolio or '—'}\n"
            f"• Telegram user id: `{user_id}`"
        )
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Approve", callback_data=f"coach_verify:{user_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"coach_reject:{user_id}"),
        ]])
        try:
            await context.bot.send_message(
                chat_id=sa_id, text=bundle, parse_mode="Markdown", reply_markup=keyboard,
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
            text=f"✅ Welcome aboard, *{coach.name}*! You've been approved as a coach.\n"
                 "You'll receive client plans for review here.",
            parse_mode="Markdown",
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
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return ASK_DAYS


async def handle_days(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data['days'] = int(query.data)

    keyboard = [
        [InlineKeyboardButton("Beginner", callback_data="beginner")],
        [InlineKeyboardButton("Intermediate", callback_data="intermediate")],
        [InlineKeyboardButton("Advanced", callback_data="advanced")],
    ]
    await query.edit_message_text("What is your experience level?", reply_markup=InlineKeyboardMarkup(keyboard))
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


async def handle_experience(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data['experience_level'] = query.data
    context.user_data['selected_limitations'] = set()
    await query.edit_message_text(
        f"Awesome, {query.data.title()}!\n\nSelect any injuries or limitations:",
        reply_markup=_build_limitations_keyboard(set()),
    )
    return ASK_LIMITATIONS


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
    await query.edit_message_reply_markup(reply_markup=_build_limitations_keyboard(selected))
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
            "Please describe your limitation in one sentence (e.g. 'recovering from ankle sprain'):"
        )
        return ASK_LIMITATIONS_OTHER

    if "none" in selected or not selected:
        context.user_data['limitations'] = []
    else:
        context.user_data['limitations'] = sorted(selected)

    await query.edit_message_text("Almost there! What's your email address? (We'll send your plan PDF here.)")
    return ASK_EMAIL


async def handle_limitations_other(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store free-text limitation note and proceed to email."""
    context.user_data['limitations_notes'] = update.message.text.strip()
    await update.message.reply_text("Almost there! What's your email address? (We'll send your plan PDF here.)")
    return ASK_EMAIL


async def handle_limitations(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Legacy free-text fallback for limitations (kept for backwards compat)."""
    text = update.message.text.strip().lower()
    context.user_data['limitations'] = [] if text == "none" else [l.strip() for l in text.split(",")]
    await update.message.reply_text("Almost there! What's your email address? (We'll send your plan PDF here.)")
    return ASK_EMAIL


async def handle_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    email = update.message.text.strip()
    context.user_data['email'] = email

    updating = context.user_data.get('update_profile_mode', False)
    # Post-verify intake stashes the real client_id; otherwise look up by chat binding.
    intake_client_id = context.user_data.get('intake_client_id')
    client = auth_roles.get_authenticated_client(update.effective_chat.id)
    client_id = intake_client_id or (client.client_id if client else str(update.effective_user.id))

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
                profile.available_equipment = profile.available_equipment or ["full_gym"]
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
                available_equipment=["full_gym"],
                week_number=1,
                email=email,
                name=first_name,
                limitations_notes=context.user_data.get('limitations_notes'),
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


async def start_update_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point for /update_profile — reuses intake flow with pre-filled values."""
    client_id = str(update.effective_user.id)
    with Session(engine) as session:
        profile = session.get(ClientProfile, client_id)

    if not profile:
        await update.message.reply_text("No profile found. Use /start to create one first.")
        return ConversationHandler.END

    context.user_data['update_profile_mode'] = True
    context.user_data['avatar'] = profile.avatar
    context.user_data['days'] = profile.training_days
    context.user_data['experience_level'] = profile.experience_level
    context.user_data['limitations'] = profile.limitations or []

    avatar_display = {"powerlifter": "Powerlifter", "powerbuilder": "Powerbuilder", "gen_pop": "General Fitness"}.get(profile.avatar, profile.avatar)
    keyboard = [[
        InlineKeyboardButton("Powerlifter", callback_data="powerlifter"),
        InlineKeyboardButton("Powerbuilder", callback_data="powerbuilder"),
    ], [
        InlineKeyboardButton("General Fitness", callback_data="gen_pop"),
    ]]
    await update.message.reply_text(
        f"Updating your profile (current: *{avatar_display}*, *{profile.training_days} days*, *{profile.experience_level}*).\n\n"
        "What is your training goal?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return ASK_AVATAR


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


async def start_checkin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    client_id = str(update.effective_user.id)

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
    context.user_data["checkin_lift_catalog"] = [
        slot.exercise_name
        for day in week.days
        for slot in day.slots
        if slot.slot_type in ("main_compound", "secondary_compound")
    ]
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
        context.user_data["checkin_structured_slots"] = [
            {"day": d, "exercise_id": s.exercise_id, "exercise_name": s.exercise_name, "rpe": s.rpe}
            for d, s in main_slots
        ]
        context.user_data["checkin_current_slot_idx"] = 0
        context.user_data["checkin_structured_results"] = {}

        first = context.user_data["checkin_structured_slots"][0]
        await update.message.reply_text(
            f"📋 *Week {week.week_number} Check-in*\n\n"
            f"Let's log your main lifts one by one.\n\n"
            f"*{first['exercise_name']}* ({first['day']}) — what was your top-set weight? (kg, e.g. `100`)",
            parse_mode="Markdown",
        )
        return CHECKIN_EX_WEIGHT

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
        await query.edit_message_text(
            f"Resuming — *{slot['exercise_name']}* ({slot['day']}) — "
            "what was your top-set weight? (kg)",
            parse_mode="Markdown",
        )
        return CHECKIN_EX_WEIGHT

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
    _persist_checkin_progress(str(update.effective_user.id), context)

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
        await query.edit_message_text(
            f"*{next_slot['exercise_name']}* ({next_slot['day']}) — what was your top-set weight? (kg)",
            parse_mode="Markdown",
        )
        return CHECKIN_EX_WEIGHT

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
    client_id = str(update.effective_user.id)
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
        summary = _build_client_summary(str(update.effective_user.id))
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
    client_id = str(
        msg_or_query.from_user.id if hasattr(msg_or_query, "from_user")
        else msg_or_query.message.from_user.id
    )

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

        client_id = str(query.from_user.id)
        with Session(engine, expire_on_commit=False) as session:
            profile = session.get(ClientProfile, client_id)
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
    client_id = str(update.effective_user.id)
    admin_chat_id = _admin_chat_id()

    if not update.message.video and not update.message.document:
        await update.message.reply_text("Please send a video file. Try again or /cancel.")
        return FORMCHECK_VIDEO

    if admin_chat_id is None:
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
            chat_id=admin_chat_id,
            video=update.message.video.file_id,
            caption=caption,
            parse_mode="Markdown",
        )
    else:
        fwd = await context.bot.send_document(
            chat_id=admin_chat_id,
            document=update.message.document.file_id,
            caption=caption,
            parse_mode="Markdown",
        )

    # Map admin's forwarded message ID → client chat ID so we can route the reply
    context.application.bot_data.setdefault("video_reviews", {})[fwd.message_id] = {
        "client_chat_id": update.effective_chat.id,
        "client_name": update.effective_user.first_name,
        "exercise_name": ex_name,
    }

    await update.message.reply_text(
        f"✅ Video sent to Coach Shoaib! You'll receive feedback here once he reviews it."
    )
    return ConversationHandler.END


# ── NUTRITION INTAKE FLOW ─────────────────────────────────────────────────────

def _dn(context: ContextTypes.DEFAULT_TYPE) -> dict:
    if "dn_data" not in context.user_data:
        context.user_data["dn_data"] = {}
    return context.user_data["dn_data"]


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
    keyboard = [
        [InlineKeyboardButton("⚖️ Balanced", callback_data="dn_diet_balanced")],
        [InlineKeyboardButton("🥩 Omnivore", callback_data="dn_diet_omnivore"),
         InlineKeyboardButton("🥗 Vegetarian", callback_data="dn_diet_vegetarian")],
        [InlineKeyboardButton("🌱 Vegan", callback_data="dn_diet_vegan"),
         InlineKeyboardButton("🐟 Pescatarian", callback_data="dn_diet_pescatarian")],
        [InlineKeyboardButton("🥚 Keto", callback_data="dn_diet_keto")],
    ]
    text = "*Step 10 of 18:* What is your dietary style?"
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

    client_id = str(update.effective_user.id)
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

    admin_chat_id = _admin_chat_id()
    if admin_chat_id is not None:
        keyboard = [[
            InlineKeyboardButton("✅ Activate plan", callback_data=f"nutrapprove:{plan.id}"),
            InlineKeyboardButton("❌ Discard", callback_data=f"nutrdiscard:{plan.id}"),
        ]]
        summary = _build_client_summary(str(update.effective_user.id))
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
            context.bot, admin_chat_id, admin_text,
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
            plan.status = "rejected"
            session.add(plan)
            session.commit()

    await query.edit_message_text("❌ Nutrition plan discarded.")


# ── ADMIN: VIDEO REPLY ROUTING ─────────────────────────────────────────────────

async def handle_admin_video_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route admin's reply to a form-check video back to the client."""
    if not update.message.reply_to_message:
        return

    replied_id = update.message.reply_to_message.message_id
    video_reviews = context.application.bot_data.get("video_reviews", {})
    entry = video_reviews.get(replied_id)
    if not entry:
        return

    client_chat_id = entry["client_chat_id"]
    ex_name = entry["exercise_name"]
    coach_name = update.effective_user.first_name

    await context.bot.send_message(
        chat_id=client_chat_id,
        text=(
            f"🎥 *Form check feedback from Coach {coach_name}*\n"
            f"Exercise: _{ex_name}_\n\n"
            f"{update.message.text}"
        ),
        parse_mode="Markdown",
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
            logging.error("Coach edit error: %s", exc)
            await update.message.reply_text("Failed to apply edits. Be more specific.")

    return ConversationHandler.END


async def cancel_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


# ── ADMIN: /review COMMAND ─────────────────────────────────────────────────────

async def client_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show today's session by default; /plan week shows the full week."""
    client_id = str(update.effective_user.id)
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

    client_id = str(update.effective_user.id)
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
    """Show index card of all pending approvals; admin taps [Open] to expand each one."""
    admin_id = _admin_chat_id()
    if admin_id is None or update.effective_user.id != admin_id:
        return

    with Session(engine) as session:
        pending_workouts = session.exec(
            select(PendingApproval).order_by(PendingApproval.created_at)
        ).all()
        pending_nutrition = session.exec(
            select(NutritionPlan).where(NutritionPlan.status == "draft")
        ).all()

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
        all_profiles = session.exec(select(ClientProfile)).all()
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
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Approve", callback_data=f"approve:{approval_id}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"reject:{approval_id}"),
    ]])
    await safe_send_markdown(context.bot, query.message.chat_id, msg, reply_markup=keyboard)


async def admin_review_batch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/review_batch — groups pending plans by avatar+days bucket for efficient batch review."""
    admin_id = _admin_chat_id()
    if admin_id is None or update.effective_user.id != admin_id:
        return

    with Session(engine) as session:
        pending_workouts = session.exec(
            select(PendingApproval).order_by(PendingApproval.created_at)
        ).all()

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
    """Log all unhandled exceptions and notify the admin (deduplicated, count-edited within 5-min window)."""
    tb = "".join(traceback.format_exception(type(context.error), context.error, context.error.__traceback__))
    logging.error("Unhandled exception:\n%s", tb)

    sig = hashlib.md5(str(context.error)[:200].encode()).hexdigest()
    now = time.monotonic()
    short_tb = tb[-3000:] if len(tb) > 3000 else tb
    admin_id = _admin_chat_id()

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

async def start_log(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """/log — manually log weight/RPE for any exercise in the active plan."""
    client_id = str(update.effective_user.id)

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

    client_id = str(update.effective_user.id)
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
        await query.edit_message_text(
            "Feel free to ask your question anytime — your coach will reply here."
        )
    else:
        label = "Great!" if query.data == "ack_good" else "Noted — keep going!"
        await query.edit_message_text(label)


# ── /override COMMAND — coach exercise substitution ────────────────────────────

async def handle_override(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/override [client_id] [from_id] [to_id] — set, list, or remove exercise overrides."""
    admin_id = _admin_chat_id()
    if admin_id is None or update.effective_user.id != admin_id:
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
    """Admin marks a client as cleared by physician, bypassing the safety gate."""
    query = update.callback_query
    await query.answer()

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
    "/start — create your profile & get your first plan\n"
    "/checkin — log this week's sessions (main lifts)\n"
    "/log — manually log weight/RPE for any exercise\n"
    "/plan — view your current plan (today's session by default)\n"
    "/diet — set up your nutrition profile\n"
    "/cancel — cancel the current action"
)

_ADMIN_HELP = (
    "/review — pending plan approvals\n"
    "/review_batch — group pending plans by training type\n"
    "/override &lt;client_id&gt; &lt;from_id&gt; &lt;to_id&gt; — substitute an exercise\n"
    "/override &lt;client_id&gt; — list/remove overrides\n"
    "/help — this message"
)


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    admin_id = _admin_chat_id()
    is_admin = admin_id is not None and update.effective_user.id == admin_id
    text = f"<b>Client commands:</b>\n{_CLIENT_HELP}"
    if is_admin:
        text += f"\n\n<b>Admin commands:</b>\n{_ADMIN_HELP}"
    await update.message.reply_text(text, parse_mode="HTML")


# ── MAIN ───────────────────────────────────────────────────────────────────────

def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logging.error("No TELEGRAM_BOT_TOKEN found.")
        return

    admin_id = _admin_chat_id()
    if admin_id is None:
        logging.error("ADMIN_CHAT_ID not set — admin commands will not work")

    create_db_and_tables()
    app = ApplicationBuilder().token(token).build()

    _intake_states = {
        ASK_AVATAR: [CallbackQueryHandler(handle_avatar, pattern=r"^(powerlifter|powerbuilder|gen_pop)$")],
        ASK_DAYS: [CallbackQueryHandler(handle_days, pattern=r"^(3|4|5|6)$")],
        ASK_EXPERIENCE: [CallbackQueryHandler(handle_experience, pattern=r"^(beginner|intermediate|advanced)$")],
        ASK_LIMITATIONS: [
            CallbackQueryHandler(handle_limitations_toggle, pattern=r"^lim_toggle_"),
            CallbackQueryHandler(handle_limitations_confirm, pattern=r"^lim_confirm$"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_limitations),
        ],
        ASK_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_email)],
        ASK_LIMITATIONS_OTHER: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_limitations_other)],
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

    # ── Update profile ──
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("update_profile", start_update_profile)],
        states=_intake_states,
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

    # ── Admin commands ──
    app.add_handler(CommandHandler("review", admin_review))
    app.add_handler(CommandHandler("review_batch", admin_review_batch))
    app.add_handler(CommandHandler("override", handle_override))

    # ── Standalone callbacks / handlers ──
    app.add_handler(CallbackQueryHandler(handle_plan_full_week, pattern=r"^plan_full_week$"))
    app.add_handler(CallbackQueryHandler(handle_open_pending_item, pattern=r"^open_pending:"))
    app.add_handler(CallbackQueryHandler(handle_admin_approve, pattern=r"^approve:"))
    app.add_handler(CallbackQueryHandler(handle_admin_approve_confirmed, pattern=r"^approve_confirmed:"))
    app.add_handler(CallbackQueryHandler(handle_fc_confirm, pattern=r"^fc_confirm_"))
    app.add_handler(CallbackQueryHandler(handle_nutrition_approve, pattern=r"^nutrapprove:"))
    app.add_handler(CallbackQueryHandler(handle_nutrition_discard, pattern=r"^nutrdiscard:"))
    app.add_handler(CallbackQueryHandler(handle_plan_ack, pattern=r"^ack_"))
    app.add_handler(CallbackQueryHandler(handle_review_toggle, pattern=r"^review_toggle_batch$"))
    app.add_handler(CallbackQueryHandler(handle_override_remove, pattern=r"^override_remove:"))
    app.add_handler(CallbackQueryHandler(handle_safety_clear, pattern=r"^safety_clear:"))
    app.add_handler(CallbackQueryHandler(handle_payment_verify, pattern=r"^pay_verify:"))
    app.add_handler(CallbackQueryHandler(handle_coach_verify, pattern=r"^coach_verify:"))

    # Route admin replies to form-check videos back to clients
    admin_chat_id = _admin_chat_id()
    if admin_chat_id is not None:
        app.add_handler(MessageHandler(
            filters.Chat(admin_chat_id) & filters.REPLY & filters.TEXT,
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
