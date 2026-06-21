"""
PDF renderer — produces professional WeasyPrint PDFs for workout and/or nutrition plans.

WeasyPrint rules observed:
  - Running header elements appear BEFORE page content in HTML source.
  - CSS is injected inline (avoids file:// path issues with weasyprint.CSS).
  - FontConfiguration passed to both CSS() and HTML.write_pdf().
  - No JavaScript; charts rendered server-side as inline SVG via matplotlib.
  - break-inside: avoid on .exercise-card inside Grid/block parent.
  - lang= set on <html> for hyphens: auto.
  - Not thread-safe — use processes for parallel rendering.
  - uuid=False for deterministic output (golden tests).
"""
from __future__ import annotations

import base64
import io
import json
import logging
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

try:
    import weasyprint
    from weasyprint.text.fonts import FontConfiguration as _FontConfiguration
    _WEASYPRINT_AVAILABLE = True
except ImportError:
    weasyprint = None  # type: ignore[assignment]
    _FontConfiguration = None  # type: ignore[assignment,misc]
    _WEASYPRINT_AVAILABLE = False

from app.models import ClientProfile, NutritionPlan, WorkoutHistory

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_CSS_DIR = Path(__file__).parent / "css"

_CSS_FILES = ["base.css", "page.css", "components.css", "workout.css", "nutrition.css"]


# ── Jinja2 env ────────────────────────────────────────────────────────────────

def _make_jinja_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


# ── CSS loader ────────────────────────────────────────────────────────────────

_FONT_DIR = Path(__file__).parent / "fonts"

# Editorial palette — keep in sync with css/base.css :root tokens.
_INK = "#211F1C"
_ACCENT = "#B5532F"
_GOLD = "#C9A24B"
_STONE = "#7D7468"
_GREY = "#8C8479"
_HAIR = "#E6E1D8"


def _font_face_css() -> str:
    """@font-face blocks with absolute file URLs so bundled OFL fonts render
    identically in the slim Docker container (no system-font dependency)."""
    blocks = []
    for family, fname in (("Fraunces", "Fraunces.ttf"), ("Source Sans 3", "SourceSans3.ttf")):
        path = (_FONT_DIR / fname).resolve()
        if path.exists():
            blocks.append(
                f"@font-face {{ font-family: '{family}'; "
                f"src: url('file://{path}') format('truetype'); "
                f"font-weight: 100 900; font-style: normal; }}"
            )
    return "\n".join(blocks) + "\n"


def _load_css() -> str:
    parts = [_font_face_css()]
    for fname in _CSS_FILES:
        css_path = _CSS_DIR / fname
        if css_path.exists():
            parts.append(css_path.read_text(encoding="utf-8"))
    return "\n".join(parts)


# ── Chart helpers (server-side SVG, no JS) ────────────────────────────────────

def _macro_pie_svg(protein_g: float, fat_g: float, carb_g: float) -> str:
    """Slim macro donut (hand-built inline SVG): total kcal centered, legend right."""
    try:
        import math
        p, f, c = protein_g * 4.0, fat_g * 9.0, carb_g * 4.0
        total = (p + f + c) or 1.0
        cx, cy, r, sw = 72.0, 75.0, 52.0, 15.0
        circ = 2 * math.pi * r
        kcal = round(p + f + c)
        segs = [(_ACCENT, p), (_GOLD, c), (_STONE, f)]
        arcs, offset = [], 0.0
        for color, val in segs:
            dash = (val / total) * circ
            arcs.append(
                f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" '
                f'stroke-width="{sw}" stroke-dasharray="{dash:.2f} {circ - dash:.2f}" '
                f'stroke-dashoffset="{-offset:.2f}" transform="rotate(-90 {cx} {cy})"/>'
            )
            offset += dash
        legend, leg_svg, ly = [
            ("Protein", round(protein_g), _ACCENT),
            ("Carbs", round(carb_g), _GOLD),
            ("Fat", round(fat_g), _STONE),
        ], "", 52
        for name, grams, color in legend:
            leg_svg += (
                f'<rect x="158" y="{ly}" width="9" height="9" rx="1.5" fill="{color}"/>'
                f'<text x="172" y="{ly + 8}" font-size="10.5" fill="{_INK}">{name}</text>'
                f'<text x="250" y="{ly + 8}" font-size="10.5" fill="{_GREY}" text-anchor="end">{grams}g</text>'
            )
            ly += 22
        return (
            f'<svg viewBox="0 0 256 150" xmlns="http://www.w3.org/2000/svg" '
            f'font-family="Source Sans 3, sans-serif">{"".join(arcs)}'
            f'<text x="{cx}" y="{cy - 1}" text-anchor="middle" font-size="23" '
            f'font-weight="700" fill="{_INK}">{kcal}</text>'
            f'<text x="{cx}" y="{cy + 15}" text-anchor="middle" font-size="8.5" '
            f'fill="{_GREY}" letter-spacing="1.5">KCAL/DAY</text>{leg_svg}</svg>'
        )
    except Exception as exc:
        logger.warning("macro_donut_svg failed: %s", exc)
        return ""


