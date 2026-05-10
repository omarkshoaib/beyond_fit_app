"""Role helpers for the bot side.

Three roles:
- super_admin: single user identified by SUPER_ADMIN_TELEGRAM_USER_ID env (falls
  back to legacy ADMIN_CHAT_ID).
- coach: any approved CoachProfile row.
- authenticated client: any chat_id with a ChatBinding row pointing at a
  ClientProfile.

`require_role` is a PTB-handler decorator that gates entry by role.
"""
from __future__ import annotations

import functools
import logging
import secrets
import time
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.database import engine
from app.models import (
    AccessCode,
    ChatBinding,
    ClientProfile,
    CoachProfile,
    Subscription,
)
from app.settings import get_settings

log = logging.getLogger(__name__)


# ── Super-admin ──────────────────────────────────────────────────────


def super_admin_user_id() -> Optional[int]:
    """Resolve the configured super-admin Telegram user id.

    Prefers SUPER_ADMIN_TELEGRAM_USER_ID. Falls back to ADMIN_CHAT_ID for
    backwards compat with the bot-only deploy that already sets it.
    """
    s = get_settings()
    if s.super_admin_telegram_user_id is not None:
        return s.super_admin_telegram_user_id
    return s.admin_chat_id


def is_super_admin(user_id: int) -> bool:
    return super_admin_user_id() == user_id


# ── Coach (with TTL cache) ───────────────────────────────────────────

_COACH_CACHE_TTL_SECONDS = 60.0
_coach_cache: dict[int, tuple[bool, float]] = {}


def is_coach(user_id: int) -> bool:
    """Whether `user_id` is an approved coach. 60s positive+negative cache."""
    now = time.monotonic()
    cached = _coach_cache.get(user_id)
    if cached is not None and (now - cached[1]) < _COACH_CACHE_TTL_SECONDS:
        return cached[0]

    with Session(engine) as session:
        row = session.exec(
            select(CoachProfile).where(
                CoachProfile.telegram_user_id == user_id,
                CoachProfile.status == "approved",
            )
        ).first()
    result = row is not None
    _coach_cache[user_id] = (result, now)
    return result


def invalidate_coach_cache(user_id: Optional[int] = None) -> None:
    """Clear the coach cache. Call after coach approve/reject. None = full flush."""
    if user_id is None:
        _coach_cache.clear()
    else:
        _coach_cache.pop(user_id, None)


# ── Client identity (chat_id → ClientProfile) ────────────────────────


def get_authenticated_client(chat_id: int) -> Optional[ClientProfile]:
    """Return the ClientProfile bound to this chat_id, or None if unbound."""
    with Session(engine) as session:
        binding = session.exec(
            select(ChatBinding).where(ChatBinding.chat_id == chat_id)
        ).first()
        if binding is None:
            return None
        return session.exec(
            select(ClientProfile).where(ClientProfile.client_id == binding.client_id)
        ).first()


def resolve_primary_chat_id(client_id: str) -> Optional[int]:
    """Return the primary chat_id for a client, or any binding if no primary set."""
    with Session(engine) as session:
        primary = session.exec(
            select(ChatBinding).where(
                ChatBinding.client_id == client_id,
                ChatBinding.is_primary == True,  # noqa: E712
            )
        ).first()
        if primary is not None:
            return primary.chat_id
        any_binding = session.exec(
            select(ChatBinding).where(ChatBinding.client_id == client_id)
        ).first()
        return any_binding.chat_id if any_binding else None


def find_client_by_access_code(code: str) -> Optional[str]:
    """Return the client_id matching an access code (exact match), else None."""
    with Session(engine) as session:
        row = session.exec(select(AccessCode).where(AccessCode.code == code)).first()
        return row.client_id if row else None


# ── Subscription gate ────────────────────────────────────────────────


def has_active_subscription(client_id: str) -> bool:
    """True if the client has at least one Subscription with status='active' and
    ends_at in the future."""
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        row = session.exec(
            select(Subscription).where(
                Subscription.client_id == client_id,
                Subscription.status == "active",
                Subscription.ends_at > now,
            )
        ).first()
    return row is not None


# ── Access code generation + bind ────────────────────────────────────

