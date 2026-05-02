"""production usability fields

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-23
"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clientprofile", sa.Column("coach_overrides", sa.JSON(), nullable=True))
    op.add_column("pendingapproval", sa.Column("edit_log", sa.JSON(), nullable=True))
    op.add_column("pendingapproval", sa.Column("cancelled_at", sa.DateTime(), nullable=True))
    op.add_column("workouthistory", sa.Column("acknowledged_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("clientprofile", "coach_overrides")
    op.drop_column("pendingapproval", "edit_log")
    op.drop_column("pendingapproval", "cancelled_at")
    op.drop_column("workouthistory", "acknowledged_at")
