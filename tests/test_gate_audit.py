"""Phase G — gating policy audit.

Locks the decorator-based subscription gate by asserting every service entry
point is wrapped. Adding a new service command? Add it to one of these lists.
Forgetting the decorator now fails this test instead of silently shipping an
ungated handler.
"""
from __future__ import annotations

import inspect

import app.bot as bot_mod


_REQUIRES_ACTIVE_SUB = [
    "start_update_profile",
    "cmd_pick_coach",
]

_REQUIRES_ASSIGNED_COACH = [
    "start_checkin",
    "start_diet",
    "client_plan",
    "start_log",
]


def _gate_of(fn) -> str | None:
    """Decorators in app.auth.roles tag wrappers with a `_gate` attribute."""
    return getattr(fn, "_gate", None)


def test_active_sub_decorated():
    for name in _REQUIRES_ACTIVE_SUB:
        fn = getattr(bot_mod, name)
        assert _gate_of(fn) == "requires_active_sub", (
            f"{name} must be wrapped with @auth_roles.requires_active_sub"
        )


def test_assigned_coach_decorated():
    for name in _REQUIRES_ASSIGNED_COACH:
        fn = getattr(bot_mod, name)
        assert _gate_of(fn) == "requires_assigned_coach", (
            f"{name} must be wrapped with @auth_roles.requires_assigned_coach"
        )


def test_no_undecorated_service_command():
    """Sanity: any CommandHandler-bound coro starting with 'start_' or 'cmd_'
    in app.bot module should match one of the lists above OR be explicitly
    public (e.g. start_conversation = /start entry point)."""
    public_unguarded = {"start_conversation"}  # /start is the funnel itself
    candidates = []
    for name, obj in inspect.getmembers(bot_mod):
        if not inspect.iscoroutinefunction(obj):
            continue
        if not (name.startswith("start_") or name.startswith("cmd_")):
            continue
        if name in public_unguarded:
            continue
        if name in _REQUIRES_ACTIVE_SUB or name in _REQUIRES_ASSIGNED_COACH:
            continue
        candidates.append(name)
    assert candidates == [], (
        f"Undecorated service entry candidates found: {candidates}. "
        f"Add to one of the gate lists above or to public_unguarded."
    )
