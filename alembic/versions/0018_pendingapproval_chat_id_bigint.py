"""Widen pendingapproval.client_chat_id from INTEGER to BIGINT.

Telegram chat_ids can exceed 2^31 (e.g. 5_174_685_330), causing
`psycopg2.errors.NumericValueOutOfRange` on INSERT. The SQLModel column was
already declared with BigInteger, but the original migration created the
column as plain INTEGER, leaving production drifted from the model.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("pendingapproval") as batch:
        batch.alter_column(
            "client_chat_id",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("pendingapproval") as batch:
        batch.alter_column(
            "client_chat_id",
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=False,
        )
