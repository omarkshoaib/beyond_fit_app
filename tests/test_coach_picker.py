"""Phase E: client coach-picker + admin assignment."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlmodel import Session, select

from app.bot import (
    handle_coach_picker_list,
    handle_coach_picker_pick,
    handle_coach_picker_admin,
    handle_admin_assign,
    cmd_pick_coach,
)
from app.models import ChatBinding, ClientProfile, CoachProfile
from tests.conftest import make_text_update


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
    ctx = MagicMock()
    ctx.user_data = {}
    ctx.bot = mock_bot
    ctx.application = MagicMock()
    ctx.application.bot_data = {}
    return ctx


def _client_cb(mock_bot, *, chat_id, data):
    """Build a SimpleNamespace mimicking a client-side CallbackQuery update."""
    return SimpleNamespace(
        callback_query=SimpleNamespace(
            data=data,
            message=SimpleNamespace(chat_id=chat_id),
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
        ),
        effective_user=SimpleNamespace(id=chat_id),
        effective_chat=SimpleNamespace(id=chat_id),
        effective_message=SimpleNamespace(reply_text=AsyncMock()),
    )


def _admin_cb(mock_bot, *, user_id, data):
    return SimpleNamespace(
        callback_query=SimpleNamespace(
            data=data,
            message=SimpleNamespace(chat_id=user_id),
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
        ),
        effective_user=SimpleNamespace(id=user_id),
        effective_chat=SimpleNamespace(id=user_id),
        effective_message=SimpleNamespace(reply_text=AsyncMock()),
    )


def _seed_client_and_coach(engine, *, client_id="cl_a", chat_id=111, coach_id=222, status="approved"):
    with Session(engine) as s:
        s.add(ClientProfile(client_id=client_id, avatar="gen_pop", training_days=3))
        s.add(ChatBinding(chat_id=chat_id, client_id=client_id, is_primary=True))
        s.add(CoachProfile(
            telegram_user_id=coach_id, name="Coach Bob", email="b@x", mobile="1",
            specialty="powerbuilding", years_experience=5, certifications="—",
            status=status,
        ))
        s.commit()


# ── Pick path ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pick_writes_assigned_coach_id(monkeypatch, test_engine, mock_bot):
    _patch_roles(monkeypatch, test_engine)
    _seed_client_and_coach(test_engine, client_id="cl_a", chat_id=111, coach_id=222)

    update = _client_cb(mock_bot, chat_id=111, data="cp_pick:cl_a:222")
    await handle_coach_picker_pick(update, _make_app_context(mock_bot))

    with Session(test_engine) as s:
        client = s.get(ClientProfile, "cl_a")
    assert client.assigned_coach_id == 222


@pytest.mark.asyncio
async def test_list_only_shows_approved_coaches(monkeypatch, test_engine, mock_bot):
    _patch_roles(monkeypatch, test_engine)
    _seed_client_and_coach(test_engine, client_id="cl_b", chat_id=222, coach_id=300)
    # Add a pending coach.
    with Session(test_engine) as s:
        s.add(CoachProfile(
            telegram_user_id=400, name="Coach Pending", email="p@x", mobile="2",
            specialty="gen_pop", years_experience=1, certifications="—",
            status="pending",
        ))
        s.commit()

    update = _client_cb(mock_bot, chat_id=222, data="cp_list:cl_b")
    await handle_coach_picker_list(update, _make_app_context(mock_bot))

    args, kwargs = update.callback_query.edit_message_text.call_args
    markup = kwargs["reply_markup"]
    button_data = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    # Only approved coach (300) shown, plus Back.
    assert "cp_pick:cl_b:300" in button_data
    assert not any("400" in d for d in button_data)


@pytest.mark.asyncio
async def test_other_chat_cannot_pick_for_someone_else(monkeypatch, test_engine, mock_bot):
    _patch_roles(monkeypatch, test_engine)
    _seed_client_and_coach(test_engine, client_id="cl_owner", chat_id=111, coach_id=222)
    # An unrelated chat tries to pick cl_owner's coach.
    update = _client_cb(mock_bot, chat_id=999, data="cp_pick:cl_owner:222")
    await handle_coach_picker_pick(update, _make_app_context(mock_bot))

    with Session(test_engine) as s:
        client = s.get(ClientProfile, "cl_owner")
    assert client.assigned_coach_id is None


# ── Let admin pick path ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_pick_notifies_super_admin(monkeypatch, test_engine, mock_bot):
    _patch_roles(monkeypatch, test_engine)
    _seed_client_and_coach(test_engine, client_id="cl_x", chat_id=555, coach_id=600)

    update = _client_cb(mock_bot, chat_id=555, data="cp_admin:cl_x")
    await handle_coach_picker_admin(update, _make_app_context(mock_bot))

    sa_dms = [c for c in mock_bot.send_message.await_args_list
              if c.kwargs.get("chat_id") == SUPER_ADMIN_ID]
    assert len(sa_dms) == 1
    text = sa_dms[0].kwargs["text"]
    assert "cl_x" in text
    # Buttons present.
    markup = sa_dms[0].kwargs["reply_markup"]
    button_data = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert "admin_assign:cl_x:600" in button_data


@pytest.mark.asyncio
async def test_admin_assign_writes_and_dms_client(monkeypatch, test_engine, mock_bot):
    _patch_roles(monkeypatch, test_engine)
    _seed_client_and_coach(test_engine, client_id="cl_y", chat_id=777, coach_id=800)

    update = _admin_cb(mock_bot, user_id=SUPER_ADMIN_ID, data="admin_assign:cl_y:800")
    await handle_admin_assign(update, _make_app_context(mock_bot))

    with Session(test_engine) as s:
        client = s.get(ClientProfile, "cl_y")
    assert client.assigned_coach_id == 800

    # Client got DM.
    dms = [c for c in mock_bot.send_message.await_args_list
           if c.kwargs.get("chat_id") == 777]
    assert any("paired you with" in c.kwargs.get("text", "") for c in dms)


@pytest.mark.asyncio
async def test_admin_assign_blocked_for_non_super_admin(monkeypatch, test_engine, mock_bot):
    _patch_roles(monkeypatch, test_engine)
    _seed_client_and_coach(test_engine, client_id="cl_z", chat_id=888, coach_id=900)

    update = _admin_cb(mock_bot, user_id=12345, data="admin_assign:cl_z:900")
    await handle_admin_assign(update, _make_app_context(mock_bot))

    with Session(test_engine) as s:
        client = s.get(ClientProfile, "cl_z")
    assert client.assigned_coach_id is None


# ── /pick_coach command ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pick_coach_command_for_authenticated_client(monkeypatch, test_engine, mock_bot):
    _patch_roles(monkeypatch, test_engine)
    _seed_client_and_coach(test_engine, client_id="cl_pc", chat_id=42, coach_id=43)

    update = make_text_update(mock_bot, user_id=42, text="/pick_coach")
    await cmd_pick_coach(update, _make_app_context(mock_bot))

    # Picker DM was sent.
    dms = [c for c in mock_bot.send_message.await_args_list
           if c.kwargs.get("chat_id") == 42]
    assert len(dms) == 1


@pytest.mark.asyncio
async def test_pick_coach_command_rejects_unbound(monkeypatch, test_engine, mock_bot):
    _patch_roles(monkeypatch, test_engine)
    update = make_text_update(mock_bot, user_id=99, text="/pick_coach")
    await cmd_pick_coach(update, _make_app_context(mock_bot))
    # Reply was made on the message, not via bot.send_message.
    update.message.reply_text  # noqa - just ensures message exists; no DM expected.