def _volume_bar_svg(workout_week: dict) -> str:
    """Horizontal set-volume bars per training day (hand-built inline SVG)."""
    try:
        days = workout_week.get("days", [])
        if not days:
            return ""
        rows = [(d["day_name"], sum(s["sets"] for s in d.get("slots", []))) for d in days]
        maxv = max((v for _, v in rows), default=1) or 1
        row_h, bar_h, label_w, chart_w = 26, 12, 150, 340
        width, height = label_w + chart_w + 44, len(rows) * row_h + 14
        bars, y = "", 12
        for name, val in rows:
            bw = (val / maxv) * chart_w
            bars += (
                f'<text x="0" y="{y + bar_h - 2}" font-size="10.5" fill="{_INK}">{name}</text>'
                f'<rect x="{label_w}" y="{y}" width="{chart_w}" height="{bar_h}" rx="2" fill="{_HAIR}"/>'
                f'<rect x="{label_w}" y="{y}" width="{bw:.1f}" height="{bar_h}" rx="2" fill="{_ACCENT}"/>'
                f'<text x="{label_w + bw + 6:.1f}" y="{y + bar_h - 2}" font-size="9.5" fill="{_GREY}">{val}</text>'
            )
            y += row_h
        return (
            f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
            f'font-family="Source Sans 3, sans-serif">{bars}</svg>'
        )
    except Exception as exc:
        logger.warning("volume_bar_svg failed: %s", exc)
        return ""


# ── QR helper ─────────────────────────────────────────────────────────────────

def _make_qr_data_uri(url: str) -> str:
    """Return a base64-encoded PNG data URI for a QR code."""
    try:
        import qrcode  # type: ignore
        qr = qrcode.QRCode(box_size=4, border=1)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        return f"data:image/png;base64,{b64}"
    except Exception:
        return ""


# ── Template context builders ─────────────────────────────────────────────────

def _build_workout_context(workout_history: WorkoutHistory, client: ClientProfile) -> dict:
    """Parse workout JSON into template-friendly dicts."""
    week: dict = json.loads(workout_history.workout_json)
    days: list[dict] = week.get("days", [])
    week_number: int = week.get("week_number", 1)
    is_deload = (week_number % 5) == 0

    # Enrich slots with QR data URIs (placeholder URL pattern)
    for day in days:
        for slot in day.get("slots", []):
            # Placeholder — real deployments would resolve exercise video URLs
            slot["qr_data_uri"] = ""

    # Week cells (7-day grid including rest days) — training days assigned Mon→Sun
    all_days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    week_cells = []
    day_idx = 0
    for dow in all_days:
        if day_idx < len(days):
            d = days[day_idx]
            week_cells.append({
                "day_label": dow,
                "focus": d["day_name"],
                "total_sets": sum(s["sets"] for s in d.get("slots", [])),
                "is_rest": False,
            })
            day_idx += 1
        else:
            week_cells.append({
                "day_label": dow,
                "focus": "Rest",
                "total_sets": 0,
                "is_rest": True,
            })

    # Day summaries for the table
    day_summaries = []
    for d in days:
        slots = d.get("slots", [])
        main = next((s for s in slots if s.get("slot_type") == "main_lift"), slots[0] if slots else {})
        day_summaries.append({
            "name": d["day_name"],
            "focus": d["day_name"],
            "main_lift": main.get("exercise_name", "—"),
            "total_sets": sum(s["sets"] for s in slots),
            "rpe": main.get("rpe", "—"),
        })

    return {
        "workout_plan": workout_history,
        "workout_days": days,
        "week_cells": week_cells,
        "day_summaries": day_summaries,
        "is_deload": is_deload,
        "volume_chart_svg": _volume_bar_svg(week),
    }


