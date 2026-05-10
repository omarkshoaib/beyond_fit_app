"""Phase D: coach application flow + admin approve/reject."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlmodel import Session, select

from app.bot import (
    COACH_APPLY_NAME, COACH_APPLY_EMAIL, COACH_APPLY_MOBILE,
    COACH_APPLY_SPECIALTY, COACH_APPLY_YEARS, COACH_APPLY_CERTS,
    COACH_APPLY_CV, COACH_APPLY_PORTFOLIO, COACH_REJECT_REASON,
    coach_apply_name, coach_apply_email, coach_apply_mobile,
    coach_apply_specialty, coach_apply_years, coach_apply_certs,
    coach_apply_cv, coach_apply_portfolio,
    handle_coach_verify, handle_coach_reject_start, handle_coach_reject_reason,
    handle_menu_coach,
)
from app.models import CoachProfile
from tests.conftest import make_callback_update, make_context, make_text_update


SUPER_ADMIN_ID = 4242


def _patch_roles(monkeypatch, engine, super_admin_id=SUPER_ADMIN_ID):
    import app.auth.roles as roles_mod
    monkeypatch.setattr(roles_mod, "engine", engine)
    fake = type("S", (), {
        "super_admin_telegram_user_id": super_admin_id,
        "admin_chat_id": None,
        "subscription_price_1m_egp": 1500,
        "subscription_price_3m_egp": 3500,
        "instapay_payee_handle": "@x",
        "instapay_display_name": "X",
        "faq_rate_limit_per_hour": 5,
    })()
    monkeypatch.setattr(roles_mod, "get_settings", lambda: fake)
    import app.bot as bot_mod
    monkeypatch.setattr(bot_mod, "get_settings", lambda: fake)
    roles_mod.invalidate_coach_cache()


def _make_app_context(mock_bot):
    ctx = make_context(mock_bot)
    ctx.application = MagicMock()
    ctx.application.bot_data = {}
    return ctx


def _admin_cb(mock_bot, user_id, data):
    return SimpleNamespace(
        callback_query=SimpleNamespace(
            data=data,
            message=SimpleNamespace(caption=""),
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
            edit_message_caption=AsyncMock(),
        ),
        effective_user=SimpleNamespace(id=user_id),
        effective_chat=SimpleNamespace(id=user_id),
        effective_message=SimpleNamespace(reply_text=AsyncMock()),
    )


# ── Apply path: state transitions ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_application_creates_pending_row(monkeypatch, test_engine, mock_bot):
    _patch_roles(monkeypatch, test_engine)
    ctx = _make_app_context(mock_bot)

    user_id = 7777

    # name → email → mobile → specialty → years → certs → cv (skip) → portfolio (skip)
    s = await coach_apply_name(make_text_update(mock_bot, user_id=user_id, text="Jane Lifter"), ctx)
    assert s == COACH_APPLY_EMAIL
    s = await coach_apply_email(make_text_update(mock_bot, user_id=user_id, text="jane@x.com"), ctx)
    assert s == COACH_APPLY_MOBILE
    s = await coach_apply_mobile(make_text_update(mock_bot, user_id=user_id, text="+201234567890"), ctx)
    assert s == COACH_APPLY_SPECIALTY
    s = await coach_apply_specialty(make_callback_update(mock_bot, user_id=user_id, data="coach_spec:powerbuilding"), ctx)
    assert s == COACH_APPLY_YEARS
    s = await coach_apply_years(make_text_update(mock_bot, user_id=user_id, text="6"), ctx)
    assert s == COACH_APPLY_CERTS
    s = await coach_apply_certs(make_text_update(mock_bot, user_id=user_id, text="NSCA-CSCS, NASM-PES"), ctx)
    assert s == COACH_APPLY_CV
    s = await coach_apply_cv(make_text_update(mock_bot, user_id=user_id, text="/skip"), ctx)
    assert s == COACH_APPLY_PORTFOLIO
    await coach_apply_portfolio(make_text_update(mock_bot, user_id=user_id, text="Trained 200+ clients."), ctx)

    with Session(test_engine) as session:
        coach = session.get(CoachProfile, user_id)
    assert coach is not None
    assert coach.status == "pending"
    assert coach.name == "Jane Lifter"
    assert coach.email == "jane@x.com"
    assert coach.specialty == "powerbuilding"
    assert coach.years_experience == 6
    assert coach.cv_file_id is None
    assert "200+" in coach.portfolio_text

    # Super-admin got the bundle.
    sent = mock_bot.send_message.await_args_list
    assert any(SUPER_ADMIN_ID == c.kwargs.get("chat_id") for c in sent)


@pytest.mark.asyncio
async def test_invalid_email_stays_in_state(monkeypatch, test_engine, mock_bot):
    _patch_roles(monkeypatch, test_engine)
    ctx = _make_app_context(mock_bot)
    s = await coach_apply_email(make_text_update(mock_bot, user_id=1, text="notanemail"), ctx)
    assert s == COACH_APPLY_EMAIL


@pytest.mark.asyncio
async def test_years_must_be_int(monkeypatch, test_engine, mock_bot):
    _patch_roles(monkeypatch, test_engine)
    ctx = _make_app_context(mock_bot)
    s = await coach_apply_years(make_text_update(mock_bot, user_id=1, text="five"), ctx)
    assert s == COACH_APPLY_YEARS


@pytest.mark.asyncio
async def test_existing_application_blocks_re_entry(monkeypatch, test_engine, mock_bot):
    _patch_roles(monkeypatch, test_engine)
    user_id = 9001
    with Session(test_engine) as s:
        s.add(CoachProfile(
            telegram_user_id=user_id,
            name="X", email="x@x", mobile="1", specialty="gen_pop",
            years_experience=1, certifications="—", status="pending",
        ))
        s.commit()
    ctx = _make_app_context(mock_bot)
    update = SimpleNamespace(
        callback_query=SimpleNamespace(
            data="menu_coach",
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
        ),
        effective_user=SimpleNamespace(id=user_id),
        effective_chat=SimpleNamespace(id=user_id),
        effective_message=SimpleNamespace(reply_text=AsyncMock()),
    )
    from telegram.ext import ConversationHandler
    state = await handle_menu_coach(update, ctx)
    assert state == ConversationHandler.END


# ── Approve path ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_coach_verify_approves_and_invalidates_cache(monkeypatch, test_engine, mock_bot):
    _patch_roles(monkeypatch, test_engine)
    user_id = 5555
    with Session(test_engine) as s:
        s.add(CoachProfile(
            telegram_user_id=user_id,
            name="Bob", email="b@x", mobile="1", specialty="powerlifting",
            years_experience=3, certifications="—", status="pending",
        ))
        s.commit()

    import app.auth.roles as roles
    # Prime negative cache.
    assert roles.is_coach(user_id) is False

    update = _admin_cb(mock_bot, SUPER_ADMIN_ID, f"coach_verify:{user_id}")
    await handle_coach_verify(update, _make_app_context(mock_bot))

    with Session(test_engine) as s:
        coach = s.get(CoachProfile, user_id)
    assert coach.status == "approved"

    # Cache was invalidated → fresh lookup returns True.
    assert roles.is_coach(user_id) is True

    # Coach got DM.
    welcome_dms = [c for c in mock_bot.send_message.await_args_list
                   if c.kwargs.get("chat_id") == user_id]
    assert any("approved" in c.kwargs.get("text", "").lower() for c in welcome_dms)


@pytest.mark.asyncio
async def test_coach_verify_rejects_non_super_admin(monkeypatch, test_engine, mock_bot):
    _patch_roles(monkeypatch, test_engine)
    user_id = 6666
    with Session(test_engine) as s:
        s.add(CoachProfile(
            telegram_user_id=user_id, name="C", email="c@x", mobile="1",
            specialty="gen_pop", years_experience=1, certifications="—",
            status="pending",
        ))
        s.commit()
    update = _admin_cb(mock_bot, 12345, f"coach_verify:{user_id}")
    await handle_coach_verify(update, _make_app_context(mock_bot))
    with Session(test_engine) as s:
        coach = s.get(CoachProfile, user_id)
    assert coach.status == "pending"


# ── Reject path ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_coach_reject_sets_status_with_reason(monkeypatch, test_engine, mock_bot):
    _patch_roles(monkeypatch, test_engine)
    user_id = 4321
    with Session(test_engine) as s:
        s.add(CoachProfile(
            telegram_user_id=user_id, name="D", email="d@x", mobile="1",
            specialty="bodybuilding", years_experience=2, certifications="—",
            status="pending",
        ))
        s.commit()

    ctx = _make_app_context(mock_bot)
    update_click = _admin_cb(mock_bot, SUPER_ADMIN_ID, f"coach_reject:{user_id}")
    state = await handle_coach_reject_start(update_click, ctx)
    assert state == COACH_REJECT_REASON

    update_text = make_text_update(mock_bot, user_id=SUPER_ADMIN_ID, text="Insufficient experience.")
    await handle_coach_reject_reason(update_text, ctx)

    with Session(test_engine) as s:
        coach = s.get(CoachProfile, user_id)
    assert coach.status == "rejected"
    assert "Insufficient" in coach.rejection_reason
