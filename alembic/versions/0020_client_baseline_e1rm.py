"""Add squat/bench/deadlift estimated-1RM columns to clientprofile for week-1 load seeding.

All nullable — existing rows are unaffected (clients onboarded before this feature
simply have no baselines and get guidance strings instead of seeded loads).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("clientprofile", sa.Column("squat_e1rm", sa.Float(), nullable=True))
    op.add_column("clientprofile", sa.Column("bench_e1rm", sa.Float(), nullable=True))
    op.add_column("clientprofile", sa.Column("deadlift_e1rm", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("clientprofile", "deadlift_e1rm")
    op.drop_column("clientprofile", "bench_e1rm")
    op.drop_column("clientprofile", "squat_e1rm")
