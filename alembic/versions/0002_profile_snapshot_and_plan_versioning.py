"""profile_snapshot_and_plan_versioning

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-16

Adds:
- profilesnapshot table (captures client state at each plan generation)
- client.features JSON column (per-client feature flags)
- workouthistory.status, block_number, version, profile_snapshot_id columns
  (WorkoutHistory becomes the versioned WorkoutPlan table)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "profilesnapshot",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("client_id", sa.String(), sa.ForeignKey("clientprofile.client_id"), nullable=False, index=True),
        sa.Column("snapshot_json", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False, server_default="manual"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # Per-client feature flags (e.g. {"nutrition": true})
    op.add_column("clientprofile", sa.Column("features", sa.JSON(), nullable=True))

    # Plan versioning on WorkoutHistory
    op.add_column(
        "workouthistory",
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
    )
    op.add_column(
        "workouthistory",
        sa.Column("block_number", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "workouthistory",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "workouthistory",
        sa.Column("profile_snapshot_id", sa.Integer(), sa.ForeignKey("profilesnapshot.id"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workouthistory", "profile_snapshot_id")
    op.drop_column("workouthistory", "version")
    op.drop_column("workouthistory", "block_number")
    op.drop_column("workouthistory", "status")
    op.drop_column("clientprofile", "features")
    op.drop_table("profilesnapshot")
