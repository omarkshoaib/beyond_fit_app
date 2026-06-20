"""SP-A C1: equipment survey at intake."""
import pytest
from unittest.mock import AsyncMock
from sqlmodel import Session
from app.models import ClientProfile  # ensures SQLModel.metadata is populated before test_engine fixture
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


@pytest.mark.asyncio
async def test_pullup_no_sets_bodyweight_and_sends_new_message(mock_bot):
    # the "No" branch edits the message with a warning, then sends the experience
    # prompt as a NEW message (cannot edit the same callback twice).
    from app import bot
    ctx = make_context(mock_bot, {"avatar": "gen_pop", "days": 4})
    upd = make_callback_update(mock_bot, data="equip_pullup:no")
    nxt = await bot.handle_equipment_pullup(upd, ctx)
    assert ctx.user_data["available_equipment"] == ["bodyweight"]
    assert nxt == bot.ASK_EXPERIENCE
    # conftest attaches a real CallbackQuery to mock_bot: edit_message_text routes to
    # mock_bot.edit_message_text (the warning), message.reply_text to mock_bot.send_message
    # (the experience prompt as a NEW message — proving no double-edit).
    mock_bot.edit_message_text.assert_called_once()
    mock_bot.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_upd_equipment_saves_and_returns_to_pick(mock_bot):
    from app import bot
    # bot.engine is replaced by the autouse patch_engine fixture with the per-test SQLite DB.
    cid = "cl_upd_equip"
    with Session(bot.engine) as s:
        s.merge(ClientProfile(client_id=cid, avatar="gen_pop", training_days=3,
                              experience_level="beginner", limitations=[],
                              available_equipment=["full_gym"]))
        s.commit()
    ctx = make_context(mock_bot, {"upd_client_id": cid, "equip_selected": {"dumbbells"}})
    nxt = await bot.upd_equipment_confirm(make_callback_update(mock_bot, data="equip_confirm"), ctx)
    with Session(bot.engine) as s:
        p = s.get(ClientProfile, cid)
    assert set(p.available_equipment) == {"dumbbells", "bodyweight"}
    assert nxt == bot.UPD_PICK


@pytest.mark.asyncio
async def test_back_from_equipment_returns_to_days(mock_bot):
    from app import bot
    ctx = make_context(mock_bot, {"avatar": "gen_pop", "days": 4})
    nxt = await bot.handle_intake_back(make_callback_update(mock_bot, data="intake_back:ASK_EQUIPMENT"), ctx)
    assert nxt == bot.ASK_DAYS


@pytest.mark.asyncio
async def test_back_from_baseline_computes_predecessor(mock_bot):
    from app import bot
    ctx = make_context(mock_bot, {"avatar": "gen_pop", "days": 4,
                                  "experience_level": "beginner", "_ask_limitations_other": False})
    nxt = await bot.handle_intake_back(make_callback_update(mock_bot, data="intake_back:ASK_BASE_SQUAT"), ctx)
    assert nxt == bot.ASK_LIMITATIONS


@pytest.mark.asyncio
async def test_limitations_confirm_idempotent_clears_other_flag(mock_bot):
    from app import bot
    ctx = make_context(mock_bot, {"selected_limitations": {"knee_pain"},
                                  "_ask_limitations_other": True})
    await bot.handle_limitations_confirm(make_callback_update(mock_bot, data="lim_confirm"), ctx)
    assert ctx.user_data["_ask_limitations_other"] is False


@pytest.mark.asyncio
async def test_back_from_experience_returns_to_equipment(mock_bot):
    """Discriminating test: int-valued state (ASK_EXPERIENCE=2) must round-trip through callback_data."""
    from app import bot
    ctx = make_context(mock_bot, {"avatar": "gen_pop", "days": 4})
    nxt = await bot.handle_intake_back(
        make_callback_update(mock_bot, data=f"intake_back:{bot.ASK_EXPERIENCE}"), ctx)
    assert nxt == bot.ASK_EQUIPMENT


@pytest.mark.asyncio
async def test_other_describe_step_is_not_a_dead_end(mock_bot):
    """A client who picked 'Other' must be able to Back out of the describe prompt to the
    limitations checklist (was a dead-end trap — the describe prompt had no Back button)."""
    from app import bot
    ctx = make_context(mock_bot, {"avatar": "gen_pop", "days": 4,
                                  "experience_level": "beginner", "_ask_limitations_other": True})
    # Back from the squat baseline lands on the describe step (since 'other' was chosen)...
    nxt = await bot.handle_intake_back(
        make_callback_update(mock_bot, data="intake_back:ASK_BASE_SQUAT"), ctx)
    assert nxt == bot.ASK_LIMITATIONS_OTHER
    # ...and Back from the describe step reaches the checklist (no longer trapped).
    nxt = await bot.handle_intake_back(
        make_callback_update(mock_bot, data="intake_back:ASK_LIMITATIONS_OTHER"), ctx)
    assert nxt == bot.ASK_LIMITATIONS
