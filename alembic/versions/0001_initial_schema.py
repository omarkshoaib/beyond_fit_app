"""initial_schema

Revision ID: 0001
Revises:
Create Date: 2026-04-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "clientprofile",
        sa.Column("client_id", sa.String(), primary_key=True),
        sa.Column("avatar", sa.String(), nullable=False),
        sa.Column("training_days", sa.Integer(), nullable=False),
        sa.Column("experience_level", sa.String(), nullable=False),
        sa.Column("limitations", sa.JSON(), nullable=True),
        sa.Column("available_equipment", sa.JSON(), nullable=True),
        sa.Column("week_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("active_workout_id", sa.Integer(), nullable=True),
    )

    op.create_table(
        "pendingapproval",
        sa.Column("approval_uuid", sa.String(), primary_key=True),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("client_chat_id", sa.Integer(), nullable=False),
        sa.Column("client_name", sa.String(), nullable=False),
        sa.Column("client_email", sa.String(), nullable=False),
        sa.Column("workout_json", sa.String(), nullable=False),
        sa.Column("coaching_message", sa.String(), nullable=False),
    )

    op.create_table(
        "workouthistory",
        sa.Column("history_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("client_id", sa.String(), sa.ForeignKey("clientprofile.client_id"), nullable=False, index=True),
        sa.Column("week_number", sa.Integer(), nullable=False),
        sa.Column("workout_json", sa.String(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("workouthistory")
    op.drop_table("pendingapproval")
    op.drop_table("clientprofile")
