# Design: SP-D — Pre-payment pitch

**Date:** 2026-06-21
**Branch base:** `fix/audit-hardening`
**Status:** Approved design — pending implementation plan

Fourth and final sub-project (SP-A, SP-B1, SP-C shipped).

## Problem (feedback this slice closes)

**#4 — a new client doesn't know what they're paying for.** The pre-payment funnel goes
straight from **💳 Subscribe** to the plan-price picker (`handle_menu_subscribe`,
`bot.py:709`, returns `SUBSCRIBE_PICK_PLAN` showing "Choose your plan: [1 Month][3 Months]").
The only "what we offer" content lives in the LLM FAQ (`menu_faq`), which fires **only if the
client asks**. So a prospect sees prices before ever learning what makes Beyond Fit different —
and may leave for another online coach. SP-D shows a compelling, **static** pitch **before** the
plans, so the client knows what they're buying and why it's better.

## Goals

- A polished pitch (what we are / our niche / what's included) is shown **before** the plan
  prices, unavoidably, in the subscribe funnel.
- The same pitch is also reachable from the root menu (a "✨ Why Beyond Fit?" button) for
  browsers.
- The pitch highlights the **real, already-built** differentiators (true claims, not fluff).

## Non-goals (deferred)

- No LLM-generated copy (static, deterministic, on-brand — an LLM pitch varies and can
  over-promise). No A/B testing, no DB-configurable content, no testimonials/images, no
  pricing changes (prices stay sourced from `settings`).

---

## Architecture

Pure presentation wiring inside the existing pre-payment `ConversationHandler` (state
`MENU_ROOT` → `SUBSCRIBE_PICK_PLAN`). No model, no migration, no LLM.

```
root menu (_show_root_menu)
  ├─ 💳 Subscribe (menu_subscribe) ──> [PITCH] ──┐
  └─ ✨ Why Beyond Fit? (menu_why) ──> [PITCH] ──┤
                                                 ↓ 💳 See plans (menu_see_plans)
                                          plan picker (the current handle_menu_subscribe body)
                                                 ↓ sub_pick:1m|3m
                                          payment instructions  (unchanged)
```

## Components

1. **`WHY_BEYOND_FIT`** — a module-level static constant (Telegram-Markdown string). The pitch
   copy (final text below). Prices are **not** embedded — the pitch ends with a "See plans"
   button that leads to the price picker.

2. **`_show_pitch(query)`** — a small helper that renders `WHY_BEYOND_FIT` with the keyboard
   `[💳 See plans →  (menu_see_plans)]` + `[⬅️ Back  (menu_back)]`, and returns `MENU_ROOT`
   (the client stays in the menu conversation). Reused by both entry buttons.

3. **`handle_menu_subscribe`** — **changed**: instead of showing the price picker, it now calls
   `_show_pitch(query)` (returns `MENU_ROOT`). (It used to build the price keyboard + return
   `SUBSCRIBE_PICK_PLAN`.)

4. **`handle_menu_see_plans`** — **new**: the *old* `handle_menu_subscribe` body verbatim (the
   1m/3m price keyboard from `settings` + Back), returns `SUBSCRIBE_PICK_PLAN`. Callback
   `menu_see_plans`.

5. **`handle_menu_why`** — **new**: calls `_show_pitch(query)`. Callback `menu_why`.

6. **`_show_root_menu`** — add a `[✨ Why Beyond Fit?  (menu_why)]` button (above or below
   Subscribe).

7. **Registration** — in the `MENU_ROOT` state handler list (`bot.py:5875`), add
   `CallbackQueryHandler(handle_menu_why, "^menu_why$")` and
   `CallbackQueryHandler(handle_menu_see_plans, "^menu_see_plans$")`. `menu_back` already
   returns to the root menu (`handle_menu_back`); `_show_pitch`'s Back button reuses it.

## The pitch copy (`WHY_BEYOND_FIT`)

```
🏋️ *Why Beyond Fit?*

Most fitness apps spit out a generic plan and leave you alone. We're different — every
client gets a programme built by a deterministic, science-based engine *and* personally
reviewed and approved by a real human coach before it ever reaches you.

*What you get:*
✅ *A real coach in your corner* — every plan is checked and approved by a human, not
   auto-sent by a bot. Message your coach anytime with a question and get a real answer.
🔬 *Programming that actually progresses* — proper periodization, and weekly auto-regulation
   that adjusts your loads to how *you* actually performed at check-in.
🧩 *Built around your reality* — your equipment (even bodyweight-only), your ability (we
   regress the lifts you can't do *yet* and build you up), and your injuries (safe
   substitutions, never "push through it").
🥗 *Halal nutrition* — clean, balanced meal plans that fit your goal.
📈 *You vs. last week* — you check in, we adapt. Real progression, not the same plan on repeat.

This is coaching that adapts to you — not a one-size-fits-all PDF.

Tap *See plans* to get started. 👇
```

(Wording is final and reviewed; the implementer uses it verbatim.)

## Error handling

- Markdown send failure → reuse the existing `safe_send_markdown` / plain-text fallback pattern
  the menu already uses (`edit_message_text` with `parse_mode="Markdown"`, the codebase's
  established approach). No new failure modes — it's a text screen.

## Testing (TDD)

- Tapping **Subscribe** (`handle_menu_subscribe`) now renders the pitch (text contains "Why
  Beyond Fit") and returns `MENU_ROOT` — **not** the price picker.
- **See plans** (`handle_menu_see_plans`) renders the 1m/3m price keyboard (from `settings`)
  and returns `SUBSCRIBE_PICK_PLAN` — preserving the old behavior one click later.
- The **Why Beyond Fit?** menu button (`handle_menu_why`) renders the pitch.
- `_show_pitch` keyboard has a See-plans button (`menu_see_plans`) and a Back button
  (`menu_back`).
- Regression: the full funnel still reaches payment (Subscribe → See plans → sub_pick → payment
  instructions unchanged).

## Appendix — verified surfaces (file:line)

- `_show_root_menu` `bot.py:~684-703` (menu buttons + `MENU_ROOT`).
- `handle_menu_subscribe` `bot.py:709-722` (currently → price picker → `SUBSCRIBE_PICK_PLAN`).
- `handle_subscribe_pick_plan` (payment, unchanged) just below.
- `MENU_ROOT` state registration `bot.py:~5875`.
- Prices: `get_settings().subscription_price_1m_egp / _3m_egp`.
- Back: `handle_menu_back` (`menu_back`) returns to the root menu.
