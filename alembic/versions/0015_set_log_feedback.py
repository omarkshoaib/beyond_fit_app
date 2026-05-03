"""Add SetLog (per-set logger) + Feedback (in-app bug reports)."""
from alembic import op
import sqlalchemy as sa


revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "setlog",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("client_id", sa.String, nullable=False, index=True),
        sa.Column("history_id", sa.Integer, nullable=False, index=True),
        sa.Column("day_index", sa.Integer, nullable=False),
        sa.Column("slot_index", sa.Integer, nullable=False),
        sa.Column("set_index", sa.Integer, nullable=False),
        sa.Column("actual_reps", sa.Integer, nullable=False),
        sa.Column("actual_weight", sa.Float, nullable=False),
        sa.Column("rpe", sa.Integer, nullable=True),
        sa.Column("logged_at", sa.DateTime, nullable=True),
    )
    op.create_table(
        "feedback",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("client_id", sa.String, nullable=True, index=True),
        sa.Column("email", sa.String, nullable=True),
        sa.Column("message", sa.String, nullable=False),
        sa.Column("app_version", sa.String, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("feedback")
    op.drop_table("setlog")
