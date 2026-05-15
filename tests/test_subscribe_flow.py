"""Phase B: pre-payment funnel + payment review + login-by-code + FAQ."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlmodel import Session, select

from telegram import Chat, Message, PhotoSize, Update, User

from app.bot import (
    MENU_ROOT,
    SUBSCRIBE_PICK_PLAN,
    SUBSCRIBE_AWAIT_SCREENSHOT,
    LOGIN_AWAIT_CODE,
    FAQ_LOOP,
    PAY_REJECT_REASON,
    handle_login_code,
    handle_menu_subscribe,
    handle_subscribe_pick_plan,
    handle_payment_screenshot,
    handle_payment_verify,
    handle_payment_reject_start,
    handle_payment_reject_reason,
    handle_faq_message,
    handle_setup_begin,
    start_conversation,
)
from app.models import (
    AccessCode,
    ChatBinding,
    ClientProfile,
    Payment,
    Subscription,
)
from tests.conftest import make_callback_update, make_context, make_text_update


SUPER_ADMIN_ID = 4242
CLIENT_CHAT_ID = 555


# ── helpers ──────────────────────────────────────────────────────────


def _patch_roles(monkeypatch, engine, super_admin_id=SUPER_ADMIN_ID):
    """Point app.auth.roles + app.bot at the test engine + super-admin id."""
    import app.auth.roles as roles_mod
    monkeypatch.setattr(roles_mod, "engine", engine)
    fake = type("S", (), {
        "super_admin_telegram_user_id": super_admin_id,
        "admin_chat_id": None,
        "subscription_price_1m_egp": 1500,
        "subscription_price_3m_egp": 3500,
        "instapay_payee_handle": "@beyond.fit",
        "instapay_display_name": "Beyond Fit",
        "faq_rate_limit_per_hour": 5,
    })()
    monkeypatch.setattr(roles_mod, "get_settings", lambda: fake)
    # bot.py reads settings via its own import — patch there too.
    import app.bot as bot_mod
    monkeypatch.setattr(bot_mod, "get_settings", lambda: fake)
    roles_mod.invalidate_coach_cache()


def _make_admin_callback(mock_bot, *, user_id: int, data: str, caption: str = "Pending"):
    """Build a SimpleNamespace mimicking the Update fields the handlers read.

    PTB classes are frozen, so we don't try to wrap real Update/CallbackQuery here —
    handlers only touch a small subset of attributes.
    """
    from types import SimpleNamespace
    msg = SimpleNamespace(caption=caption)
    cq = SimpleNamespace(
        data=data,
        message=msg,
        answer=AsyncMock(),
        edit_message_caption=AsyncMock(),
    )
    return SimpleNamespace(
        callback_query=cq,
        effective_user=SimpleNamespace(id=user_id),
        effective_chat=SimpleNamespace(id=user_id),
        effective_message=SimpleNamespace(reply_text=AsyncMock()),
    )


def _make_photo_update(mock_bot, *, user_id: int, file_id: str = "AgAC1234") -> Update:
    """Construct a photo-message Update with a PhotoSize attached."""
    user = User(id=user_id, first_name="TestUser", is_bot=False)
    chat = Chat(id=user_id, type="private")
    photo = PhotoSize(file_id=file_id, file_unique_id=file_id + "_u", width=600, height=600)
    msg = Message(
        message_id=1,
        date=datetime.now(timezone.utc),
        chat=chat,
        from_user=user,
        photo=(photo,),
    )
    msg.set_bot(mock_bot)
    return Update(update_id=1, message=msg)


def _make_app_context(mock_bot):
    """Build a context whose .application.bot_data persists across calls."""
    ctx = make_context(mock_bot)
    ctx.application = MagicMock()
    ctx.application.bot_data = {}
    return ctx


# ── start_conversation dispatch ──────────────────────────────────────


@pytest.mark.asyncio
async def test_start_unbound_chat_shows_menu(monkeypatch, test_engine, mock_bot):
    _patch_roles(monkeypatch, test_engine)
    update = make_text_update(mock_bot, user_id=999, text="/start")
    state = await start_conversation(update, _make_app_context(mock_bot))
    assert state == MENU_ROOT


@pytest.mark.asyncio
async def test_start_bound_chat_skips_menu(monkeypatch, test_engine, mock_bot):
    _patch_roles(monkeypatch, test_engine)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with Session(test_engine) as s:
        s.add(ClientProfile(client_id="cl_x", avatar="gen_pop", training_days=3))
        s.add(ChatBinding(chat_id=999, client_id="cl_x", is_primary=True))
        # Bound + active sub → "welcome back", not funnel.
        s.add(Subscription(
            client_id="cl_x", plan_type="1m",
            started_at=now, ends_at=now + timedelta(days=20),
            status="active", created_at=now,
        ))
        s.commit()
    update = make_text_update(mock_bot, user_id=999, text="/start")
    state = await start_conversation(update, _make_app_context(mock_bot))
    from telegram.ext import ConversationHandler
    assert state == ConversationHandler.END


@pytest.mark.asyncio
async def test_start_bound_chat_with_expired_sub_drops_to_menu(monkeypatch, test_engine, mock_bot):
    """Item 18 (review) — expired subscription should not show 'Welcome back'."""
    _patch_roles(monkeypatch, test_engine)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with Session(test_engine) as s:
        s.add(ClientProfile(client_id="cl_y", avatar="gen_pop", training_days=3))
        s.add(ChatBinding(chat_id=1001, client_id="cl_y", is_primary=True))
        # Expired sub (ends in the past).
        s.add(Subscription(
            client_id="cl_y", plan_type="1m",
            started_at=now - timedelta(days=40), ends_at=now - timedelta(days=10),
            status="active", created_at=now - timedelta(days=40),
        ))
        s.commit()
    update = make_text_update(mock_bot, user_id=1001, text="/start")
    state = await start_conversation(update, _make_app_context(mock_bot))
    assert state == MENU_ROOT


# ── Subscribe path ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_subscribe_pick_plan_advances_to_screenshot(monkeypatch, test_engine, mock_bot):
    _patch_roles(monkeypatch, test_engine)
    update = make_callback_update(mock_bot, user_id=CLIENT_CHAT_ID, data="sub_pick:1m")
    ctx = _make_app_context(mock_bot)
    state = await handle_subscribe_pick_plan(update, ctx)
    assert state == SUBSCRIBE_AWAIT_SCREENSHOT
    assert ctx.user_data["subscribe_plan_type"] == "1m"
    assert ctx.user_data["subscribe_amount"] == 1500


@pytest.mark.asyncio
async def test_subscribe_pick_3m_amount(monkeypatch, test_engine, mock_bot):
    _patch_roles(monkeypatch, test_engine)
    update = make_callback_update(mock_bot, user_id=CLIENT_CHAT_ID, data="sub_pick:3m")
    ctx = _make_app_context(mock_bot)
    await handle_subscribe_pick_plan(update, ctx)
    assert ctx.user_data["subscribe_amount"] == 3500


@pytest.mark.asyncio
async def test_payment_screenshot_creates_payment_and_notifies_admin(monkeypatch, test_engine, mock_bot):
    _patch_roles(monkeypatch, test_engine)
    ctx = _make_app_context(mock_bot)
    ctx.user_data["subscribe_plan_type"] = "1m"
    ctx.user_data["subscribe_amount"] = 1500

    update = _make_photo_update(mock_bot, user_id=CLIENT_CHAT_ID, file_id="AgAC1234")
    await handle_payment_screenshot(update, ctx)

    with Session(test_engine) as s:
        payment = s.exec(select(Payment)).first()
    assert payment is not None
    assert payment.status == "pending"
    assert payment.amount_egp == 1500
    assert payment.client_id.startswith("cl_")
    assert payment.screenshot_file_id == "AgAC1234"

    # Admin DM with photo.
    mock_bot.send_photo.assert_awaited()
    args, kwargs = mock_bot.send_photo.call_args
    assert kwargs["chat_id"] == SUPER_ADMIN_ID
    # bot_data index populated.
    assert payment.id in ctx.application.bot_data["pending_payments"]


# ── Verify path ──────────────────────────────────────────────────────


def _seed_pending_payment(test_engine, ctx, *, plan_type="1m", amount=1500, chat_id=CLIENT_CHAT_ID):
    with Session(test_engine) as s:
        p = Payment(
            client_id="cl_alpha",
            plan_type=plan_type,
            amount_egp=amount,
            screenshot_file_id="X",
            status="pending",
            submitted_at=datetime.now(timezone.utc),
        )
        s.add(p)
        s.commit()
        s.refresh(p)
        payment_id = p.id
    ctx.application.bot_data["pending_payments"] = {
        payment_id: {
            "chat_id": chat_id,
            "sender_name": "Alice",
            "client_id": "cl_alpha",
            "plan_type": plan_type,
            "amount": amount,
        }
    }
    return payment_id


@pytest.mark.asyncio
async def test_pay_verify_creates_subscription_accesscode_binding(monkeypatch, test_engine, mock_bot):
    _patch_roles(monkeypatch, test_engine)
    ctx = _make_app_context(mock_bot)
    payment_id = _seed_pending_payment(test_engine, ctx, plan_type="1m", amount=1500)

    update = _make_admin_callback(mock_bot, user_id=SUPER_ADMIN_ID,
                                   data=f"pay_verify:{payment_id}", caption="Pending payment")
    await handle_payment_verify(update, ctx)

    with Session(test_engine) as s:
        payment = s.get(Payment, payment_id)
        sub = s.exec(select(Subscription).where(Subscription.client_id == "cl_alpha")).first()
        code = s.exec(select(AccessCode).where(AccessCode.client_id == "cl_alpha")).first()
        binding = s.exec(select(ChatBinding).where(ChatBinding.client_id == "cl_alpha")).first()
        profile = s.get(ClientProfile, "cl_alpha")

    assert payment.status == "verified"
    assert sub is not None
    assert sub.status == "active"
    # SQLite returns naive datetimes; compare naive-to-naive.
    assert sub.ends_at.replace(tzinfo=None) > datetime.utcnow() + timedelta(days=29)
    assert code is not None
    assert code.code.startswith("BF-")
    assert binding is not None
    assert binding.chat_id == CLIENT_CHAT_ID
    assert binding.is_primary is True
    assert profile is not None

    # Client got DM with the code.
    sent_messages = [c for c in mock_bot.send_message.await_args_list]
    assert any(code.code in (c.kwargs.get("text", "")) for c in sent_messages), \
        "client should receive DM containing the access code"


@pytest.mark.asyncio
async def test_pay_verify_rejects_non_super_admin(monkeypatch, test_engine, mock_bot):
    _patch_roles(monkeypatch, test_engine)
    ctx = _make_app_context(mock_bot)
    payment_id = _seed_pending_payment(test_engine, ctx)

    # Caller is NOT the super admin.
    update = _make_admin_callback(mock_bot, user_id=12345,
                                   data=f"pay_verify:{payment_id}", caption="Pending payment")
    await handle_payment_verify(update, ctx)

    with Session(test_engine) as s:
        payment = s.get(Payment, payment_id)
    assert payment.status == "pending"


@pytest.mark.asyncio
async def test_pay_verify_idempotent_on_replay(monkeypatch, test_engine, mock_bot):
    _patch_roles(monkeypatch, test_engine)
    ctx = _make_app_context(mock_bot)
    payment_id = _seed_pending_payment(test_engine, ctx)

    update = _make_admin_callback(mock_bot, user_id=SUPER_ADMIN_ID,
                                   data=f"pay_verify:{payment_id}", caption="Pending")
    await handle_payment_verify(update, ctx)
    # Second call.
    update2 = _make_admin_callback(mock_bot, user_id=SUPER_ADMIN_ID,
                                    data=f"pay_verify:{payment_id}", caption="Pending")
    await handle_payment_verify(update2, ctx)

    with Session(test_engine) as s:
        subs = s.exec(select(Subscription).where(Subscription.client_id == "cl_alpha")).all()
        codes = s.exec(select(AccessCode).where(AccessCode.client_id == "cl_alpha")).all()
        bindings = s.exec(select(ChatBinding).where(ChatBinding.client_id == "cl_alpha")).all()

    # No duplicates created.
    assert len(subs) == 1
    assert len(codes) == 1
    assert len(bindings) == 1


# ── Reject path ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pay_reject_sets_status_and_dms_client(monkeypatch, test_engine, mock_bot):
    _patch_roles(monkeypatch, test_engine)
    ctx = _make_app_context(mock_bot)
    payment_id = _seed_pending_payment(test_engine, ctx)

    # 1. Admin clicks Reject button.
    update_click = _make_admin_callback(mock_bot, user_id=SUPER_ADMIN_ID,
                                          data=f"pay_reject:{payment_id}", caption="Pending")
    state = await handle_payment_reject_start(update_click, ctx)
    assert state == PAY_REJECT_REASON

    # 2. Admin types reason.
    update_text = make_text_update(mock_bot, user_id=SUPER_ADMIN_ID, text="Wrong amount.")
    await handle_payment_reject_reason(update_text, ctx)

    with Session(test_engine) as s:
        payment = s.get(Payment, payment_id)
    assert payment.status == "rejected"
    assert "Wrong amount" in payment.rejection_reason

    # Client got DM.
    client_dms = [
        c for c in mock_bot.send_message.await_args_list
        if c.kwargs.get("chat_id") == CLIENT_CHAT_ID
    ]
    assert any("couldn't be verified" in c.kwargs.get("text", "") for c in client_dms)


# ── Login-by-code (Phase C bundled) ──────────────────────────────────


@pytest.mark.asyncio
async def test_login_by_code_binds_new_chat(monkeypatch, test_engine, mock_bot):
    _patch_roles(monkeypatch, test_engine)
    with Session(test_engine) as s:
        s.add(ClientProfile(client_id="cl_zeta", avatar="gen_pop", training_days=3))
        s.add(AccessCode(client_id="cl_zeta", code="BF-ABCD-1234-WXYZ"))
        s.commit()

    new_chat_id = 7777
    update = make_text_update(mock_bot, user_id=new_chat_id, text="bf-abcd-1234-wxyz")
    state = await handle_login_code(update, _make_app_context(mock_bot))
    from telegram.ext import ConversationHandler
    assert state == ConversationHandler.END

    with Session(test_engine) as s:
        binding = s.exec(select(ChatBinding).where(ChatBinding.chat_id == new_chat_id)).first()
    assert binding is not None
    assert binding.client_id == "cl_zeta"
    assert binding.is_primary is False


@pytest.mark.asyncio
async def test_login_by_code_rejects_invalid(monkeypatch, test_engine, mock_bot):
    _patch_roles(monkeypatch, test_engine)
    update = make_text_update(mock_bot, user_id=8888, text="BF-NOPE-NOPE-NOPE")
    state = await handle_login_code(update, _make_app_context(mock_bot))
    assert state == LOGIN_AWAIT_CODE  # stays in state


@pytest.mark.asyncio
async def test_login_by_code_blocks_chat_already_bound_elsewhere(monkeypatch, test_engine, mock_bot):
    _patch_roles(monkeypatch, test_engine)
    with Session(test_engine) as s:
        s.add(ClientProfile(client_id="cl_a", avatar="gen_pop", training_days=3))
        s.add(ClientProfile(client_id="cl_b", avatar="gen_pop", training_days=3))
        s.add(AccessCode(client_id="cl_b", code="BF-XXXX-YYYY-ZZZZ"))
        s.add(ChatBinding(chat_id=9001, client_id="cl_a", is_primary=True))
        s.commit()

    update = make_text_update(mock_bot, user_id=9001, text="BF-XXXX-YYYY-ZZZZ")
    await handle_login_code(update, _make_app_context(mock_bot))

    with Session(test_engine) as s:
        binding = s.exec(select(ChatBinding).where(ChatBinding.chat_id == 9001)).first()
    # Should NOT have been rebound.
    assert binding.client_id == "cl_a"


# ── FAQ rate limit ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_faq_rate_limit(monkeypatch, test_engine, mock_bot):
    _patch_roles(monkeypatch, test_engine)
    # Reset module-level counter.
    import app.bot as bot_mod
    bot_mod._faq_recent_calls.clear()

    ctx = _make_app_context(mock_bot)

    # Mock LLM so we don't hit the network.
    fake_llm = MagicMock()
    fake_llm._llm.complete.return_value = "Service answer."
    monkeypatch.setattr(bot_mod, "FlashCommunicationService", lambda *_, **__: fake_llm)
    monkeypatch.setattr(bot_mod, "_make_llm_client", lambda: MagicMock())

    chat_id = 4321
    for i in range(5):
        upd = make_text_update(mock_bot, user_id=chat_id, text=f"q{i}")
        await handle_faq_message(upd, ctx)

    # 6th call must be blocked.
    upd6 = make_text_update(mock_bot, user_id=chat_id, text="q6")
    await handle_faq_message(upd6, ctx)

    # LLM was called 5 times, not 6.
    assert fake_llm._llm.complete.call_count == 5
