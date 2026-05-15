"""Partial unique index on ChatBinding so each client_id has at most one primary binding.

Without this, code that flips is_primary without first demoting the existing row
can land in a multi-primary state; resolve_primary_chat_id then returns whichever
row the DB scans first. This is a defense-in-depth invariant — current code paths
don't break it, but the DB-level guarantee makes it impossible to drift in future.

Note: Postgres supports `CREATE UNIQUE INDEX … WHERE …` (partial index). SQLite
3.8+ also supports partial indexes, so this works in tests too.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "uq_chatbinding_primary_per_client",
        "chatbinding",
        ["client_id"],
        unique=True,
        postgresql_where="is_primary = true",
        sqlite_where="is_primary = 1",
    )


def downgrade() -> None:
    op.drop_index("uq_chatbinding_primary_per_client", table_name="chatbinding")
