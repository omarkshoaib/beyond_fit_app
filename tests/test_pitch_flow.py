# tests/test_pitch_flow.py
"""SP-D pre-payment pitch."""
import pytest
from unittest.mock import AsyncMock
from tests.conftest import make_callback_update, make_context


@pytest.fixture
def mock_bot():
    return AsyncMock()


def _sent_text(mock_bot):
    # the menu handlers call query.edit_message_text -> mock_bot.edit_message_text
    calls = mock_bot.edit_message_text.call_args_list
    return " ".join(str(c.args) + str(c.kwargs) for c in calls)


@pytest.mark.asyncio
async def test_subscribe_shows_pitch_not_prices(mock_bot):
    from app import bot
    ctx = make_context(mock_bot)
    nxt = await bot.handle_menu_subscribe(make_callback_update(mock_bot, data="menu_subscribe"), ctx)
    text = _sent_text(mock_bot)
    assert "Why Beyond Fit" in text          # the pitch, not the price picker
    assert "EGP" not in text                  # prices are NOT shown yet
    assert nxt == bot.MENU_ROOT


@pytest.mark.asyncio
async def test_see_plans_shows_price_picker(mock_bot):
    from app import bot
    ctx = make_context(mock_bot)
    nxt = await bot.handle_menu_see_plans(make_callback_update(mock_bot, data="menu_see_plans"), ctx)
    text = _sent_text(mock_bot)
    assert "EGP" in text and "Month" in text  # the 1m/3m price picker
    assert nxt == bot.SUBSCRIBE_PICK_PLAN


@pytest.mark.asyncio
async def test_why_button_shows_pitch(mock_bot):
    from app import bot
    ctx = make_context(mock_bot)
    nxt = await bot.handle_menu_why(make_callback_update(mock_bot, data="menu_why"), ctx)
    assert "Why Beyond Fit" in _sent_text(mock_bot)
    assert nxt == bot.MENU_ROOT


def test_pitch_keyboard_has_see_plans_and_back():
    from app import bot
    kb = bot._pitch_keyboard()
    datas = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "menu_see_plans" in datas and "menu_back" in datas
