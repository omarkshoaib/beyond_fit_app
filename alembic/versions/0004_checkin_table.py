"""checkin_table

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-17

Adds the CheckIn table for Phase 2 conversational check-in storage.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "checkin",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("client_id", sa.String(), sa.ForeignKey("clientprofile.client_id"),
                  nullable=False, index=True),
        sa.Column("raw_text", sa.String(), nullable=False),
        sa.Column("extraction_json", sa.String(), nullable=True),
        sa.Column("digest_markdown", sa.String(), nullable=True),
        sa.Column("active_workout_plan_id", sa.Integer(), nullable=True),
        sa.Column("resulting_workout_plan_id", sa.Integer(), nullable=True),
        sa.Column("needs_coach_review", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("checkin")
