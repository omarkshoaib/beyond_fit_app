"""Phase H: coach scope on /review, /review_batch, /override + 3-role /help."""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlmodel import Session

from app.bot import admin_review, admin_review_batch, handle_override, handle_help
from app.models import ClientProfile, CoachProfile, PendingApproval


SUPER_ADMIN_ID = 4242
COACH_ID = 5555
OTHER_COACH_ID = 6666


def _patch_roles(monkeypatch, engine):
    import app.auth.roles as roles_mod
    monkeypatch.setattr(roles_mod, "engine", engine)
    fake = type("S", (), {
        "super_admin_telegram_user_id": SUPER_ADMIN_ID,
        "admin_chat_id": None,
    })()
    monkeypatch.setattr(roles_mod, "get_settings", lambda: fake)
    roles_mod.invalidate_coach_cache()


def _seed(engine):
    """Two coaches; one client per coach; one pending workout per client."""
    with Session(engine) as s:
        s.add(CoachProfile(
            telegram_user_id=COACH_ID, name="Coach A", email="a@x", mobile="1",
            specialty="powerlifting", years_experience=5, certifications="—",
            status="approved",
        ))
        s.add(CoachProfile(
            telegram_user_id=OTHER_COACH_ID, name="Coach B", email="b@x", mobile="2",
            specialty="powerbuilding", years_experience=4, certifications="—",
            status="approved",
        ))
        s.add(ClientProfile(
            client_id="cl_a", avatar="powerlifter", training_days=4,
            assigned_coach_id=COACH_ID, name="Alice",
        ))
        s.add(ClientProfile(
            client_id="cl_b", avatar="gen_pop", training_days=3,
            assigned_coach_id=OTHER_COACH_ID, name="Bob",
        ))
        s.commit()

    workout_json = (
        '{"week_number":1,"days":[{"day_name":"Day1","slots":['
        '{"slot_order":0,"exercise_id":"x","exercise_name":"X","sets":3,"reps":"8","rpe":7,"warmup_sets":[],"coaching_cues":[]}'
        '],"total_fatigue":4}]}'
    )
    with Session(engine) as s:
        s.add(PendingApproval(
            approval_uuid=str(uuid.uuid4()), client_id="cl_a",
            client_chat_id=11, client_name="Alice", client_email="a@x.com",
            workout_json=workout_json, coaching_message="msg",
        ))
        s.add(PendingApproval(
            approval_uuid=str(uuid.uuid4()), client_id="cl_b",
            client_chat_id=22, client_name="Bob", client_email="b@x.com",
            workout_json=workout_json, coaching_message="msg",
        ))
        s.commit()


def _command_update(mock_bot, *, user_id, text="/review", args=None):
    msg = type("M", (), {"reply_text": AsyncMock()})()
    user = type("UU", (), {"id": user_id})()
    chat = type("CC", (), {"id": user_id})()
    update = type("U", (), {
        "effective_user": user, "effective_chat": chat,
        "effective_message": msg, "message": msg,
    })()
    return update, msg.reply_text


def _ctx(mock_bot, args=None):
    ctx = MagicMock()
    ctx.bot = mock_bot
    ctx.args = args or []
    return ctx


# ── /review scoping ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_super_admin_review_sees_all_pending(monkeypatch, test_engine, mock_bot):
    _patch_roles(monkeypatch, test_engine)
    _seed(test_engine)
    update, _ = _command_update(mock_bot, user_id=SUPER_ADMIN_ID)
    # safe_send_markdown takes the bot; intercept it.
    sends = []
    async def fake_send(bot, chat_id, text, reply_markup=None):
        sends.append(text)
    import app.bot as bot_mod
    monkeypatch.setattr(bot_mod, "safe_send_markdown", fake_send)
    await admin_review(update, _ctx(mock_bot))
    assert sends, "super-admin should see something"
    text = sends[0]
    assert "Alice" in text
    assert "Bob" in text


