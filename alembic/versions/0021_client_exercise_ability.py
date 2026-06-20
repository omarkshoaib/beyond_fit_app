"""Add exercise_ability JSON column to clientprofile (SP-B1 per-family ability).

Nullable — existing rows stay NULL and the selection layer coerces NULL to the
client's experience_level default, so legacy clients are unaffected until they
re-run intake.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("clientprofile", sa.Column("exercise_ability", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("clientprofile", "exercise_ability")
