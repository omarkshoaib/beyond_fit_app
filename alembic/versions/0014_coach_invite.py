"""Add CoachInvite table — pre-registered coach emails."""
from alembic import op
import sqlalchemy as sa


revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "coachinvite",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("email", sa.String, nullable=False, unique=True, index=True),
        sa.Column("invited_by", sa.String, nullable=False),
        sa.Column("invited_at", sa.DateTime, nullable=True),
        sa.Column("accepted_at", sa.DateTime, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("coachinvite")
