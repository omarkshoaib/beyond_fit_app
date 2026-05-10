"""Unit tests for app.auth.roles helpers."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlmodel import Session

from app.models import (
    AccessCode,
    ChatBinding,
    ClientProfile,
    CoachProfile,
    Subscription,
)


# ── helpers ──────────────────────────────────────────────────────────


def _seed_client(engine, client_id="cl_alpha", chat_id=111):
    with Session(engine) as s:
        s.add(ClientProfile(client_id=client_id, avatar="gen_pop", training_days=3))
        s.add(ChatBinding(chat_id=chat_id, client_id=client_id, is_primary=True))
        s.commit()


def _seed_coach(engine, telegram_user_id=999, status="approved"):
    with Session(engine) as s:
        s.add(CoachProfile(
            telegram_user_id=telegram_user_id,
            name="Coach C",
            email="c@x",
            mobile="1",
            specialty="powerbuilding",
            years_experience=5,
            certifications="X",
            status=status,
        ))
        s.commit()


def _patch_engine(monkeypatch, engine):
    """Point app.auth.roles at the test engine."""
    import app.auth.roles as roles_mod
    monkeypatch.setattr(roles_mod, "engine", engine)


# ── super-admin ──────────────────────────────────────────────────────


def test_is_super_admin_uses_settings(monkeypatch):
    from app.auth import roles
    fake = type("S", (), {"super_admin_telegram_user_id": 42, "admin_chat_id": None})()
    monkeypatch.setattr(roles, "get_settings", lambda: fake)
    assert roles.is_super_admin(42) is True
    assert roles.is_super_admin(43) is False


def test_super_admin_falls_back_to_admin_chat_id(monkeypatch):
    from app.auth import roles
    fake = type("S", (), {"super_admin_telegram_user_id": None, "admin_chat_id": 7})()
    monkeypatch.setattr(roles, "get_settings", lambda: fake)
    assert roles.super_admin_user_id() == 7
    assert roles.is_super_admin(7) is True


# ── coach (with cache) ──────────────────────────────────────────────


def test_is_coach_true_for_approved(monkeypatch, test_engine):
    _patch_engine(monkeypatch, test_engine)
    _seed_coach(test_engine, telegram_user_id=999, status="approved")
    from app.auth import roles
    roles.invalidate_coach_cache()
    assert roles.is_coach(999) is True


def test_is_coach_false_for_pending(monkeypatch, test_engine):
    _patch_engine(monkeypatch, test_engine)
    _seed_coach(test_engine, telegram_user_id=888, status="pending")
    from app.auth import roles
    roles.invalidate_coach_cache()
    assert roles.is_coach(888) is False


def test_is_coach_cache_invalidates(monkeypatch, test_engine):
    _patch_engine(monkeypatch, test_engine)
    _seed_coach(test_engine, telegram_user_id=777, status="pending")
    from app.auth import roles
    roles.invalidate_coach_cache()
    assert roles.is_coach(777) is False  # cached as False
    # Promote the coach.
    with Session(test_engine) as s:
        c = s.get(CoachProfile, 777)
        c.status = "approved"
        s.add(c)
        s.commit()
    # Without invalidation we still see stale False.
    assert roles.is_coach(777) is False
    roles.invalidate_coach_cache(777)
    assert roles.is_coach(777) is True


# ── client identity ──────────────────────────────────────────────────


def test_get_authenticated_client(monkeypatch, test_engine):
    _patch_engine(monkeypatch, test_engine)
    _seed_client(test_engine, client_id="cl_a", chat_id=111)
    from app.auth import roles
    cp = roles.get_authenticated_client(111)
    assert cp is not None
    assert cp.client_id == "cl_a"
    assert roles.get_authenticated_client(222) is None


def test_resolve_primary_chat_id(monkeypatch, test_engine):
    _patch_engine(monkeypatch, test_engine)
    _seed_client(test_engine, client_id="cl_b", chat_id=500)
    # Add a non-primary second device.
    with Session(test_engine) as s:
        s.add(ChatBinding(chat_id=600, client_id="cl_b", is_primary=False))
        s.commit()
    from app.auth import roles
    assert roles.resolve_primary_chat_id("cl_b") == 500
    assert roles.resolve_primary_chat_id("nonexistent") is None


def test_find_client_by_access_code(monkeypatch, test_engine):
    _patch_engine(monkeypatch, test_engine)
    _seed_client(test_engine, client_id="cl_c", chat_id=10)
    with Session(test_engine) as s:
        s.add(AccessCode(client_id="cl_c", code="BF-XXXX-YYYY-ZZZZ"))
        s.commit()
    from app.auth import roles
    assert roles.find_client_by_access_code("BF-XXXX-YYYY-ZZZZ") == "cl_c"
    assert roles.find_client_by_access_code("nope") is None


# ── subscription ────────────────────────────────────────────────────


def test_has_active_subscription_true(monkeypatch, test_engine):
    _patch_engine(monkeypatch, test_engine)
    _seed_client(test_engine, client_id="cl_d", chat_id=1)
    with Session(test_engine) as s:
        s.add(Subscription(
            client_id="cl_d", plan_type="1m",
            started_at=datetime.now(timezone.utc) - timedelta(days=1),
            ends_at=datetime.now(timezone.utc) + timedelta(days=29),
            status="active",
        ))
        s.commit()
    from app.auth import roles
    assert roles.has_active_subscription("cl_d") is True


def test_has_active_subscription_expired(monkeypatch, test_engine):
    _patch_engine(monkeypatch, test_engine)
    _seed_client(test_engine, client_id="cl_e", chat_id=2)
    with Session(test_engine) as s:
        s.add(Subscription(
            client_id="cl_e", plan_type="1m",
            started_at=datetime.now(timezone.utc) - timedelta(days=40),
            ends_at=datetime.now(timezone.utc) - timedelta(days=10),
            status="active",  # status field stale; gate must still reject
        ))
        s.commit()
    from app.auth import roles
    assert roles.has_active_subscription("cl_e") is False


def test_has_active_subscription_none(monkeypatch, test_engine):
    _patch_engine(monkeypatch, test_engine)
    from app.auth import roles
    assert roles.has_active_subscription("cl_none") is False


# ── require_role decorator ───────────────────────────────────────────


def _fake_update(user_id: int):
    """Build a minimal Update-shaped object with reply_text as AsyncMock."""
    msg = type("M", (), {"reply_text": AsyncMock()})()
    user = type("UU", (), {"id": user_id})()
    update = type("U", (), {"effective_user": user, "effective_message": msg})()
    return update, msg.reply_text


@pytest.mark.asyncio
async def test_require_role_super_admin_blocks_others(monkeypatch):
    from app.auth import roles
    fake = type("S", (), {"super_admin_telegram_user_id": 1, "admin_chat_id": None})()
    monkeypatch.setattr(roles, "get_settings", lambda: fake)

    called = []

    @roles.require_role(super_admin=True)
    async def handler(update, context):
        called.append(True)

    update, reply = _fake_update(user_id=99)
    await handler(update, None)
    assert called == []
    reply.assert_awaited_once_with("🔒 Not authorized.")


@pytest.mark.asyncio
async def test_require_role_super_admin_allows_match(monkeypatch):
    from app.auth import roles
    fake = type("S", (), {"super_admin_telegram_user_id": 7, "admin_chat_id": None})()
    monkeypatch.setattr(roles, "get_settings", lambda: fake)

    called = []

    @roles.require_role(super_admin=True)
    async def handler(update, context):
        called.append(True)

    update, reply = _fake_update(user_id=7)
    await handler(update, None)
    assert called == [True]
    reply.assert_not_awaited()


@pytest.mark.asyncio
async def test_require_role_coach_allows_super_admin(monkeypatch, test_engine):
    _patch_engine(monkeypatch, test_engine)
    from app.auth import roles
    fake = type("S", (), {"super_admin_telegram_user_id": 5, "admin_chat_id": None})()
    monkeypatch.setattr(roles, "get_settings", lambda: fake)
    roles.invalidate_coach_cache()

    called = []

    @roles.require_role(coach=True)
    async def handler(update, context):
        called.append(True)

    update, _ = _fake_update(user_id=5)
    await handler(update, None)
    assert called == [True]
