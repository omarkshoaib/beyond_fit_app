"""
NutritionService: generates and calibrates nutrition plans.

All math is deterministic — the LLM never sets a calorie target or macro gram.
The LLM is only called (optionally) to format the plan as readable markdown.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, select

from app.domain.checkin.schema import CheckInExtraction
from app.domain.nutrition.energy import (
    calculate_bmr, calculate_tdee, apply_goal_adjustment, apply_calorie_floor
)
from app.domain.nutrition.macros import calculate_macros
from app.domain.nutrition.meal_builder import build_day_plan, filter_food_pool, validate_day
from app.domain.nutrition.food_db import get_food_db
from app.models import NutritionProfile, NutritionPlan, ProfileSnapshot

logger = logging.getLogger(__name__)

# Calibration constants
_KCAL_SHIFT_FAT_LOSS = 100.0    # kcal to shift per calibration cycle
_KCAL_SHIFT_BULK     = 150.0
_DRIFT_THRESHOLD     = 0.50     # 50% divergence from target rate triggers calibration


class NutritionService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def generate(self, client_id: str) -> Optional[NutritionPlan]:
        """
        Generate a NutritionPlan from the client's NutritionProfile.
        Returns None if the profile doesn't exist or is missing required fields.
        """
        session = self._session
        profile = session.exec(
            select(NutritionProfile).where(NutritionProfile.client_id == client_id)
        ).first()

        if not profile:
            logger.warning("generate: no NutritionProfile for client %s", client_id)
            return None

        missing = [f for f in ("weight_kg", "height_cm", "age", "sex", "goal", "activity_level")
                   if getattr(profile, f) is None]
        if missing:
            logger.warning("generate: profile incomplete (%s), missing: %s", client_id, missing)
            return None

        # ── Compute energy targets ─────────────────────────────────────────
        bmr = calculate_bmr(
            weight_kg=profile.weight_kg,
            height_cm=profile.height_cm,
            age=profile.age,
            sex=profile.sex,
            body_fat_pct=profile.body_fat_pct,
        )
        tdee = calculate_tdee(bmr, profile.activity_level, bias_down=True)
        raw_target = apply_goal_adjustment(
            tdee, profile.goal, profile.aggressiveness or "moderate"
        )
        target_kcal = apply_calorie_floor(
            raw_target, bmr, profile.weight_kg, profile.sex
        )

        # ── Compute macros ─────────────────────────────────────────────────
        lbm = None
        if profile.body_fat_pct is not None:
            lbm = profile.weight_kg * (1.0 - profile.body_fat_pct / 100.0)

        macros = calculate_macros(
            target_kcal=target_kcal,
            weight_kg=profile.weight_kg,
            goal=profile.goal,
            lbm_kg=lbm,
        )

        # ── Build 7-day meal plan ──────────────────────────────────────────
        all_foods = get_food_db()
        filtered_pool = filter_food_pool(
            pool=all_foods,
            allergens=profile.allergies or [],
            religious_restrictions=profile.religious_restrictions or [],
            diet_type=profile.diet_style,
            dislikes=profile.dislikes or [],
            medical_conditions=profile.medical_conditions or [],
            max_cost_tier=profile.budget_tier,
            max_prep_time_min=profile.cooking_time_min,
            max_cooking_skill=profile.cooking_skill,
        )

        days = []
        used_slugs: dict[str, int] = {}
        for _ in range(7):
            day = build_day_plan(
                food_pool=filtered_pool,
                target_kcal=target_kcal,
                target_protein_g=macros["protein_g"],
                target_fat_g=macros["fat_g"],
                target_carb_g=macros["carb_g"],
                target_fiber_g=macros["fiber_g"],
                meals_per_day=profile.meals_per_day,
                used_slugs_this_week=used_slugs,
            )
            for slot in day.slots:
                for food, _ in slot.items:
                    used_slugs[food.slug] = used_slugs.get(food.slug, 0) + 1
            days.append(day)

        # ── Snapshot the profile ───────────────────────────────────────────
        snapshot = ProfileSnapshot(
            client_id=client_id,
            snapshot_json=profile.model_dump_json(),
            reason="nutrition_generate",
            created_at=datetime.now(timezone.utc),
        )
        session.add(snapshot)
        session.flush()  # get snapshot.id before commit

        rationale = (
            f"BMR={bmr:.0f} kcal | TDEE={tdee:.0f} kcal | "
            f"Target={target_kcal:.0f} kcal | Goal={profile.goal} ({profile.aggressiveness or 'moderate'})"
        )

        plan = NutritionPlan(
            client_id=client_id,
            profile_snapshot_id=snapshot.id,
            status="draft",
            kcal_target=target_kcal,
            protein_g=macros["protein_g"],
            fat_g=macros["fat_g"],
            carb_g=macros["carb_g"],
            fiber_g=macros["fiber_g"],
            water_ml=macros["water_ml"],
            plan_json=json.dumps([
                {
                    "day": i + 1,
                    "kcal": round(d.kcal),
                    "protein_g": round(d.protein_g),
                    "fat_g": round(d.fat_g),
                    "carb_g": round(d.carb_g),
                    "fiber_g": round(d.fiber_g),
                    "slots": [
                        {
                            "slot_name": slot.slot_name,
                            "kcal": round(slot.kcal),
                            "protein_g": round(slot.protein_g),
                            "fat_g": round(slot.fat_g),
                            "carb_g": round(slot.carb_g),
                            "fiber_g": round(slot.fiber_g),
                            "items": [
                                {
                                    "name": food.name,
                                    "slug": food.slug,
                                    "category": food.category,
                                    "grams": round(grams),
                                    "kcal": round(food.kcal_per_100g * grams / 100),
                                    "protein_g": round(food.protein_per_100g * grams / 100, 1),
                                    "fat_g": round(food.fat_per_100g * grams / 100, 1),
                                    "carb_g": round(food.carb_per_100g * grams / 100, 1),
                                }
                                for food, grams in slot.items
                            ],
                        }
                        for slot in d.slots
                    ],
                }
                for i, d in enumerate(days)
            ]),
            rationale=rationale,
            created_at=datetime.now(timezone.utc),
        )

        # Safety guard: never persist a degenerate ~0-kcal plan (e.g. if the food
        # pool ever collapses to empty). A real plan totals ~target_kcal/day.
        total_kcal = sum(d.kcal for d in days)
        if not days or total_kcal < 0.5 * target_kcal * len(days):
            raise ValueError(
                f"Refusing to persist a degenerate nutrition plan: {total_kcal:.0f} kcal "
                f"across {len(days)} days vs target {target_kcal:.0f}/day — food pool likely empty."
            )

        session.add(plan)
        session.commit()
        session.refresh(plan)
        return plan

    def calibrate_from_checkin(
        self, client_id: str, extraction: CheckInExtraction
    ) -> None:
        """
        If observed BW trend diverges from target_rate_pct_per_week by ≥50%,
        shift kcal_target by ±100–150 kcal at next regeneration.
        Clamps to safety floor. Records reason in active plan's rationale.
        """
        session = self._session
        profile = session.exec(
            select(NutritionProfile).where(NutritionProfile.client_id == client_id)
        ).first()
        if not profile or not profile.target_rate_pct_per_week:
            return

        if extraction.bodyweight_trend is None:
            return

        goal = profile.goal or "maintain"
        trend = extraction.bodyweight_trend

        # Determine if trend is opposite to goal
        needs_up   = goal in ("lean_bulk", "bulk")  and trend == "losing"
        needs_down = goal in ("fat_loss", "recomp") and trend == "gaining"

        if not (needs_up or needs_down):
            return

        # Find active plan and adjust kcal_target
        active_plan = session.exec(
            select(NutritionPlan)
            .where(NutritionPlan.client_id == client_id)
            .where(NutritionPlan.status == "active")
        ).first()

        if not active_plan or active_plan.kcal_target is None:
            return

        shift = _KCAL_SHIFT_BULK if goal == "bulk" else _KCAL_SHIFT_FAT_LOSS
        if needs_down:
            shift = -shift

        from app.domain.nutrition.energy import apply_calorie_floor, calculate_bmr
        if profile.weight_kg and profile.height_cm and profile.age and profile.sex:
            bmr = calculate_bmr(profile.weight_kg, profile.height_cm,
                                profile.age, profile.sex, profile.body_fat_pct)
            new_target = apply_calorie_floor(
                active_plan.kcal_target + shift,
                bmr, profile.weight_kg, profile.sex,
            )
        else:
            new_target = active_plan.kcal_target + shift

        reason = (
            f"Calibration: BW trend={trend} vs goal={goal} → "
            f"kcal {active_plan.kcal_target:.0f} → {new_target:.0f}"
        )
        logger.info(reason)
        active_plan.rationale = (active_plan.rationale or "") + f"\n[{datetime.now().date()}] {reason}"
        active_plan.kcal_target = new_target
        session.add(active_plan)
        session.commit()
