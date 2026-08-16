"""add conflict analysis

Revision ID: 20260816_0008
Revises: 20260816_0007
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260816_0008"
down_revision: str | None = "20260816_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_pipeline_artifacts_derived_source",
        "pipeline_artifacts",
        type_="check",
    )
    op.create_check_constraint(
        "ck_pipeline_artifacts_derived_source",
        "pipeline_artifacts",
        "artifact_type NOT IN ('event_reconstruction', 'claim_extraction', "
        "'timeline_reconstruction', 'conflict_analysis') OR source_artifact_id IS NOT NULL",
    )
    op.create_table(
        "conflicts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_conflicts_event_id"), "conflicts", ["event_id"])
    op.create_table(
        "conflict_claims",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conflict_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("attached_by_pipeline_run_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["conflict_id"], ["conflicts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["attached_by_pipeline_run_id"], ["pipeline_runs.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conflict_id", "claim_id", name="uq_conflict_claims_conflict_claim"),
    )
    for column in ("conflict_id", "claim_id", "attached_by_pipeline_run_id"):
        op.create_index(op.f(f"ix_conflict_claims_{column}"), "conflict_claims", [column])
    op.create_table(
        "conflict_signals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conflict_id", sa.Uuid(), nullable=False),
        sa.Column("signal_id", sa.Uuid(), nullable=False),
        sa.Column("attached_by_pipeline_run_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["conflict_id"], ["conflicts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["signal_id"], ["signals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["attached_by_pipeline_run_id"], ["pipeline_runs.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conflict_id", "signal_id", name="uq_conflict_signals_conflict_signal"),
    )
    for column in ("conflict_id", "signal_id", "attached_by_pipeline_run_id"):
        op.create_index(op.f(f"ix_conflict_signals_{column}"), "conflict_signals", [column])


def downgrade() -> None:
    op.drop_table("conflict_signals")
    op.drop_table("conflict_claims")
    op.drop_table("conflicts")
    op.drop_constraint(
        "ck_pipeline_artifacts_derived_source",
        "pipeline_artifacts",
        type_="check",
    )
    op.create_check_constraint(
        "ck_pipeline_artifacts_derived_source",
        "pipeline_artifacts",
        "artifact_type NOT IN ('event_reconstruction', 'claim_extraction', "
        "'timeline_reconstruction') OR source_artifact_id IS NOT NULL",
    )
