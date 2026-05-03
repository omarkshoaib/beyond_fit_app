"""Add verified_at to ClientProfile for email verification."""
from alembic import op
import sqlalchemy as sa


revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("clientprofile") as batch:
        batch.add_column(sa.Column("verified_at", sa.DateTime, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("clientprofile") as batch:
        batch.drop_column("verified_at")
