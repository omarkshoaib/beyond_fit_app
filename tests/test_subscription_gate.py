"""Phase G: subscription + coach gate decorators."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlmodel import Session

from app.auth import roles
from app.models import ChatBinding, ClientProfile, CoachProfile, Subscription


def _patch_engine(monkeypatch, engine):
    monkeypatch.setattr(roles, "engine", engine)


def _seed(engine, *, client_id, chat_id, sub_status="active",
          ends_in_days=10, assigned_coach=None, with_coach_row=True):
    now = datetime.now(timezone.utc)
    with Session(engine) as s:
        s.add(ClientProfile(
            client_id=client_id, avatar="gen_pop", training_days=3,
            assigned_coach_id=assigned_coach,
        ))
        s.add(ChatBinding(chat_id=chat_id, client_id=client_id, is_primary=True))
        if sub_status is not None:
            s.add(Subscription(
                client_id=client_id, plan_type="1m",
                started_at=now - timedelta(days=5),
                ends_at=now + timedelta(days=ends_in_days),
                status=sub_status,
            ))
        if assigned_coach is not None and with_coach_row:
            s.add(CoachProfile(
                telegram_user_id=assigned_coach, name="C", email="c@x", mobile="1",
                specialty="gen_pop", years_experience=1, certifications="—",
                status="approved",
            ))
        s.commit()


def _fake_update(chat_id):
    msg = type("M", (), {"reply_text": AsyncMock()})()
    user = type("UU", (), {"id": chat_id})()
    chat = type("CC", (), {"id": chat_id})()
    return type("U", (), {
        "effective_user": user,
        "effective_chat": chat,
        "effective_message": msg,
    })(), msg.reply_text


# ── requires_active_sub ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_requires_active_sub_blocks_unbound(monkeypatch, test_engine):
    _patch_engine(monkeypatch, test_engine)
    called = []

    @roles.requires_active_sub
    async def handler(update, context):
        called.append(True)

    update, reply = _fake_update(chat_id=999)
    await handler(update, None)
    assert called == []
    reply.assert_awaited_once()
    assert "isn't linked" in reply.call_args.args[0]


@pytest.mark.asyncio
async def test_requires_active_sub_blocks_expired(monkeypatch, test_engine):
    _patch_engine(monkeypatch, test_engine)
    _seed(test_engine, client_id="cl_a", chat_id=111, sub_status="expired", ends_in_days=-5)
    called = []

    @roles.requires_active_sub
    async def handler(update, context):
        called.append(True)

    update, reply = _fake_update(chat_id=111)
    await handler(update, None)
    assert called == []
    assert "expired" in reply.call_args.args[0].lower()


@pytest.mark.asyncio
async def test_requires_active_sub_allows_active(monkeypatch, test_engine):
    _patch_engine(monkeypatch, test_engine)
    _seed(test_engine, client_id="cl_b", chat_id=222, sub_status="active", ends_in_days=15)
    called = []

    @roles.requires_active_sub
    async def handler(update, context):
        called.append(True)

    update, _ = _fake_update(chat_id=222)
    await handler(update, None)
    assert called == [True]


# ── requires_assigned_coach ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_requires_assigned_coach_blocks_no_coach(monkeypatch, test_engine):
    _patch_engine(monkeypatch, test_engine)
    _seed(test_engine, client_id="cl_c", chat_id=333,
          sub_status="active", ends_in_days=15, assigned_coach=None)
    called = []

    @roles.requires_assigned_coach
    async def handler(update, context):
        called.append(True)

    update, reply = _fake_update(chat_id=333)
    await handler(update, None)
    assert called == []
    assert "Pick a coach" in reply.call_args.args[0]


@pytest.mark.asyncio
async def test_requires_assigned_coach_allows_when_coach_set(monkeypatch, test_engine):
    _patch_engine(monkeypatch, test_engine)
    _seed(test_engine, client_id="cl_d", chat_id=444,
          sub_status="active", ends_in_days=15, assigned_coach=555)
    called = []

    @roles.requires_assigned_coach
    async def handler(update, context):
        called.append(True)

    update, _ = _fake_update(chat_id=444)
    await handler(update, None)
    assert called == [True]


@pytest.mark.asyncio
async def test_requires_assigned_coach_blocks_expired_sub(monkeypatch, test_engine):
    _patch_engine(monkeypatch, test_engine)
    _seed(test_engine, client_id="cl_e", chat_id=555,
          sub_status="active", ends_in_days=-3, assigned_coach=666)
    called = []

    @roles.requires_assigned_coach
    async def handler(update, context):
        called.append(True)

    update, reply = _fake_update(chat_id=555)
    await handler(update, None)
    assert called == []
    assert "expired" in reply.call_args.args[0].lower()
