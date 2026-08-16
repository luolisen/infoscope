"""add maintenance run state

Revision ID: 20260816_0017
Revises: 20260816_0016
Create Date: 2026-08-16 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260816_0017"
down_revision: str | None = "20260816_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "maintenance_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("phase", sa.String(length=32), nullable=True),
        sa.Column("active_slot", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_maintenance_runs_status",
        ),
        sa.CheckConstraint(
            "phase IS NULL OR phase IN ('window_analysis', 'event_backwrite', "
            "'reconciliation', 'personalization')",
            name="ck_maintenance_runs_phase",
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND phase IS NULL AND started_at IS NULL AND finished_at IS NULL) "
            "OR (status = 'running' AND phase IS NOT NULL AND started_at IS NOT NULL "
            "AND finished_at IS NULL) OR (status IN ('completed', 'failed') AND phase IS NULL "
            "AND started_at IS NOT NULL AND finished_at IS NOT NULL)",
            name="ck_maintenance_runs_lifecycle",
        ),
        sa.CheckConstraint(
            "(status IN ('pending', 'running') AND active_slot = 1) OR "
            "(status IN ('completed', 'failed') AND active_slot IS NULL)",
            name="ck_maintenance_runs_active_slot",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("active_slot", name="uq_maintenance_runs_active_slot"),
    )
    op.create_index(
        op.f("ix_maintenance_runs_requested_by_user_id"),
        "maintenance_runs",
        ["requested_by_user_id"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_maintenance_runs_requested_by_user_id"), table_name="maintenance_runs")
    op.drop_table("maintenance_runs")
