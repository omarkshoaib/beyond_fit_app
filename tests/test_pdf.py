"""
Tests for Phase 4 — PDF renderer.

We do NOT call WeasyPrint in CI (slow, needs system libs).
Instead we verify:
  1. Template rendering produces valid HTML (no Jinja2 errors).
  2. Context builders parse workout/nutrition JSON correctly.
  3. render_plan_pdf raises ValueError when no plan is provided.
  4. default_pdf_path produces the expected filename pattern.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.adapters.pdf.renderer import (
    _build_nutrition_context,
    _build_workout_context,
    _make_jinja_env,
    _load_css,
    default_pdf_path,
    render_plan_pdf,
)
from app.models import ClientProfile, NutritionPlan, WorkoutHistory


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_client() -> ClientProfile:
    return ClientProfile(
        client_id="test_user",
        avatar="gen_pop",
        training_days=4,
        experience_level="intermediate",
        limitations=[],
        available_equipment=["barbell", "dumbbell", "cable"],
    )


def _make_workout_history() -> WorkoutHistory:
    week_json = {
        "week_number": 1,
        "days": [
            {
                "day_name": "Upper A",
                "total_fatigue": 10,
                "slots": [
                    {
                        "slot_type": "main_lift",
                        "exercise_id": "barbell_bench_press",
                        "exercise_name": "Barbell Bench Press",
                        "sets": 4,
                        "reps": "6-8",
                        "rpe": 8,
                        "rest_seconds": 180,
                        "tempo": "2-0-X-0",
                        "coaching_cues": ["Retract scapula, drive feet into floor"],
                        "warmup_sets": [
                            {"pct_of_working": 0.0, "reps": 8, "rest_seconds": 60, "is_primer": False},
                            {"pct_of_working": 0.5, "reps": 5, "rest_seconds": 60, "is_primer": False},
                            {"pct_of_working": 0.7, "reps": 3, "rest_seconds": 90, "is_primer": False},
                        ],
                        "target_weight": 100.0,
                        "actual_weight": None,
                        "actual_rpe": None,
                    },
                    {
                        "slot_type": "primary_accessory",
                        "exercise_id": "cable_row",
                        "exercise_name": "Cable Row",
                        "sets": 3,
                        "reps": "10-12",
                        "rpe": 7,
                        "rest_seconds": 90,
                        "tempo": "3-0-1-0",
                        "coaching_cues": ["Keep chest tall"],
                        "warmup_sets": [],
                        "target_weight": None,
                        "actual_weight": None,
                        "actual_rpe": None,
                    },
                ],
            }
        ],
    }
    return WorkoutHistory(
        history_id=1,
        client_id="test_user",
        week_number=1,
        workout_json=json.dumps(week_json),
        status="active",
        block_number=1,
        version=1,
    )


def _make_nutrition_plan() -> NutritionPlan:
    plan_json = json.dumps([
        {"day": 1, "kcal": 2400, "protein_g": 180, "fat_g": 80, "carb_g": 240, "fiber_g": 28},
        {"day": 2, "kcal": 2400, "protein_g": 180, "fat_g": 80, "carb_g": 240, "fiber_g": 28},
    ])
    return NutritionPlan(
        id=1,
        client_id="test_user",
        block_number=1,
        version=1,
        status="active",
        kcal_target=2400.0,
        protein_g=180.0,
        fat_g=80.0,
        carb_g=240.0,
        fiber_g=28.0,
        water_ml=2800.0,
        plan_json=plan_json,
        rationale="BMR=1800 kcal | TDEE=2700 kcal | Target=2400 kcal",
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestCSSLoading:
    def test_css_loads_without_error(self):
        css = _load_css()
        assert len(css) > 100
        assert "--ink:" in css
        assert ".exercise-card" in css


class TestContextBuilders:
    def test_workout_context_parses_days(self):
        client = _make_client()
        wh = _make_workout_history()
        ctx = _build_workout_context(wh, client)

        assert "workout_days" in ctx
        assert len(ctx["workout_days"]) == 1
        assert ctx["workout_days"][0]["day_name"] == "Upper A"

    def test_workout_context_builds_week_cells(self):
        ctx = _build_workout_context(_make_workout_history(), _make_client())
        assert len(ctx["week_cells"]) == 7  # always 7 cells (Mon–Sun)
        training_cells = [c for c in ctx["week_cells"] if not c["is_rest"]]
        assert len(training_cells) == 1  # one training day in fixture

    def test_workout_context_day_summaries(self):
        ctx = _build_workout_context(_make_workout_history(), _make_client())
        assert len(ctx["day_summaries"]) == 1
        summary = ctx["day_summaries"][0]
        assert summary["main_lift"] == "Barbell Bench Press"
        assert summary["total_sets"] == 7  # 4 + 3

    def test_nutrition_context_parses_plan_json(self):
        plan = _make_nutrition_plan()
        ctx = _build_nutrition_context(plan)
        assert ctx["nutrition_plan"] is plan
        assert len(ctx["nutrition_days"]) == 2
        assert ctx["nutrition_days"][0]["kcal"] == 2400

    def test_nutrition_context_handles_null_plan_json(self):
        plan = _make_nutrition_plan()
        plan.plan_json = None
        ctx = _build_nutrition_context(plan)
        assert ctx["nutrition_days"] == []


class TestTemplateRendering:
    """Verify Jinja2 templates render without errors (no WeasyPrint call)."""

    def _render_html(self, **overrides) -> str:
        from app.adapters.pdf.renderer import _load_css
        env = _make_jinja_env()
        client = _make_client()
        wh = _make_workout_history()
        plan = _make_nutrition_plan()

        ctx = {
            "client": client,
            "plan_title": "Test Plan",
            "block_number": 1,
            "version": 1,
            "generated_date": "2026-04-17",
            "draft_watermark": False,
            "nutrition_only": False,
            "css_content": "",  # skip CSS for speed
            **_build_workout_context(wh, client),
            **_build_nutrition_context(plan),
        }
        ctx.update(overrides)
        return env.get_template("plan.html.j2").render(**ctx)

    def test_full_plan_renders(self):
        html = self._render_html()
        assert "Test Plan" in html
        assert "test_user" in html

    def test_draft_watermark_rendered(self):
        html = self._render_html(draft_watermark=True)
        assert "DRAFT" in html

    def test_exercise_card_in_html(self):
        html = self._render_html()
        assert "Barbell Bench Press" in html

    def test_nutrition_macros_in_html(self):
        html = self._render_html()
        assert "2400" in html  # kcal target

    def test_no_workout_renders_nutrition_only(self):
        env = _make_jinja_env()
        plan = _make_nutrition_plan()
        client = _make_client()
        ctx = {
            "client": client,
            "plan_title": "Nutrition Plan",
            "block_number": 1,
            "version": 1,
            "generated_date": "2026-04-17",
            "draft_watermark": False,
            "nutrition_only": True,
            "css_content": "",
            "workout_plan": None,
            "workout_days": [],
            "week_cells": [],
            "day_summaries": [],
            "is_deload": False,
            "volume_chart_svg": "",
            **_build_nutrition_context(plan),
        }
        html = env.get_template("plan.html.j2").render(**ctx)
        assert "Nutrition Plan" in html
        assert "2400" in html


class TestRenderPlanPdfGuards:
    def test_raises_if_no_plan(self):
        with pytest.raises(ValueError, match="at least one"):
            render_plan_pdf(
                client=_make_client(),
                out_path=Path("/tmp/test.pdf"),
            )

    def test_calls_weasyprint_with_correct_args(self, tmp_path):
        """Smoke test: mock WeasyPrint, check HTML() is called."""
        out = tmp_path / "test.pdf"

        mock_html_instance = MagicMock()
        mock_html_instance.write_pdf.return_value = None

        with (
            patch("app.adapters.pdf.renderer.weasyprint") as mock_wp,
            patch("app.adapters.pdf.renderer._WEASYPRINT_AVAILABLE", True),
            patch("app.adapters.pdf.renderer._FontConfiguration", MagicMock),
        ):
            mock_wp.HTML.return_value = mock_html_instance
            mock_wp.CSS.return_value = MagicMock()

            render_plan_pdf(
                client=_make_client(),
                out_path=out,
                workout_history=_make_workout_history(),
            )
            mock_wp.HTML.assert_called_once()


class TestDefaultPdfPath:
    def test_path_structure(self):
        p = default_pdf_path("Alice Smith", 2, 1, "combined")
        assert p.name == "alice_smith_block2_v1_combined.pdf"

    def test_nutrition_only_label(self):
        p = default_pdf_path("bob", 1, 1, "nutrition")
        assert "nutrition" in p.name

    def test_custom_base_dir(self, tmp_path):
        p = default_pdf_path("carl", 1, 1, base_dir=tmp_path)
        assert str(tmp_path) in str(p)
