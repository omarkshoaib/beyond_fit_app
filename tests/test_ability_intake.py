import pytest
from unittest.mock import AsyncMock
from tests.conftest import make_callback_update, make_context


@pytest.fixture
def mock_bot():
    return AsyncMock()


@pytest.mark.asyncio
async def test_ability_level_maps_and_advances(mock_bot):
    from app import bot
    ctx = make_context(mock_bot, {"experience_level": "beginner", "ability_idx": 0, "exercise_ability": {}})
    # the "I can do the standard version" button is abil:2 -> ability 3
    upd = make_callback_update(mock_bot, data="abil:2")
    nxt = await bot.handle_ability(upd, ctx)
    assert ctx.user_data["exercise_ability"]["squat"] == 3
    assert ctx.user_data["ability_idx"] == 1
    assert nxt == bot.ASK_ABILITY  # still cycling families


@pytest.mark.asyncio
async def test_ability_skip_defaults_from_experience(mock_bot):
    from app import bot
    ctx = make_context(mock_bot, {"experience_level": "advanced", "ability_idx": 0, "exercise_ability": {}})
    nxt = await bot.handle_ability(make_callback_update(mock_bot, data="abil_skip"), ctx)
    # skip-all -> every family defaulted from experience (advanced -> 4) and advance to limitations
    assert all(ctx.user_data["exercise_ability"][f] == 4 for f in bot._ABILITY_FAMILIES)
    assert nxt == bot.ASK_LIMITATIONS


@pytest.mark.asyncio
async def test_ability_last_family_advances_to_limitations(mock_bot):
    from app import bot
    ea = {f: 2 for f in bot._ABILITY_FAMILIES[:-1]}
    ctx = make_context(mock_bot, {"experience_level": "beginner",
                                  "ability_idx": len(bot._ABILITY_FAMILIES) - 1, "exercise_ability": ea})
    nxt = await bot.handle_ability(make_callback_update(mock_bot, data="abil:2"), ctx)
    assert nxt == bot.ASK_LIMITATIONS
    assert len(ctx.user_data["exercise_ability"]) == len(bot._ABILITY_FAMILIES)


@pytest.mark.asyncio
async def test_back_into_ability_after_completion_does_not_crash(mock_bot):
    # after the 6th answer ability_idx == 6; Back into ASK_ABILITY must clamp, not IndexError
    from app import bot
    ctx = make_context(mock_bot, {"experience_level": "beginner", "ability_idx": 6,
                                  "exercise_ability": {f: 2 for f in bot._ABILITY_FAMILIES}})
    upd = make_callback_update(mock_bot, data=f"intake_back:{bot.ASK_LIMITATIONS}")
    nxt = await bot.handle_intake_back(upd, ctx)
    assert nxt == bot.ASK_ABILITY  # re-prompts the last family, no crash
