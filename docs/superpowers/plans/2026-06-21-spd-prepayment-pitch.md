# SP-D — Pre-payment pitch — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a compelling static pitch (what we are / our niche / what's included) before the plan prices in the subscribe funnel, plus a "Why Beyond Fit?" menu button.

**Architecture:** Pure presentation wiring in the existing pre-payment `ConversationHandler` (state `MENU_ROOT` → `SUBSCRIBE_PICK_PLAN`). `handle_menu_subscribe` now shows the pitch (returns `MENU_ROOT`); a new `handle_menu_see_plans` holds the old price-picker body (returns `SUBSCRIBE_PICK_PLAN`); a new `handle_menu_why` + menu button reach the pitch. No model, no migration, no LLM.

**Tech Stack:** python-telegram-bot, pytest. Tests use `tests/conftest.py` (`make_callback_update`, `make_context`) + an `AsyncMock` bot.

**Spec:** `docs/superpowers/specs/2026-06-21-spd-prepayment-pitch-design.md`

---

## File structure

- **Modify** `app/bot.py` — `WHY_BEYOND_FIT` constant; `_pitch_keyboard` + `_show_pitch`; rewire `handle_menu_subscribe`; add `handle_menu_why` + `handle_menu_see_plans`; add the menu button to `_show_root_menu`; register the new callbacks (and `menu_back`) in the `MENU_ROOT` state.
- **Create** `tests/test_pitch_flow.py`.
- **Modify** `CLAUDE.md`, `CHANGELOG.md`.

**Task order:** 1 (pitch + funnel rewire + registration) → 2 (docs).

---

## Task 1: Pitch screen + funnel rewire

**Files:** Modify `app/bot.py`; Test `tests/test_pitch_flow.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pitch_flow.py
"""SP-D pre-payment pitch."""
import pytest
from unittest.mock import AsyncMock
from tests.conftest import make_callback_update, make_context


@pytest.fixture
def mock_bot():
    return AsyncMock()


def _sent_text(mock_bot):
    # the menu handlers call query.edit_message_text -> mock_bot.edit_message_text
    calls = mock_bot.edit_message_text.call_args_list
    return " ".join(str(c.args) + str(c.kwargs) for c in calls)


@pytest.mark.asyncio
async def test_subscribe_shows_pitch_not_prices(mock_bot):
    from app import bot
    ctx = make_context(mock_bot)
    nxt = await bot.handle_menu_subscribe(make_callback_update(mock_bot, data="menu_subscribe"), ctx)
    text = _sent_text(mock_bot)
    assert "Why Beyond Fit" in text          # the pitch, not the price picker
    assert "EGP" not in text                  # prices are NOT shown yet
    assert nxt == bot.MENU_ROOT


@pytest.mark.asyncio
async def test_see_plans_shows_price_picker(mock_bot):
    from app import bot
    ctx = make_context(mock_bot)
    nxt = await bot.handle_menu_see_plans(make_callback_update(mock_bot, data="menu_see_plans"), ctx)
    text = _sent_text(mock_bot)
    assert "EGP" in text and "Month" in text  # the 1m/3m price picker
    assert nxt == bot.SUBSCRIBE_PICK_PLAN


@pytest.mark.asyncio
async def test_why_button_shows_pitch(mock_bot):
    from app import bot
    ctx = make_context(mock_bot)
    nxt = await bot.handle_menu_why(make_callback_update(mock_bot, data="menu_why"), ctx)
    assert "Why Beyond Fit" in _sent_text(mock_bot)
    assert nxt == bot.MENU_ROOT


def test_pitch_keyboard_has_see_plans_and_back():
    from app import bot
    kb = bot._pitch_keyboard()
    datas = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "menu_see_plans" in datas and "menu_back" in datas
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pitch_flow.py -v`
Expected: FAIL — `AttributeError: ... 'handle_menu_why'` / `_pitch_keyboard` / the subscribe
assertion (it currently shows prices).

