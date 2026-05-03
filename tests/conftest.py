"""
Shared fixtures for bot integration tests.
"""
from __future__ import annotations

import os
# Disable rate limiting before app imports anything (must precede FastAPI init)
os.environ.setdefault("DISABLE_RATELIMIT", "true")

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlmodel import SQLModel, create_engine

from telegram import CallbackQuery, Chat, Message, Update, User


# ── Database fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def test_engine(tmp_path):
    """Per-test SQLite database with all tables created."""
    db_path = tmp_path / "test.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture(autouse=True)
def patch_engine(test_engine, monkeypatch):
    """Replace the global engine in app.bot with the test engine."""
    import app.bot as bot_mod
    monkeypatch.setattr(bot_mod, "engine", test_engine)


# ── PTB mock fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def mock_bot():
    """AsyncMock simulating a Telegram Bot."""
    bot = AsyncMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    bot.send_document = AsyncMock(return_value=MagicMock(message_id=2))
    bot.answer_callback_query = AsyncMock()
    return bot


@pytest.fixture(autouse=True)
def reset_rate_limit(monkeypatch):
    """Clear the per-client generation cooldown before every test."""
    from collections import defaultdict
    import app.bot as bot_mod
    monkeypatch.setattr(bot_mod, "_generation_timestamps", defaultdict(float))


# ── PTB object factories ───────────────────────────────────────────────────────

def make_text_update(mock_bot, user_id: int = 123456, text: str = "hello", update_id: int = 1) -> Update:
    """Construct a text-message Update with the mock bot attached."""
    user = User(id=user_id, first_name="TestUser", is_bot=False, username="testuser")
    chat = Chat(id=user_id, type="private")
    msg = Message(
        message_id=update_id,
        date=datetime.now(tz=timezone.utc),
        chat=chat,
        from_user=user,
        text=text,
    )
    msg.set_bot(mock_bot)
    return Update(update_id=update_id, message=msg)


def make_callback_update(mock_bot, user_id: int = 123456, data: str = "", update_id: int = 1) -> Update:
    """Construct a callback-query Update with the mock bot attached."""
    user = User(id=user_id, first_name="TestUser", is_bot=False, username="testuser")
    chat = Chat(id=user_id, type="private")
    msg = Message(
        message_id=1,
        date=datetime.now(tz=timezone.utc),
        chat=chat,
        from_user=user,
    )
    msg.set_bot(mock_bot)
    cq = CallbackQuery(
        id="cq_test",
        from_user=user,
        chat_instance="test_instance",
        data=data,
        message=msg,
    )
    cq.set_bot(mock_bot)
    return Update(update_id=update_id, callback_query=cq)


def make_context(mock_bot, user_data: dict | None = None) -> MagicMock:
    """Construct a ContextTypes.DEFAULT_TYPE-compatible mock."""
    ctx = MagicMock()
    ctx.user_data = user_data if user_data is not None else {}
    ctx.bot = mock_bot
    return ctx
