"""add acquisition pipeline schema

Revision ID: 20260816_0003
Revises: 20260816_0002
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260816_0003"
down_revision: str | None = "20260816_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "raw_information",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_key", sa.String(length=512), nullable=False),
        sa.Column("source_visibility", sa.String(length=16), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_text", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("collector_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "normalization_status",
            sa.String(length=16),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("normalization_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error_code", sa.String(length=128), nullable=True),
        sa.Column("normalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "normalization_attempts >= 0", name="ck_raw_information_normalization_attempts"
        ),
        sa.CheckConstraint(
            "normalization_status IN ('pending', 'processing', 'succeeded', 'failed')",
            name="ck_raw_information_normalization_status",
        ),
        sa.CheckConstraint(
            "source_visibility IN ('public', 'private')",
            name="ck_raw_information_source_visibility",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_type", "source_key", name="uq_raw_information_source"),
    )
    op.create_index(
        "ix_raw_information_acquisition_cursor",
        "raw_information",
        ["acquired_at", "id"],
    )
    op.create_index(
        "ix_raw_information_normalization_cursor",
        "raw_information",
        ["normalization_status", "acquired_at", "id"],
    )

    op.create_table(
        "signals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("raw_information_id", sa.Uuid(), nullable=False),
        sa.Column("signal_index", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("evidence_visibility", sa.String(length=24), nullable=False),
        sa.Column("public_provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("duplicate_of_signal_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "evidence_visibility IN ('public', 'private_sanitized')",
            name="ck_signals_evidence_visibility",
        ),
        sa.CheckConstraint("signal_index >= 0", name="ck_signals_signal_index"),
        sa.ForeignKeyConstraint(["duplicate_of_signal_id"], ["signals.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["raw_information_id"], ["raw_information.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "raw_information_id", "signal_index", name="uq_signals_raw_information_index"
        ),
    )
    op.create_index("ix_signals_content_hash", "signals", ["content_hash"])
    op.create_index(
        op.f("ix_signals_duplicate_of_signal_id"),
        "signals",
        ["duplicate_of_signal_id"],
    )
    op.create_index(op.f("ix_signals_raw_information_id"), "signals", ["raw_information_id"])

    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pipeline_name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lower_cursor_acquired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lower_cursor_raw_id", sa.Uuid(), nullable=True),
        sa.Column("upper_cursor_acquired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("upper_cursor_raw_id", sa.Uuid(), nullable=True),
        sa.Column("attempt", sa.Integer(), server_default="1", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("attempt > 0", name="ck_pipeline_runs_attempt"),
        sa.CheckConstraint(
            "(lower_cursor_acquired_at IS NULL) = (lower_cursor_raw_id IS NULL)",
            name="ck_pipeline_runs_lower_cursor_pair",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed')",
            name="ck_pipeline_runs_status",
        ),
        sa.CheckConstraint(
            "(upper_cursor_acquired_at IS NULL) = (upper_cursor_raw_id IS NULL)",
            name="ck_pipeline_runs_upper_cursor_pair",
        ),
        sa.CheckConstraint(
            "window_end = window_start + interval '1 hour'",
            name="ck_pipeline_runs_window",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_pipeline_runs_pipeline_status",
        "pipeline_runs",
        ["pipeline_name", "status"],
    )
    op.create_index(
        "ix_pipeline_runs_pipeline_window",
        "pipeline_runs",
        ["pipeline_name", "window_start"],
    )

    op.create_table(
        "pipeline_checkpoints",
        sa.Column("pipeline_name", sa.String(length=128), nullable=False),
        sa.Column("last_acquired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_raw_id", sa.Uuid(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(last_acquired_at IS NULL) = (last_raw_id IS NULL)",
            name="ck_pipeline_checkpoints_cursor_pair",
        ),
        sa.PrimaryKeyConstraint("pipeline_name"),
    )


def downgrade() -> None:
    op.drop_table("pipeline_checkpoints")
    op.drop_index("ix_pipeline_runs_pipeline_window", table_name="pipeline_runs")
    op.drop_index("ix_pipeline_runs_pipeline_status", table_name="pipeline_runs")
    op.drop_table("pipeline_runs")
    op.drop_index(op.f("ix_signals_raw_information_id"), table_name="signals")
    op.drop_index(op.f("ix_signals_duplicate_of_signal_id"), table_name="signals")
    op.drop_index("ix_signals_content_hash", table_name="signals")
    op.drop_table("signals")
    op.drop_index("ix_raw_information_normalization_cursor", table_name="raw_information")
    op.drop_index("ix_raw_information_acquisition_cursor", table_name="raw_information")
    op.drop_table("raw_information")
