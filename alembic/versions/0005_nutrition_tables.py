"""nutrition_tables

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-17

Adds NutritionProfile and NutritionPlan tables for Phase 3.
All columns nullable to avoid disrupting existing rows.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "nutritionprofile",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("client_id", sa.String(), sa.ForeignKey("clientprofile.client_id"),
                  nullable=False, unique=True, index=True),
        sa.Column("weight_kg", sa.Float(), nullable=True),
        sa.Column("height_cm", sa.Float(), nullable=True),
        sa.Column("age", sa.Integer(), nullable=True),
        sa.Column("sex", sa.String(), nullable=True),
        sa.Column("body_fat_pct", sa.Float(), nullable=True),
        sa.Column("goal", sa.String(), nullable=True),
        sa.Column("aggressiveness", sa.String(), nullable=True),
        sa.Column("activity_level", sa.String(), nullable=True),
        sa.Column("target_rate_pct_per_week", sa.Float(), nullable=True),
        sa.Column("diet_style", sa.String(), nullable=True),
        sa.Column("allergies", sa.JSON(), nullable=True),
        sa.Column("dislikes", sa.JSON(), nullable=True),
        sa.Column("religious_restrictions", sa.JSON(), nullable=True),
        sa.Column("meals_per_day", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("cooking_skill", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("cooking_time_min", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("budget_tier", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("medical_conditions", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "nutritionplan",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("client_id", sa.String(), sa.ForeignKey("clientprofile.client_id"),
                  nullable=False, index=True),
        sa.Column("profile_snapshot_id", sa.Integer(),
                  sa.ForeignKey("profilesnapshot.id"), nullable=True),
        sa.Column("block_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("kcal_target", sa.Float(), nullable=True),
        sa.Column("protein_g", sa.Float(), nullable=True),
        sa.Column("fat_g", sa.Float(), nullable=True),
        sa.Column("carb_g", sa.Float(), nullable=True),
        sa.Column("fiber_g", sa.Float(), nullable=True),
        sa.Column("water_ml", sa.Float(), nullable=True),
        sa.Column("plan_json", sa.String(), nullable=True),
        sa.Column("plan_markdown", sa.String(), nullable=True),
        sa.Column("rationale", sa.String(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("pdf_path", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("nutritionplan")
    op.drop_table("nutritionprofile")
