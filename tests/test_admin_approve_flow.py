"""Verifies the admin-approve path delivers the PDF via Telegram and never calls EmailService."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models import (
    ClientProfile,
    PendingApproval,
    WorkoutDay,
    WorkoutHistory,
    WorkoutSlot,
    WorkoutWeek,
)


@pytest.mark.asyncio
async def test_approve_sends_pdf_and_does_not_email(monkeypatch):
    from app import bot as bot_module

    week = WorkoutWeek(
        week_number=1,
        days=[
            WorkoutDay(
                day_name="Full Body A",
                slots=[
                    WorkoutSlot(
                        slot_order=1, slot_type="main_compound",
                        exercise_id="back_squat", exercise_name="Back Squat",
                        sets=3, reps="5", rpe=7,
                    )
                ],
                total_fatigue=4,
            )
        ],
    )
    pending = PendingApproval(
        approval_uuid="uuid-1",
        client_id="42",
        client_chat_id=12345,
        client_name="Test Client",
        client_email="ignored@example.com",
        workout_json=week.model_dump_json(),
        coaching_message="# Plan\n\nDo squats.",
    )
    profile = ClientProfile(
        client_id="42", avatar="gen_pop", training_days=3,
        experience_level="beginner", email="ignored@example.com",
        name="Test Client",
    )

    fake_bot = MagicMock()
    fake_bot.send_document = AsyncMock()
    fake_bot.send_message = AsyncMock()

    fake_context = MagicMock()
    fake_context.bot = fake_bot

    fake_query = MagicMock()
    fake_query.edit_message_text = AsyncMock()

    email_called = {"value": False}
    def _email_spy(*args, **kwargs):
        email_called["value"] = True
        return True
    monkeypatch.setattr(
        "app.services.email_service.EmailService.send_plan", _email_spy
    )

    monkeypatch.setattr(bot_module, "_load_pending_and_profile",
                        lambda approval_id: (pending, profile))
    monkeypatch.setattr(bot_module, "_safe_render_pdf",
                        lambda profile, pending: b"%PDF-fake")
    finalise_called = {"value": False}
    def _finalise_spy(pending_arg, _ctx_session=None):
        finalise_called["value"] = True
    monkeypatch.setattr(bot_module, "_atomic_finalise_history", _finalise_spy)

    await bot_module._do_approve_confirmed(fake_query, "uuid-1", fake_context)

    fake_bot.send_document.assert_awaited_once()
    assert fake_bot.send_document.await_args.kwargs["chat_id"] == 12345
    fake_bot.send_message.assert_awaited()  # inline summary
    assert finalise_called["value"] is True
    assert email_called["value"] is False, "email path must not be invoked in bot-only build"