# Crockford base32 alphabet (no I, L, O, U).
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _make_code() -> str:
    """Return a fresh BF-XXXX-XXXX-XXXX style code (12 Crockford chars)."""
    raw = secrets.token_bytes(8)
    body = "".join(_CROCKFORD[b & 0x1F] for b in raw)[:12]
    return f"BF-{body[0:4]}-{body[4:8]}-{body[8:12]}"


def generate_unique_access_code(session: Session, max_attempts: int = 4) -> str:
    """Return a code that's not currently in use. Caller commits."""
    for _ in range(max_attempts):
        candidate = _make_code()
        if session.exec(select(AccessCode).where(AccessCode.code == candidate)).first() is None:
            return candidate
    # ~60 bits entropy; 4 collisions in a row is astronomically unlikely.
    raise RuntimeError("could not generate a unique access code after retries")


def new_client_id() -> str:
    """Generate an opaque client_id. `cl_` prefix breaks any int() assumption."""
    return "cl_" + secrets.token_urlsafe(8).rstrip("=").replace("-", "").replace("_", "")[:12]


def bind_chat(session: Session, chat_id: int, client_id: str, *, is_primary: bool = False) -> str:
    """Idempotent ChatBinding insert.

    Returns:
      - "bound": new binding created.
      - "already": chat_id already maps to the same client_id.
      - "conflict": chat_id already maps to a *different* client_id (rejected).
    """
    existing = session.exec(select(ChatBinding).where(ChatBinding.chat_id == chat_id)).first()
    if existing is not None:
        return "already" if existing.client_id == client_id else "conflict"
    try:
        session.add(ChatBinding(
            chat_id=chat_id,
            client_id=client_id,
            bound_at=datetime.now(timezone.utc),
            is_primary=is_primary,
        ))
        session.commit()
        return "bound"
    except IntegrityError:
        session.rollback()
        # Race: another worker inserted same chat_id.
        existing = session.exec(select(ChatBinding).where(ChatBinding.chat_id == chat_id)).first()
        if existing is not None and existing.client_id == client_id:
            return "already"
        return "conflict"


# ── PTB notify helper ────────────────────────────────────────────────


async def notify_super_admin(bot, text: str, **kwargs) -> None:
    """DM the super-admin. Silently logs and returns if not configured."""
    sa_id = super_admin_user_id()
    if sa_id is None:
        log.warning("notify_super_admin called but no super_admin_user_id configured")
        return
    await bot.send_message(chat_id=sa_id, text=text, **kwargs)


# ── Handler decorator ────────────────────────────────────────────────


HandlerFn = Callable[..., Awaitable[object]]


def require_role(*, super_admin: bool = False, coach: bool = False) -> Callable[[HandlerFn], HandlerFn]:
    """Decorator gating a PTB handler by role.

    `super_admin=True, coach=False` → only the super-admin may enter.
    `super_admin=False, coach=True` → super-admin or any approved coach may enter.
    `super_admin=True, coach=True` → same as coach=True (super-admin is a coach
    superset for permission purposes).

    On rejection: replies "🔒 Not authorized." and returns without invoking the
    handler. Logs `role_check_failed`.
    """
    if not super_admin and not coach:
        raise ValueError("require_role: at least one of super_admin/coach must be True")

    def decorator(fn: HandlerFn) -> HandlerFn:
        @functools.wraps(fn)
        async def wrapper(update, context, *args, **kwargs):
            user = getattr(update, "effective_user", None)
            uid = user.id if user else None
            if uid is None:
                log.warning("role_check_failed reason=no_user fn=%s", fn.__name__)
                return None

            allowed = False
            if super_admin and is_super_admin(uid):
                allowed = True
            elif coach and (is_super_admin(uid) or is_coach(uid)):
                allowed = True

            if not allowed:
                log.info(
                    "role_check_failed user_id=%s fn=%s super_admin=%s coach=%s",
                    uid, fn.__name__, super_admin, coach,
                )
                msg = getattr(update, "effective_message", None)
                if msg is not None:
                    await msg.reply_text("🔒 Not authorized.")
                return None

            return await fn(update, context, *args, **kwargs)

        return wrapper

    return decorator
