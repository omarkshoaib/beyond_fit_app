"""SP-A C1: equipment survey at intake."""
import pytest
from unittest.mock import AsyncMock
from tests.conftest import make_callback_update, make_context


@pytest.fixture
def mock_bot():
    return AsyncMock()


@pytest.mark.asyncio
async def test_commercial_preset_sets_full_gym_and_advances(mock_bot):
    from app import bot
    ctx = make_context(mock_bot, {"avatar": "gen_pop", "days": 4})
    upd = make_callback_update(mock_bot, data="equip_preset:commercial")
    nxt = await bot.handle_equipment_preset(upd, ctx)
    assert ctx.user_data["available_equipment"] == ["full_gym"]
    assert nxt == bot.ASK_EXPERIENCE


@pytest.mark.asyncio
async def test_bodyweight_preset_asks_pullup(mock_bot):
    from app import bot
    ctx = make_context(mock_bot, {"avatar": "gen_pop", "days": 4})
    upd = make_callback_update(mock_bot, data="equip_preset:bodyweight")
    nxt = await bot.handle_equipment_preset(upd, ctx)
    assert nxt == bot.ASK_EQUIPMENT_PULLUP


@pytest.mark.asyncio
async def test_pullup_yes_adds_bar(mock_bot):
    from app import bot
    ctx = make_context(mock_bot, {"avatar": "gen_pop", "days": 4})
    upd = make_callback_update(mock_bot, data="equip_pullup:yes")
    nxt = await bot.handle_equipment_pullup(upd, ctx)
    assert "pull_up_bar" in ctx.user_data["available_equipment"]
    assert "bodyweight" in ctx.user_data["available_equipment"]
    assert nxt == bot.ASK_EXPERIENCE


@pytest.mark.asyncio
async def test_custom_done_with_nothing_floors_to_bodyweight(mock_bot):
    from app import bot
    ctx = make_context(mock_bot, {"avatar": "gen_pop", "days": 4, "equip_selected": set()})
    upd = make_callback_update(mock_bot, data="equip_confirm")
    nxt = await bot.handle_equipment_confirm(upd, ctx)
    assert ctx.user_data["available_equipment"] == ["bodyweight"]
    assert nxt == bot.ASK_EXPERIENCE


@pytest.mark.asyncio
async def test_custom_toggle_accumulates(mock_bot):
    from app import bot
    ctx = make_context(mock_bot, {"avatar": "gen_pop", "days": 4})
    await bot.handle_equipment_toggle(
        make_callback_update(mock_bot, data="equip_toggle_dumbbells"), ctx)
    await bot.handle_equipment_toggle(
        make_callback_update(mock_bot, data="equip_toggle_bench"), ctx)
    assert ctx.user_data["equip_selected"] == {"dumbbells", "bench"}
