"""safety_fields

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-17

Adds health-screening fields to ClientProfile (all nullable — no disruption to
existing rows). These fields drive Phase 1.7 safety gates in the generator.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("clientprofile", sa.Column("hypertension", sa.Boolean(), nullable=True))
    op.add_column("clientprofile", sa.Column("systolic_bp", sa.Integer(), nullable=True))
    op.add_column("clientprofile", sa.Column("cardiac_history", sa.Boolean(), nullable=True))
    op.add_column("clientprofile", sa.Column("cardiac_event_weeks_ago", sa.Integer(), nullable=True))
    op.add_column("clientprofile", sa.Column("osteoporosis", sa.Boolean(), nullable=True))
    op.add_column("clientprofile", sa.Column("pregnancy_status", sa.String(), nullable=True))
    op.add_column("clientprofile", sa.Column("postpartum_weeks", sa.Integer(), nullable=True))
    op.add_column("clientprofile", sa.Column("unexplained_weight_loss", sa.Boolean(), nullable=True))
    op.add_column("clientprofile", sa.Column("progressive_neuro_deficits", sa.Boolean(), nullable=True))


def downgrade() -> None:
    for col in [
        "progressive_neuro_deficits", "unexplained_weight_loss", "postpartum_weeks",
        "pregnancy_status", "osteoporosis", "cardiac_event_weeks_ago",
        "cardiac_history", "systolic_bp", "hypertension",
    ]:
        op.drop_column("clientprofile", col)
