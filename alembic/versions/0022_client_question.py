"""Add clientquestion table for the client↔coach Q&A channel (SP-C)."""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "clientquestion",
        sa.Column("question_id", sa.String(), primary_key=True),
        sa.Column("client_id", sa.String(), nullable=False, index=True),
        sa.Column("client_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("coach_recipient_id", sa.BigInteger(), nullable=False),
        sa.Column("question_text", sa.String(), nullable=False),
        sa.Column("draft_answer", sa.String(), nullable=True),
        sa.Column("final_answer", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("answered_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("clientquestion")
