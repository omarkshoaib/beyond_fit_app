"""Subscription, payment, access code, chat binding, coach profile, reminder log.

Wipes existing client-derived rows (test data), adds assigned_coach_id +
created_at to clientprofile, and creates the six new tables backing the paid
SaaS flow.

The pre-existing role flags (is_coach, is_admin, coach_id) on clientprofile
are kept because the FastAPI layer (app/api/*) still relies on them. The bot
uses the new CoachProfile + assigned_coach_id + env-based super-admin instead.
CoachInvite is also preserved (FastAPI invite flow).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. Wipe client-derived data (test data; coachinvite preserved). ─
    for table in [
        "rejectionfeedback",
        "setlog",
        "feedback",
        "checkin",
        "nutritionplan",
        "nutritionprofile",
        "pendingapproval",
        "workouthistory",
        "profilesnapshot",
        "auditevent",
        "clientprofile",
    ]:
        op.execute(f"DELETE FROM {table}")

    # ── 2. New tables. ────────────────────────────────────────────────
    op.create_table(
        "coachprofile",
        sa.Column("telegram_user_id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False, index=True),
        sa.Column("mobile", sa.String(), nullable=False),
        sa.Column("specialty", sa.String(), nullable=False),
        sa.Column("years_experience", sa.Integer(), nullable=False),
        sa.Column("certifications", sa.String(), nullable=False),
        sa.Column("cv_file_id", sa.String(), nullable=True),
        sa.Column("portfolio_text", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("decided_by", sa.String(), nullable=True),
        sa.Column("rejection_reason", sa.String(), nullable=True),
    )

    op.create_table(
        "payment",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("client_id", sa.String(), nullable=False, index=True),
        sa.Column("plan_type", sa.String(), nullable=False),
        sa.Column("amount_egp", sa.Integer(), nullable=False),
        sa.Column("screenshot_file_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("verified_by", sa.String(), nullable=True),
        sa.Column("rejection_reason", sa.String(), nullable=True),
    )

    op.create_table(
        "subscription",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("client_id", sa.String(), nullable=False, index=True),
        sa.Column("plan_type", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ends_at", sa.DateTime(), nullable=False, index=True),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("payment_id", sa.Integer(), sa.ForeignKey("payment.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "accesscode",
        sa.Column("client_id", sa.String(), primary_key=True),
        sa.Column("code", sa.String(), nullable=False, unique=True, index=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("rotated_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "chatbinding",
        sa.Column("chat_id", sa.BigInteger(), primary_key=True),
        sa.Column("client_id", sa.String(), nullable=False, index=True),
        sa.Column("bound_at", sa.DateTime(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "reminderlog",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "subscription_id",
            sa.Integer(),
            sa.ForeignKey("subscription.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("subscription_id", "kind", name="uq_reminderlog_sub_kind"),
    )

    # ── 3. Add new columns on clientprofile (keep is_coach/is_admin/coach_id
    #       for FastAPI compatibility; bot doesn't use them). ────────────
    with op.batch_alter_table("clientprofile") as batch:
        batch.add_column(sa.Column("assigned_coach_id", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("created_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("clientprofile") as batch:
        batch.drop_column("created_at")
        batch.drop_column("assigned_coach_id")

    op.drop_table("reminderlog")
    op.drop_table("chatbinding")
    op.drop_table("accesscode")
    op.drop_table("subscription")
    op.drop_table("payment")
    op.drop_table("coachprofile")
