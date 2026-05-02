"""round-2 usability fields

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-24
"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clientprofile", sa.Column("limitations_notes", sa.String(), nullable=True))
    op.add_column("clientprofile", sa.Column("safety_override_note", sa.String(), nullable=True))
    op.add_column("workouthistory", sa.Column("plan_started_at", sa.DateTime(), nullable=True))
    op.add_column("workouthistory", sa.Column("generation_notes", sa.JSON(), nullable=True))
    op.add_column("checkin", sa.Column("structured_progress", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("clientprofile", "limitations_notes")
    op.drop_column("clientprofile", "safety_override_note")
    op.drop_column("workouthistory", "plan_started_at")
    op.drop_column("workouthistory", "generation_notes")
    op.drop_column("checkin", "structured_progress")
