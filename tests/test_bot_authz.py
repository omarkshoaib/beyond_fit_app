"""Security: nutrition-approve/discard + safety-clear must be authorized."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlmodel import Session

from app.bot import (
    handle_nutrition_approve,
    handle_nutrition_discard,
    handle_safety_clear,
)
from app.models import ClientProfile, CoachProfile, NutritionPlan

SUPER_ADMIN_ID = 4242
COACH_ID = 5555
RANDOM_ID = 99999


def _patch_roles(monkeypatch, engine):
    import app.auth.roles as roles_mod
    monkeypatch.setattr(roles_mod, "engine", engine)
    fake = type("S", (), {"super_admin_telegram_user_id": SUPER_ADMIN_ID, "admin_chat_id": None})()
    monkeypatch.setattr(roles_mod, "get_settings", lambda: fake)
    roles_mod.invalidate_coach_cache()


def _seed(engine):
    with Session(engine) as s:
        s.add(CoachProfile(
            telegram_user_id=COACH_ID, name="Coach A", email="a@x", mobile="1",
            specialty="powerlifting", years_experience=5, certifications="-", status="approved",
        ))
        s.add(ClientProfile(client_id="cl_a", avatar="gen_pop", training_days=3,
                            assigned_coach_id=COACH_ID, name="Alice"))
        s.add(NutritionPlan(id=1, client_id="cl_a", status="draft"))
        s.commit()


def _callback_update(user_id: int, data: str):
    query = MagicMock()
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.data = data
    update = type("U", (), {
        "callback_query": query,
        "effective_user": type("UU", (), {"id": user_id})(),
    })()
    return update, query


def _ctx():
    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_document = AsyncMock()
    ctx.bot.send_message = AsyncMock()
    return ctx


@pytest.mark.asyncio
async def test_random_user_cannot_approve_nutrition(monkeypatch, test_engine):
    _patch_roles(monkeypatch, test_engine)
    _seed(test_engine)
    update, query = _callback_update(RANDOM_ID, "nutapprove:1")
    await handle_nutrition_approve(update, _ctx())
    with Session(test_engine) as s:
        assert s.get(NutritionPlan, 1).status == "draft"  # NOT activated
    assert "thoriz" in query.edit_message_text.call_args.args[0].lower() or \
           "authoriz" in query.edit_message_text.call_args.args[0].lower()


@pytest.mark.asyncio
async def test_random_user_cannot_discard_nutrition(monkeypatch, test_engine):
    _patch_roles(monkeypatch, test_engine)
    _seed(test_engine)
    update, query = _callback_update(RANDOM_ID, "nutdiscard:1")
    await handle_nutrition_discard(update, _ctx())
    with Session(test_engine) as s:
        assert s.get(NutritionPlan, 1).status == "draft"  # NOT rejected


@pytest.mark.asyncio
async def test_assigned_coach_can_discard_nutrition(monkeypatch, test_engine):
    _patch_roles(monkeypatch, test_engine)
    _seed(test_engine)
    update, query = _callback_update(COACH_ID, "nutdiscard:1")
    await handle_nutrition_discard(update, _ctx())
    with Session(test_engine) as s:
        assert s.get(NutritionPlan, 1).status == "rejected"


@pytest.mark.asyncio
async def test_random_user_cannot_clear_safety_gate(monkeypatch, test_engine):
    _patch_roles(monkeypatch, test_engine)
    _seed(test_engine)
    update, query = _callback_update(RANDOM_ID, "safety_clear:cl_a:hypertension")
    await handle_safety_clear(update, _ctx())
    with Session(test_engine) as s:
        assert s.get(ClientProfile, "cl_a").safety_override_note is None


@pytest.mark.asyncio
async def test_super_admin_can_clear_safety_gate(monkeypatch, test_engine):
    _patch_roles(monkeypatch, test_engine)
    _seed(test_engine)
    update, query = _callback_update(SUPER_ADMIN_ID, "safety_clear:cl_a:hypertension")
    await handle_safety_clear(update, _ctx())
    with Session(test_engine) as s:
        assert s.get(ClientProfile, "cl_a").safety_override_note is not None


@pytest.mark.asyncio
async def test_coach_cannot_clear_safety_gate(monkeypatch, test_engine):
    """Medical safety override is super-admin only, even for the assigned coach."""
    _patch_roles(monkeypatch, test_engine)
    _seed(test_engine)
    update, query = _callback_update(COACH_ID, "safety_clear:cl_a:hypertension")
    await handle_safety_clear(update, _ctx())
    with Session(test_engine) as s:
        assert s.get(ClientProfile, "cl_a").safety_override_note is None
