# PDF Editorial Redesign — Design

**Goal:** Make the coaching-plan PDF more appealing and easier to read, in a premium-editorial style.

**Approved direction:** Premium editorial + modern inline-SVG charts.

## Design system
- **Palette:** ink `#211F1C`, paper `#FCFAF6`, accent terracotta `#B5532F`, warm-grey text `#8C8479`, hairline `#E6E1D8`, tile `#F4F0E8`. One unified system across cover/workout/nutrition (retires navy/green/orange clash).
- **Type:** bundled OFL fonts via `@font-face` (render identically in the slim Docker container):
  - Display/headings: **Fraunces** (`app/adapters/pdf/fonts/Fraunces.ttf`).
  - Body/UI: **Source Sans 3** (`SourceSans3.ttf`).
  - Fallbacks: `Georgia, "DejaVu Serif", serif` / `"DejaVu Sans", sans-serif`.
  - No monospace for data; numbers use lining figures.

## Layout
- **Cover:** serif display title, hairline + accent tick, meta grid rebalanced (no dead mid-page).
- **Weekly overview:** week-strip + session summary tightened together; no near-blank page.
- **Macro tiles:** uniform ink numbers (accent only on headline kcal), fixed labels, even grid.
- **Day/meal cards:** quiet headers (ink + thin accent rule, not heavy color blocks), airy rows, hairline dividers.

## Charts (replace matplotlib)
- `_macro_donut_svg(protein_g, fat_g, carb_g)` → slim 3-segment donut, total kcal centered.
- `_volume_bars_svg(week)` → horizontal bars per muscle group.
- Drop matplotlib usage in `renderer.py` chart helpers.

## Files
- `app/adapters/pdf/css/*` (rewrite to the system), `renderer.py` (SVG fns + @font-face wiring + FontConfiguration), `templates/sections/*` + `partials/*` (class/markup), `app/adapters/pdf/fonts/*.ttf` (new).

## Verification
- All `tests/test_pdf.py` stay green (no Jinja errors; charts return valid SVG).
- Render real combined + nutrition-only PDFs; screenshot pages; confirm legibility + cohesion.
