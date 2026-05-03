"""Add coach role + coach_id link to ClientProfile."""
from alembic import op
import sqlalchemy as sa


revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("clientprofile") as batch:
        batch.add_column(sa.Column("is_coach", sa.Boolean, nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("is_admin", sa.Boolean, nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("coach_id", sa.String, nullable=True, index=True))


def downgrade() -> None:
    with op.batch_alter_table("clientprofile") as batch:
        batch.drop_column("is_coach")
        batch.drop_column("is_admin")
        batch.drop_column("coach_id")