- [ ] **Step 3: Add the pitch constant + helpers**

In `app/bot.py`, add near the menu handlers (e.g. above `handle_menu_subscribe`):

```python
WHY_BEYOND_FIT = (
    "🏋️ *Why Beyond Fit?*\n\n"
    "Most fitness apps spit out a generic plan and leave you alone. We're different — every "
    "client gets a programme built by a deterministic, science-based engine *and* personally "
    "reviewed and approved by a real human coach before it ever reaches you.\n\n"
    "*What you get:*\n"
    "✅ *A real coach in your corner* — every plan is checked and approved by a human, not "
    "auto-sent by a bot. Message your coach anytime with a question and get a real answer.\n"
    "🔬 *Programming that actually progresses* — proper periodization, and weekly auto-regulation "
    "that adjusts your loads to how *you* actually performed at check-in.\n"
    "🧩 *Built around your reality* — your equipment (even bodyweight-only), your ability (we "
    "regress the lifts you can't do *yet* and build you up), and your injuries (safe "
    "substitutions, never \"push through it\").\n"
    "🥗 *Halal nutrition* — clean, balanced meal plans that fit your goal.\n"
    "📈 *You vs. last week* — you check in, we adapt. Real progression, not the same plan on repeat.\n\n"
    "This is coaching that adapts to you — not a one-size-fits-all PDF.\n\n"
    "Tap *See plans* to get started. 👇"
)


def _pitch_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 See plans →", callback_data="menu_see_plans")],
        [InlineKeyboardButton("⬅️ Back", callback_data="menu_back")],
    ])


async def _show_pitch(query) -> str:
    await query.edit_message_text(WHY_BEYOND_FIT, reply_markup=_pitch_keyboard(), parse_mode="Markdown")
    return MENU_ROOT
```

- [ ] **Step 4: Rewire `handle_menu_subscribe` + add the two new handlers**

Replace the current `handle_menu_subscribe` (it builds the price keyboard + returns
`SUBSCRIBE_PICK_PLAN`) with the pitch, and move its old body into `handle_menu_see_plans`:

```python
async def handle_menu_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    query = update.callback_query
    await query.answer()
    return await _show_pitch(query)


async def handle_menu_why(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    query = update.callback_query
    await query.answer()
    return await _show_pitch(query)


async def handle_menu_see_plans(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    query = update.callback_query
    await query.answer()
    s = get_settings()
    keyboard = [
        [InlineKeyboardButton(f"1 Month — EGP {s.subscription_price_1m_egp}", callback_data="sub_pick:1m")],
        [InlineKeyboardButton(f"3 Months — EGP {s.subscription_price_3m_egp}", callback_data="sub_pick:3m")],
        [InlineKeyboardButton("⬅️ Back", callback_data="menu_back")],
    ]
    await query.edit_message_text("Choose your plan:", reply_markup=InlineKeyboardMarkup(keyboard))
    return SUBSCRIBE_PICK_PLAN
```

(The return type annotation is `str` because `MENU_ROOT`/`SUBSCRIBE_PICK_PLAN` are string
states. The old `handle_menu_subscribe` returned `int` in its annotation but the states are
strings — keep `str` or drop the annotation; do not change behavior elsewhere.)

- [ ] **Step 5: Add the "Why Beyond Fit?" menu button**

In `_show_root_menu`, add a button (put it directly under Subscribe) and a matching bullet:

```python
    keyboard = [
        [InlineKeyboardButton("💳 Subscribe", callback_data="menu_subscribe")],
        [InlineKeyboardButton("✨ Why Beyond Fit?", callback_data="menu_why")],
        [InlineKeyboardButton("❓ Ask a question", callback_data="menu_faq")],
        [InlineKeyboardButton("🔑 I have an account", callback_data="menu_login")],
        [InlineKeyboardButton("🧑‍🏫 I want to coach", callback_data="menu_coach")],
    ]
```

