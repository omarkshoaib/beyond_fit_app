"""Tests for the field-picker /update_profile conversation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlmodel import Session
from telegram.ext import ConversationHandler

from app.bot import (
    UPD_AVATAR,
    UPD_DAYS,
    UPD_EMAIL,
    UPD_EXP,
    UPD_LIM,
    UPD_PICK,
    start_update_profile,
    upd_lim_confirm,
    upd_pick,
    upd_set_days,
    upd_set_email,
    upd_set_exp,
    upd_set_goal,
)
from app.models import (
    ChatBinding,
    ClientProfile,
    Subscription,
)


CLIENT_CHAT_ID = 7777
CLIENT_ID = "cl_testupd001"


def _seed(engine, *, with_subscription: bool = True) -> None:
    """Insert a paid client + subscription so requires_active_sub passes."""
    with Session(engine) as s:
        s.add(ClientProfile(
            client_id=CLIENT_ID,
            avatar="gen_pop",
            training_days=3,
            experience_level="beginner",
            limitations=[],
            available_equipment=["full_gym"],
            week_number=1,
            email="old@example.com",
            name="ClientName",
            assigned_coach_id=42,
        ))
        s.add(ChatBinding(
            chat_id=CLIENT_CHAT_ID,
            client_id=CLIENT_ID,
            is_primary=True,
            bound_at=datetime.now(timezone.utc).replace(tzinfo=None),
        ))
        if with_subscription:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            s.add(Subscription(
                client_id=CLIENT_ID,
                plan_type="1m",
                started_at=now,
                ends_at=now + timedelta(days=20),
                status="active",
                created_at=now,
            ))
        s.commit()


def _patch_engine(monkeypatch, engine):
    import app.auth.roles as roles_mod
    monkeypatch.setattr(roles_mod, "engine", engine)


def _text_update(text: str) -> SimpleNamespace:
    msg = SimpleNamespace(
        text=text,
        reply_text=AsyncMock(),
        chat_id=CLIENT_CHAT_ID,
    )
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=CLIENT_CHAT_ID, first_name="ClientName"),
        effective_chat=SimpleNamespace(id=CLIENT_CHAT_ID),
        effective_message=msg,
        message=msg,
    )


def _cb_update(data: str) -> SimpleNamespace:
    msg = SimpleNamespace(chat_id=CLIENT_CHAT_ID)
    cq = SimpleNamespace(
        data=data,
        message=msg,
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
        edit_message_reply_markup=AsyncMock(),
    )
    return SimpleNamespace(
        callback_query=cq,
        effective_user=SimpleNamespace(id=CLIENT_CHAT_ID, first_name="ClientName"),
        effective_chat=SimpleNamespace(id=CLIENT_CHAT_ID),
        effective_message=msg,
        message=msg,
    )


def _ctx(mock_bot, *, user_data: dict | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.user_data = user_data if user_data is not None else {}
    ctx.bot = mock_bot
    return ctx


# ── entry point ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_shows_picker_menu(monkeypatch, test_engine, mock_bot):
    _patch_engine(monkeypatch, test_engine)
    _seed(test_engine)
    update = _text_update("/update_profile")
    ctx = _ctx(mock_bot)

    state = await start_update_profile(update, ctx)

    assert state == UPD_PICK
    update.message.reply_text.assert_awaited_once()
    # Helper stashes client_id and clears dirty flag.
    assert ctx.user_data["upd_client_id"] == CLIENT_ID
    assert ctx.user_data["upd_dirty"] is False


@pytest.mark.asyncio
async def test_start_blocks_when_subscription_expired(monkeypatch, test_engine, mock_bot):
    _patch_engine(monkeypatch, test_engine)
    _seed(test_engine, with_subscription=False)
    update = _text_update("/update_profile")
    state = await start_update_profile(update, _ctx(mock_bot))
    # requires_active_sub returns None on gate-fail.
    assert state is None
    update.message.reply_text.assert_awaited()


# ── picker routing ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pick_goal_routes_to_avatar(monkeypatch, test_engine, mock_bot):
    _patch_engine(monkeypatch, test_engine)
    _seed(test_engine)
    update = _cb_update("upd:goal")
    state = await upd_pick(update, _ctx(mock_bot, user_data={"upd_client_id": CLIENT_ID}))
    assert state == UPD_AVATAR


@pytest.mark.asyncio
async def test_pick_days_routes_to_days(monkeypatch, test_engine, mock_bot):
    _patch_engine(monkeypatch, test_engine)
    _seed(test_engine)
    state = await upd_pick(_cb_update("upd:days"), _ctx(mock_bot, user_data={"upd_client_id": CLIENT_ID}))
    assert state == UPD_DAYS


@pytest.mark.asyncio
async def test_pick_email_routes_to_email(monkeypatch, test_engine, mock_bot):
    _patch_engine(monkeypatch, test_engine)
    _seed(test_engine)
    state = await upd_pick(_cb_update("upd:email"), _ctx(mock_bot, user_data={"upd_client_id": CLIENT_ID}))
    assert state == UPD_EMAIL


@pytest.mark.asyncio
async def test_pick_done_no_changes_ends(monkeypatch, test_engine, mock_bot):
    _patch_engine(monkeypatch, test_engine)
    _seed(test_engine)
    ctx = _ctx(mock_bot, user_data={"upd_client_id": CLIENT_ID, "upd_dirty": False})
    state = await upd_pick(_cb_update("upd:done"), ctx)
    assert state == ConversationHandler.END
    # Helper cleans up user_data.
    assert "upd_client_id" not in ctx.user_data


# ── per-field commit ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_goal_updates_db_and_marks_dirty(monkeypatch, test_engine, mock_bot):
    _patch_engine(monkeypatch, test_engine)
    _seed(test_engine)
    ctx = _ctx(mock_bot, user_data={"upd_client_id": CLIENT_ID})
    state = await upd_set_goal(_cb_update("upd_goal:powerlifter"), ctx)
    assert state == UPD_PICK
    assert ctx.user_data["upd_dirty"] is True
    with Session(test_engine) as s:
        assert s.get(ClientProfile, CLIENT_ID).avatar == "powerlifter"


@pytest.mark.asyncio
async def test_set_days_updates_db(monkeypatch, test_engine, mock_bot):
    _patch_engine(monkeypatch, test_engine)
    _seed(test_engine)
    ctx = _ctx(mock_bot, user_data={"upd_client_id": CLIENT_ID})
    state = await upd_set_days(_cb_update("upd_days:5"), ctx)
    assert state == UPD_PICK
    with Session(test_engine) as s:
        assert s.get(ClientProfile, CLIENT_ID).training_days == 5


@pytest.mark.asyncio
async def test_set_experience_updates_db(monkeypatch, test_engine, mock_bot):
    _patch_engine(monkeypatch, test_engine)
    _seed(test_engine)
    ctx = _ctx(mock_bot, user_data={"upd_client_id": CLIENT_ID})
    await upd_set_exp(_cb_update("upd_exp:advanced"), ctx)
    with Session(test_engine) as s:
        assert s.get(ClientProfile, CLIENT_ID).experience_level == "advanced"


@pytest.mark.asyncio
async def test_set_email_validates_and_updates(monkeypatch, test_engine, mock_bot):
    _patch_engine(monkeypatch, test_engine)
    _seed(test_engine)
    ctx = _ctx(mock_bot, user_data={"upd_client_id": CLIENT_ID})

    # Invalid email stays in same state and re-prompts.
    state_bad = await upd_set_email(_text_update("not-an-email"), ctx)
    assert state_bad == UPD_EMAIL

    state_ok = await upd_set_email(_text_update("new@example.com"), ctx)
    assert state_ok == UPD_PICK
    with Session(test_engine) as s:
        assert s.get(ClientProfile, CLIENT_ID).email == "new@example.com"


@pytest.mark.asyncio
async def test_back_button_does_not_save(monkeypatch, test_engine, mock_bot):
    _patch_engine(monkeypatch, test_engine)
    _seed(test_engine)
    ctx = _ctx(mock_bot, user_data={"upd_client_id": CLIENT_ID})
    state = await upd_set_goal(_cb_update("upd_goal:back"), ctx)
    assert state == UPD_PICK
    # Dirty flag not set on back.
    assert ctx.user_data.get("upd_dirty", False) is False
    with Session(test_engine) as s:
        # Avatar unchanged.
        assert s.get(ClientProfile, CLIENT_ID).avatar == "gen_pop"


@pytest.mark.asyncio
async def test_limitations_none_clears_existing(monkeypatch, test_engine, mock_bot):
    _patch_engine(monkeypatch, test_engine)
    _seed(test_engine)
    # Pre-set a limitation so we can verify the clear path.
    with Session(test_engine) as s:
        prof = s.get(ClientProfile, CLIENT_ID)
        prof.limitations = ["knee_pain"]
        s.add(prof)
        s.commit()
    ctx = _ctx(mock_bot, user_data={
        "upd_client_id": CLIENT_ID,
        "selected_limitations": {"none"},
    })
    state = await upd_lim_confirm(_cb_update("lim_confirm"), ctx)
    assert state == UPD_PICK
    with Session(test_engine) as s:
        assert s.get(ClientProfile, CLIENT_ID).limitations == []
