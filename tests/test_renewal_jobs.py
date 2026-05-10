"""Phase F: daily renewal reminders + expiry jobs."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlmodel import Session, select

from app.bot import send_renewal_reminders, expire_subscriptions
from app.models import (
    AccessCode,
    ChatBinding,
    ClientProfile,
    ReminderLog,
    Subscription,
)


def _patch_engine(monkeypatch, engine):
    import app.auth.roles as roles_mod
    monkeypatch.setattr(roles_mod, "engine", engine)
    fake = type("S", (), {
        "super_admin_telegram_user_id": 1,
        "admin_chat_id": None,
        "subscription_price_1m_egp": 1500,
        "subscription_price_3m_egp": 3500,
        "instapay_payee_handle": "@x",
        "instapay_display_name": "X",
        "faq_rate_limit_per_hour": 5,
    })()
    monkeypatch.setattr(roles_mod, "get_settings", lambda: fake)


def _job_context(mock_bot):
    return SimpleNamespace(bot=mock_bot)


def _seed_active_sub(engine, *, client_id, chat_id, days_out: float, status="active"):
    now = datetime.now(timezone.utc)
    with Session(engine) as s:
        s.add(ClientProfile(client_id=client_id, avatar="gen_pop", training_days=3))
        s.add(ChatBinding(chat_id=chat_id, client_id=client_id, is_primary=True))
        s.add(Subscription(
            client_id=client_id,
            plan_type="1m",
            started_at=now - timedelta(days=30),
            ends_at=now + timedelta(days=days_out),
            status=status,
        ))
        s.commit()
        sub = s.exec(select(Subscription).where(Subscription.client_id == client_id)).first()
        return sub.id


# ── Renewal reminders ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_d7_reminder_fires_for_sub_ending_in_seven_days(monkeypatch, test_engine, mock_bot):
    _patch_engine(monkeypatch, test_engine)
    sub_id = _seed_active_sub(test_engine, client_id="cl_d7", chat_id=701, days_out=7.5)

    await send_renewal_reminders(_job_context(mock_bot))

    dms = [c for c in mock_bot.send_message.await_args_list if c.kwargs.get("chat_id") == 701]
    assert len(dms) == 1
    assert "7" in dms[0].kwargs["text"] or "expires" in dms[0].kwargs["text"]
    with Session(test_engine) as s:
        log = s.exec(select(ReminderLog).where(
            ReminderLog.subscription_id == sub_id, ReminderLog.kind == "d7"
        )).first()
    assert log is not None


@pytest.mark.asyncio
async def test_reminder_idempotent_across_runs(monkeypatch, test_engine, mock_bot):
    _patch_engine(monkeypatch, test_engine)
    _seed_active_sub(test_engine, client_id="cl_idem", chat_id=702, days_out=3.5)

    await send_renewal_reminders(_job_context(mock_bot))
    await send_renewal_reminders(_job_context(mock_bot))

    dms = [c for c in mock_bot.send_message.await_args_list if c.kwargs.get("chat_id") == 702]
    # Second run does not re-DM.
    assert len(dms) == 1


@pytest.mark.asyncio
async def test_reminder_skips_sub_outside_window(monkeypatch, test_engine, mock_bot):
    _patch_engine(monkeypatch, test_engine)
    _seed_active_sub(test_engine, client_id="cl_far", chat_id=703, days_out=20)

    await send_renewal_reminders(_job_context(mock_bot))

    dms = [c for c in mock_bot.send_message.await_args_list if c.kwargs.get("chat_id") == 703]
    assert dms == []


@pytest.mark.asyncio
async def test_reminder_skips_unbound_chat(monkeypatch, test_engine, mock_bot):
    _patch_engine(monkeypatch, test_engine)
    # Subscription exists but no ChatBinding.
    now = datetime.now(timezone.utc)
    with Session(test_engine) as s:
        s.add(ClientProfile(client_id="cl_orphan", avatar="gen_pop", training_days=3))
        s.add(Subscription(
            client_id="cl_orphan", plan_type="1m",
            started_at=now, ends_at=now + timedelta(days=1, hours=1),
            status="active",
        ))
        s.commit()

    await send_renewal_reminders(_job_context(mock_bot))

    # No DM, no ReminderLog row.
    assert mock_bot.send_message.await_count == 0
    with Session(test_engine) as s:
        logs = s.exec(select(ReminderLog)).all()
    assert logs == []


# ── Expiry job ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_expire_flips_status_and_dms_client(monkeypatch, test_engine, mock_bot):
    _patch_engine(monkeypatch, test_engine)
    sub_id = _seed_active_sub(test_engine, client_id="cl_exp", chat_id=801, days_out=-1)

    await expire_subscriptions(_job_context(mock_bot))

    with Session(test_engine) as s:
        sub = s.get(Subscription, sub_id)
    assert sub.status == "expired"
    dms = [c for c in mock_bot.send_message.await_args_list if c.kwargs.get("chat_id") == 801]
    assert any("expired" in c.kwargs["text"].lower() for c in dms)


@pytest.mark.asyncio
async def test_expire_idempotent(monkeypatch, test_engine, mock_bot):
    _patch_engine(monkeypatch, test_engine)
    _seed_active_sub(test_engine, client_id="cl_exp2", chat_id=802, days_out=-2)

    await expire_subscriptions(_job_context(mock_bot))
    await expire_subscriptions(_job_context(mock_bot))

    dms = [c for c in mock_bot.send_message.await_args_list if c.kwargs.get("chat_id") == 802]
    assert len(dms) == 1


@pytest.mark.asyncio
async def test_expire_no_op_for_active_future_sub(monkeypatch, test_engine, mock_bot):
    _patch_engine(monkeypatch, test_engine)
    sub_id = _seed_active_sub(test_engine, client_id="cl_active", chat_id=803, days_out=10)

    await expire_subscriptions(_job_context(mock_bot))

    with Session(test_engine) as s:
        sub = s.get(Subscription, sub_id)
    assert sub.status == "active"
    assert mock_bot.send_message.await_count == 0
