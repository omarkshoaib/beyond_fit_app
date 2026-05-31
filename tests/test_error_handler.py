"""Locks the global PTB error-handler routing policy (app.bot.handle_error).

Two non-actionable error classes must NOT flood the admin:
- NetworkError (incl. TimedOut, wrapped httpx.ReadError): transient polling
  blips PTB auto-retries — log only, never DM.
- Conflict ("terminated by other getUpdates request"): two pollers on one
  token — one concise alert, rate-limited 30 min, never a raw traceback.

Everything else keeps the existing dedup + traceback-DM behavior.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from telegram.error import Conflict, NetworkError, TimedOut, BadRequest

import app.bot as bot_mod


def _make_context(error: Exception):
    """Minimal PTB-context double: just .error and an async .bot.send_message."""
    bot = SimpleNamespace(
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=42)),
        edit_message_text=AsyncMock(),
    )
    return SimpleNamespace(error=error, bot=bot)


@pytest.fixture(autouse=True)
def _reset_error_state():
    """Clear module-level dedup state + force a known admin id for each test."""
    bot_mod._error_last_sent.clear()
    bot_mod._error_message_ids.clear()
    bot_mod._error_counts.clear()
    with patch.object(bot_mod, "_admin_chat_id", return_value=999):
        yield
    bot_mod._error_last_sent.clear()
    bot_mod._error_message_ids.clear()
    bot_mod._error_counts.clear()


async def test_network_error_does_not_dm_admin():
    ctx = _make_context(NetworkError("httpx.ReadError"))
    await bot_mod.handle_error(None, ctx)
    ctx.bot.send_message.assert_not_called()
    ctx.bot.edit_message_text.assert_not_called()


async def test_timed_out_does_not_dm_admin():
    # TimedOut subclasses NetworkError — must be silenced too.
    ctx = _make_context(TimedOut())
    await bot_mod.handle_error(None, ctx)
    ctx.bot.send_message.assert_not_called()


async def test_conflict_sends_one_concise_alert():
    ctx = _make_context(Conflict("terminated by other getUpdates request"))
    await bot_mod.handle_error(None, ctx)
    ctx.bot.send_message.assert_called_once()
    _, kwargs = ctx.bot.send_message.call_args
    assert kwargs["chat_id"] == 999
    text = kwargs["text"]
    assert "Conflict" in text and "one poller" in text.lower()
    # Concise — not a stack trace.
    assert "Traceback" not in text and "```" not in text


async def test_conflict_rate_limited_within_30min():
    ctx = _make_context(Conflict("terminated by other getUpdates request"))
    await bot_mod.handle_error(None, ctx)
    await bot_mod.handle_error(None, ctx)  # immediate second fire
    assert ctx.bot.send_message.call_count == 1


async def test_generic_error_still_dms_traceback():
    ctx = _make_context(BadRequest("something genuinely broke"))
    await bot_mod.handle_error(None, ctx)
    ctx.bot.send_message.assert_called_once()
    _, kwargs = ctx.bot.send_message.call_args
    assert "Bot error" in kwargs["text"]