@pytest.mark.asyncio
async def test_coach_review_sees_only_assigned_client(monkeypatch, test_engine, mock_bot):
    _patch_roles(monkeypatch, test_engine)
    _seed(test_engine)
    update, _ = _command_update(mock_bot, user_id=COACH_ID)
    sends = []
    async def fake_send(bot, chat_id, text, reply_markup=None):
        sends.append(text)
    import app.bot as bot_mod
    monkeypatch.setattr(bot_mod, "safe_send_markdown", fake_send)
    await admin_review(update, _ctx(mock_bot))
    assert sends
    text = sends[0]
    assert "Alice" in text
    assert "Bob" not in text


@pytest.mark.asyncio
async def test_random_user_review_returns_silently(monkeypatch, test_engine, mock_bot):
    _patch_roles(monkeypatch, test_engine)
    _seed(test_engine)
    update, reply = _command_update(mock_bot, user_id=99999)
    sends = []
    async def fake_send(bot, chat_id, text, reply_markup=None):
        sends.append(text)
    import app.bot as bot_mod
    monkeypatch.setattr(bot_mod, "safe_send_markdown", fake_send)
    await admin_review(update, _ctx(mock_bot))
    assert sends == []
    reply.assert_not_awaited()


# ── /override scoping ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_coach_override_blocks_other_coach_client(monkeypatch, test_engine, mock_bot):
    _patch_roles(monkeypatch, test_engine)
    _seed(test_engine)
    # Coach A tries to override an exercise for Bob (Coach B's client).
    update, reply = _command_update(mock_bot, user_id=COACH_ID)
    await handle_override(update, _ctx(mock_bot, args=["cl_b", "x", "y"]))
    reply.assert_awaited_once()
    assert "don't have access" in reply.call_args.args[0]


@pytest.mark.asyncio
async def test_coach_override_allows_assigned_client(monkeypatch, test_engine, mock_bot):
    _patch_roles(monkeypatch, test_engine)
    _seed(test_engine)
    update, reply = _command_update(mock_bot, user_id=COACH_ID)
    await handle_override(update, _ctx(mock_bot, args=["cl_a"]))
    # The handler proceeds (lists overrides). reply text is something other than the access denial.
    if reply.await_count >= 1:
        assert "don't have access" not in reply.call_args.args[0]


@pytest.mark.asyncio
async def test_super_admin_override_works_for_any_client(monkeypatch, test_engine, mock_bot):
    _patch_roles(monkeypatch, test_engine)
    _seed(test_engine)
    update, reply = _command_update(mock_bot, user_id=SUPER_ADMIN_ID)
    await handle_override(update, _ctx(mock_bot, args=["cl_b"]))
    if reply.await_count >= 1:
        assert "don't have access" not in reply.call_args.args[0]


# ── /help by role ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_help_for_super_admin_includes_super_section(monkeypatch, test_engine, mock_bot):
    _patch_roles(monkeypatch, test_engine)
    update, reply = _command_update(mock_bot, user_id=SUPER_ADMIN_ID)
    await handle_help(update, _ctx(mock_bot))
    text = reply.call_args.args[0]
    assert "Super-admin commands" in text
    assert "Client commands" in text


@pytest.mark.asyncio
async def test_help_for_coach_includes_coach_section(monkeypatch, test_engine, mock_bot):
    _patch_roles(monkeypatch, test_engine)
    _seed(test_engine)
    update, reply = _command_update(mock_bot, user_id=COACH_ID)
    await handle_help(update, _ctx(mock_bot))
    text = reply.call_args.args[0]
    assert "Coach commands" in text
    assert "Super-admin commands" not in text


@pytest.mark.asyncio
async def test_help_for_client_only(monkeypatch, test_engine, mock_bot):
    _patch_roles(monkeypatch, test_engine)
    update, reply = _command_update(mock_bot, user_id=11111)
    await handle_help(update, _ctx(mock_bot))
    text = reply.call_args.args[0]
    assert "Client commands" in text
    assert "Coach commands" not in text
    assert "Super-admin commands" not in text
