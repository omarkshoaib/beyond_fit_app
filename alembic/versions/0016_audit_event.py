"""Add AuditEvent table — append-only log of admin/coach actions."""
from alembic import op
import sqlalchemy as sa


revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auditevent",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("actor_id", sa.String, nullable=True, index=True),
        sa.Column("actor_email", sa.String, nullable=True),
        sa.Column("action", sa.String, nullable=False, index=True),
        sa.Column("target", sa.String, nullable=True),
        sa.Column("payload", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("auditevent")
