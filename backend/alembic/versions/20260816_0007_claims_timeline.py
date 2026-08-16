"""add claims and timeline

Revision ID: 20260816_0007
Revises: 20260816_0006
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260816_0007"
down_revision: str | None = "20260816_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_pipeline_artifacts_reconstruction_source",
        "pipeline_artifacts",
        type_="check",
    )
    op.create_check_constraint(
        "ck_pipeline_artifacts_derived_source",
        "pipeline_artifacts",
        "artifact_type NOT IN ('event_reconstruction', 'claim_extraction', "
        "'timeline_reconstruction') OR source_artifact_id IS NOT NULL",
    )
    op.create_table(
        "claims",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
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
        sa.CheckConstraint(
            "state IN ('confirmed', 'unresolved', 'conflicting', 'contradicted')",
            name="ck_claims_state",
        ),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_claims_event_id"), "claims", ["event_id"])
    op.create_table(
        "claim_signals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("signal_id", sa.Uuid(), nullable=False),
        sa.Column("attached_by_pipeline_run_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["signal_id"], ["signals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["attached_by_pipeline_run_id"], ["pipeline_runs.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("claim_id", "signal_id", name="uq_claim_signals_claim_signal"),
    )
    for column in ("claim_id", "signal_id", "attached_by_pipeline_run_id"):
        op.create_index(op.f(f"ix_claim_signals_{column}"), "claim_signals", [column])
    op.create_table(
        "timeline_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
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
    op.create_index(op.f("ix_timeline_entries_event_id"), "timeline_entries", ["event_id"])
    op.create_table(
        "timeline_claims",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("timeline_entry_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("attached_by_pipeline_run_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["timeline_entry_id"], ["timeline_entries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["attached_by_pipeline_run_id"], ["pipeline_runs.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("timeline_entry_id", "claim_id", name="uq_timeline_claims_entry_claim"),
    )
    for column in ("timeline_entry_id", "claim_id", "attached_by_pipeline_run_id"):
        op.create_index(op.f(f"ix_timeline_claims_{column}"), "timeline_claims", [column])


def downgrade() -> None:
    op.drop_table("timeline_claims")
    op.drop_table("timeline_entries")
    op.drop_table("claim_signals")
    op.drop_table("claims")
    op.execute(
        "ALTER TABLE pipeline_artifacts "
        "DROP CONSTRAINT IF EXISTS ck_pipeline_artifacts_derived_source"
    )
    op.execute(
        "ALTER TABLE pipeline_artifacts "
        "DROP CONSTRAINT IF EXISTS ck_pipeline_artifacts_reconstruction_source"
    )
    op.create_check_constraint(
        "ck_pipeline_artifacts_reconstruction_source",
        "pipeline_artifacts",
        "artifact_type != 'event_reconstruction' OR source_artifact_id IS NOT NULL",
    )
