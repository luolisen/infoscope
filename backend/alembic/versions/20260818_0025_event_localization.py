"""add event localization projection

Revision ID: 20260818_0025
Revises: 20260818_0024
Create Date: 2026-08-18 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260818_0025"
down_revision: str | None = "20260818_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "event_localization_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("locale", sa.String(length=16), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("active_slot", sa.SmallInteger(), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("batch_size", sa.SmallInteger(), nullable=False),
        sa.Column("batch_concurrency", sa.SmallInteger(), nullable=False),
        sa.Column("total_event_count", sa.Integer(), nullable=False),
        sa.Column("batch_count", sa.Integer(), nullable=False),
        sa.Column("completed_batch_count", sa.Integer(), nullable=False),
        sa.Column("failed_batch_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("token_usage", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("locale = 'zh-CN'", name="ck_event_localization_runs_locale"),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_event_localization_runs_status",
        ),
        sa.CheckConstraint(
            "(status IN ('pending', 'running') AND active_slot = 1) OR "
            "(status IN ('completed', 'failed') AND active_slot IS NULL)",
            name="ck_event_localization_runs_active_slot",
        ),
        sa.CheckConstraint(
            "total_event_count >= 0 AND batch_count >= 0 AND completed_batch_count >= 0 "
            "AND failed_batch_count >= 0 AND completed_batch_count + failed_batch_count "
            "<= batch_count",
            name="ck_event_localization_runs_counts",
        ),
        sa.CheckConstraint(
            "batch_size BETWEEN 1 AND 10", name="ck_event_localization_runs_batch_size"
        ),
        sa.CheckConstraint(
            "batch_concurrency BETWEEN 1 AND 3", name="ck_event_localization_runs_concurrency"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("locale", "active_slot", name="uq_event_localization_runs_active"),
        sa.UniqueConstraint("locale", "input_hash", name="uq_event_localization_runs_input"),
    )
    op.create_table(
        "event_localization_artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("locale", sa.String(length=16), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("output_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("token_usage", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("locale = 'zh-CN'", name="ck_event_localization_artifacts_locale"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("locale", "input_hash", name="uq_event_localization_artifacts_input"),
    )
    op.create_table(
        "event_localization_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("batch_index", sa.Integer(), nullable=False),
        sa.Column("event_ids", postgresql.ARRAY(sa.Uuid()), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_event_localization_batches_status",
        ),
        sa.CheckConstraint("batch_index >= 0", name="ck_event_localization_batches_index"),
        sa.CheckConstraint(
            "attempt_count >= 0 AND max_attempts > 0",
            name="ck_event_localization_batches_attempts",
        ),
        sa.CheckConstraint(
            "cardinality(event_ids) BETWEEN 1 AND 10",
            name="ck_event_localization_batches_event_count",
        ),
        sa.CheckConstraint(
            "(status = 'completed' AND artifact_id IS NOT NULL) OR "
            "(status != 'completed' AND artifact_id IS NULL)",
            name="ck_event_localization_batches_artifact",
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"], ["event_localization_artifacts.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["run_id"], ["event_localization_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "batch_index", name="uq_event_localization_batches_position"),
    )
    op.create_index(
        op.f("ix_event_localization_batches_run_id"),
        "event_localization_batches",
        ["run_id"],
        unique=False,
    )
    op.create_table(
        "event_localizations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("locale", sa.String(length=16), nullable=False),
        sa.Column("source_artifact_id", sa.Uuid(), nullable=False),
        sa.Column("event_input_hash", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("overview", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("locale = 'zh-CN'", name="ck_event_localizations_locale"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_artifact_id"], ["event_localization_artifacts.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "locale", name="uq_event_localizations_event_locale"),
    )
    op.create_index(
        op.f("ix_event_localizations_event_id"), "event_localizations", ["event_id"], unique=False
    )
    op.create_index(
        op.f("ix_event_localizations_source_artifact_id"),
        "event_localizations",
        ["source_artifact_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_event_localizations_source_artifact_id"), table_name="event_localizations"
    )
    op.drop_index(op.f("ix_event_localizations_event_id"), table_name="event_localizations")
    op.drop_table("event_localizations")
    op.drop_index(
        op.f("ix_event_localization_batches_run_id"), table_name="event_localization_batches"
    )
    op.drop_table("event_localization_batches")
    op.drop_table("event_localization_artifacts")
    op.drop_table("event_localization_runs")