def _build_nutrition_context(plan: NutritionPlan) -> dict:
    """Parse nutrition plan JSON into template-friendly dicts."""
    nutrition_days = []
    shopping_list: dict[str, list] = defaultdict(list)

    if plan.plan_json:
        try:
            days_raw = json.loads(plan.plan_json)
            for day_raw in days_raw:
                nutrition_days.append(day_raw)
                # Aggregate shopping list from slot-level food items
                for slot in day_raw.get("slots", []):
                    for item in slot.get("items", []):
                        category = item.get("category", "other")
                        slug = item.get("slug", "")
                        # Accumulate total grams per food across all days
                        existing = next(
                            (e for e in shopping_list[category] if e["slug"] == slug),
                            None,
                        )
                        if existing:
                            existing["total_grams"] += item.get("grams", 0)
                        else:
                            shopping_list[category].append({
                                "name": item.get("name", slug),
                                "slug": slug,
                                "total_grams": item.get("grams", 0),
                            })
        except (json.JSONDecodeError, TypeError):
            pass

    macro_svg = _macro_pie_svg(
        protein_g=plan.protein_g or 0,
        fat_g=plan.fat_g or 0,
        carb_g=plan.carb_g or 0,
    )

    return {
        "nutrition_plan": plan,
        "nutrition_days": nutrition_days,
        "shopping_list": dict(shopping_list),
        "macro_chart_svg": macro_svg,
    }


# ── Public render function ─────────────────────────────────────────────────────

def render_plan_pdf(
    client: ClientProfile,
    out_path: Path,
    workout_history: Optional[WorkoutHistory] = None,
    nutrition_plan: Optional[NutritionPlan] = None,
    draft_watermark: bool = False,
    block_number: int = 1,
    version: int = 1,
) -> Path:
    """
    Render a PDF for the given client.

    At least one of workout_history or nutrition_plan must be provided.
    Returns out_path after writing.
    """
    if workout_history is None and nutrition_plan is None:
        raise ValueError("render_plan_pdf: at least one of workout_history or nutrition_plan required")

    if not _WEASYPRINT_AVAILABLE:
        raise RuntimeError("WeasyPrint is required for PDF rendering")

    env = _make_jinja_env()
    css_content = _load_css()

    # Determine plan title
    has_workout = workout_history is not None
    has_nutrition = nutrition_plan is not None
    if has_workout and has_nutrition:
        plan_title = "Combined Training & Nutrition Plan"
    elif has_workout:
        plan_title = "Training Plan"
    else:
        plan_title = "Nutrition Plan"

    # Build context
    ctx: dict = {
        "client": client,
        "plan_title": plan_title,
        "block_number": block_number,
        "version": version,
        "generated_date": date.today().isoformat(),
        "draft_watermark": draft_watermark,
        "nutrition_only": not has_workout and has_nutrition,
        "css_content": css_content,
        # Defaults
        "workout_plan": None,
        "workout_days": [],
        "week_cells": [],
        "day_summaries": [],
        "is_deload": False,
        "volume_chart_svg": "",
        "nutrition_plan": None,
        "nutrition_days": [],
        "shopping_list": {},
        "macro_chart_svg": "",
    }

    if has_workout:
        ctx.update(_build_workout_context(workout_history, client))

    if has_nutrition:
        ctx.update(_build_nutrition_context(nutrition_plan))

    # Render HTML
    tmpl = env.get_template("plan.html.j2")
    html_str = tmpl.render(**ctx)

    # WeasyPrint render
    font_config = _FontConfiguration()
    html_doc = weasyprint.HTML(string=html_str, base_url=str(_TEMPLATE_DIR))
    css_obj = weasyprint.CSS(
        string=css_content,
        font_config=font_config,
    )

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    html_doc.write_pdf(
        target=str(out_path),
        stylesheets=[css_obj],
        font_config=font_config,
        optimize_images=True,
        presentational_hints=True,
    )
    logger.info("PDF written to %s", out_path)
    return out_path


def default_pdf_path(
    client_id: str,
    block_number: int,
    version: int,
    plan_type: str = "combined",
    base_dir: Path = Path("pdfs"),
) -> Path:
    """Construct a deterministic output path."""
    slug = client_id.lower().replace(" ", "_")
    return base_dir / f"{slug}_block{block_number}_v{version}_{plan_type}.pdf"
