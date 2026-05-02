"""add password_hash to clientprofile

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-02
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("clientprofile", sa.Column("password_hash", sa.String(), nullable=True))


def downgrade():
    op.drop_column("clientprofile", "password_hash")