(Optionally add "• *Why Beyond Fit?* — what makes us different" to the text block; cosmetic.)

- [ ] **Step 6: Register the new callbacks in `MENU_ROOT`**

In the `MENU_ROOT` state list (`bot.py:~5875`), add the two new handlers **and** `menu_back`
(the pitch's Back button is tapped while in `MENU_ROOT`, where `menu_back` is not yet
registered):

```python
        MENU_ROOT: [
            CallbackQueryHandler(handle_menu_subscribe, pattern=r"^menu_subscribe$"),
            CallbackQueryHandler(handle_menu_why, pattern=r"^menu_why$"),
            CallbackQueryHandler(handle_menu_see_plans, pattern=r"^menu_see_plans$"),
            CallbackQueryHandler(handle_menu_back, pattern=r"^menu_back$"),
            CallbackQueryHandler(handle_menu_faq, pattern=r"^menu_faq$"),
            CallbackQueryHandler(handle_menu_login, pattern=r"^menu_login$"),
            CallbackQueryHandler(handle_menu_coach, pattern=r"^menu_coach$"),
        ],
```

- [ ] **Step 7: Run tests**

Run: `pytest tests/test_pitch_flow.py -v`
Expected: PASS (4 tests).

- [ ] **Step 8: Run the full suite**

Run: `pytest -q`
Expected: green. (No existing test asserts `handle_menu_subscribe`'s return — verified; the
subscribe tests start from `sub_pick`/`handle_subscribe_pick_plan`, unchanged.)

- [ ] **Step 9: Commit**

```bash
git add app/bot.py tests/test_pitch_flow.py
git commit -m "feat(bot): pre-payment pitch before plan prices + Why Beyond Fit menu button (SP-D)"
```

---

## Task 2: Docs (CLAUDE.md + CHANGELOG)

**Files:** Modify `CLAUDE.md`, `CHANGELOG.md`.

- [ ] **Step 1: Update CLAUDE.md**

Add a bullet under "Key design constraints":

```markdown
- The pre-payment funnel shows a static pitch before prices (SP-D): **💳 Subscribe** →
  `WHY_BEYOND_FIT` pitch (`_show_pitch`, returns `MENU_ROOT`) → **💳 See plans**
  (`handle_menu_see_plans`, the old price-picker body, returns `SUBSCRIBE_PICK_PLAN`) →
  payment (unchanged). A **✨ Why Beyond Fit?** root-menu button (`handle_menu_why`) reaches
  the same pitch. `menu_back` is registered in `MENU_ROOT` so the pitch's Back works. Static
  copy — no LLM/model/migration. See
  `docs/superpowers/specs/2026-06-21-spd-prepayment-pitch-design.md`.
```

- [ ] **Step 2: Update CHANGELOG.md**

Add at the top:

```markdown
## [1.7.0] — 2026-06-21 — SP-D: pre-payment pitch

### Added
- A compelling static pitch ("Why Beyond Fit?") is now shown before the plan prices in the
  subscribe funnel (and via a root-menu button), so prospects know what they're paying for —
  human-approved plans, weekly auto-regulation, ability/equipment/injury-aware programming,
  halal nutrition, and a direct line to their coach. No model/migration.
```

- [ ] **Step 3: Run the full suite**

Run: `pytest -q`
Expected: green.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md CHANGELOG.md
git commit -m "docs: record SP-D pre-payment pitch (1.7.0)"
```

---

## Definition of done

- Tapping **Subscribe** shows the pitch (not prices) and stays in `MENU_ROOT`.
- **See plans** shows the 1m/3m price picker (from `settings`) and returns `SUBSCRIBE_PICK_PLAN`;
  the rest of the payment funnel is unchanged.
- The **✨ Why Beyond Fit?** menu button shows the pitch; the pitch's **Back** returns to the
  root menu.
- `pytest -q` green. No migration (deploy is a plain rebuild + restart).
```
