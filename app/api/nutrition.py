from __future__ import annotations

import json
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.auth.deps import get_current_user, get_db
from app.models import ClientProfile, NutritionPlan

router = APIRouter(prefix="/nutrition", tags=["nutrition"])


@router.get("/plan")
def get_nutrition_plan(
    user: ClientProfile = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    plan = session.exec(
        select(NutritionPlan)
        .where(NutritionPlan.client_id == user.client_id)
        .where(NutritionPlan.status == "active")
        .order_by(NutritionPlan.created_at.desc())
    ).first()
    if not plan:
        raise HTTPException(status_code=404, detail="No active nutrition plan")
    return {
        "id": plan.id,
        "kcal_target": plan.kcal_target,
        "protein_g": plan.protein_g,
        "fat_g": plan.fat_g,
        "carb_g": plan.carb_g,
        "fiber_g": plan.fiber_g,
        "water_ml": plan.water_ml,
        "plan": json.loads(plan.plan_json) if plan.plan_json else None,
        "markdown": plan.plan_markdown,
    }
