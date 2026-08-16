"""add base analysis

Revision ID: 20260816_0009
Revises: 20260816_0008
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260816_0009"
down_revision: str | None = "20260816_0008"
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
        "'timeline_reconstruction', 'conflict_analysis', 'base_analysis') "
        "OR source_artifact_id IS NOT NULL",
    )
    op.create_table(
        "base_analyses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("source_artifact_id", sa.Uuid(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("importance", sa.String(length=16), nullable=False),
        sa.Column("topics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("entities", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
            "importance IN ('low', 'medium', 'high', 'critical')",
            name="ck_base_analyses_importance",
        ),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_artifact_id"], ["pipeline_artifacts.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", name="uq_base_analyses_event"),
    )
    op.create_index(op.f("ix_base_analyses_event_id"), "base_analyses", ["event_id"])
    op.create_index(
        op.f("ix_base_analyses_source_artifact_id"),
        "base_analyses",
        ["source_artifact_id"],
    )


def downgrade() -> None:
    op.drop_table("base_analyses")
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
