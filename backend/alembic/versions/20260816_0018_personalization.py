"""add personalization snapshots

Revision ID: 20260816_0018
Revises: 20260816_0017
Create Date: 2026-08-16 20:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260816_0018"
down_revision: str | None = "20260816_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "personalization_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("profile_hash", sa.String(64), nullable=False),
        sa.Column("captured_update_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("active_slot", sa.SmallInteger(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(128), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('pending','running','completed','failed')", name="ck_personalization_runs_status"),
        sa.CheckConstraint("(status IN ('pending','running') AND active_slot = 1) OR (status IN ('completed','failed') AND active_slot IS NULL)", name="ck_personalization_runs_active_slot"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_personalization_runs_attempt_count"),
        sa.CheckConstraint("max_attempts > 0", name="ck_personalization_runs_max_attempts"),
        sa.CheckConstraint("input_hash ~ '^[0-9a-f]{64}$'", name="ck_personalization_runs_input_hash"),
        sa.CheckConstraint("profile_hash ~ '^[0-9a-f]{64}$'", name="ck_personalization_runs_profile_hash"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_personalization_runs_idempotency_key"),
        sa.UniqueConstraint("id", "user_id", name="uq_personalization_runs_id_user"),
        sa.UniqueConstraint("user_id", "input_hash", name="uq_personalization_runs_user_input"),
        sa.UniqueConstraint("user_id", "active_slot", name="uq_personalization_runs_user_active"),
    )
    op.create_index(op.f("ix_personalization_runs_user_id"), "personalization_runs", ["user_id"])
    op.create_table(
        "personalization_artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_run_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_kind", sa.String(32), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("input_payload", postgresql.JSONB(), nullable=False),
        sa.Column("output_payload", postgresql.JSONB(), nullable=False),
        sa.Column("provider", sa.String(64), nullable=True),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("token_usage", postgresql.JSONB(), nullable=True),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_information_count", sa.Integer(), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("relevant_event_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("artifact_kind IN ('model','deterministic_empty')", name="ck_personalization_artifacts_kind"),
        sa.CheckConstraint("input_hash ~ '^[0-9a-f]{64}$'", name="ck_personalization_artifacts_input_hash"),
        sa.CheckConstraint("window_started_at < window_ended_at", name="ck_personalization_artifacts_window"),
        sa.CheckConstraint("raw_information_count >= 0 AND event_count >= 0 AND relevant_event_count >= 0 AND relevant_event_count <= event_count", name="ck_personalization_artifacts_counts"),
        sa.CheckConstraint("(artifact_kind = 'model' AND provider IS NOT NULL AND model IS NOT NULL AND token_usage IS NOT NULL) OR (artifact_kind = 'deterministic_empty' AND provider IS NULL AND model IS NULL AND token_usage IS NULL AND event_count = 0 AND relevant_event_count = 0)", name="ck_personalization_artifacts_metadata"),
        sa.ForeignKeyConstraint(["created_by_run_id", "user_id"], ["personalization_runs.id", "personalization_runs.user_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("created_by_run_id", name="uq_personalization_artifacts_run"),
        sa.UniqueConstraint("user_id", "input_hash", name="uq_personalization_artifacts_user_input"),
        sa.UniqueConstraint("id", "user_id", name="uq_personalization_artifacts_id_user"),
    )
    for column in ("user_id", "created_by_run_id"):
        op.create_index(op.f(f"ix_personalization_artifacts_{column}"), "personalization_artifacts", [column])
    op.create_table(
        "personalized_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("source_base_analysis_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_position", sa.Integer(), nullable=False),
        sa.Column("relevant", sa.Boolean(), nullable=False),
        sa.Column("priority", sa.String(16), nullable=False),
        sa.Column("snapshot_title", sa.String(512), nullable=False),
        sa.Column("snapshot_overview", sa.Text(), nullable=False),
        sa.Column("snapshot_state", sa.String(24), nullable=False),
        sa.Column("snapshot_display_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot_event_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot_topics", postgresql.JSONB(), nullable=False),
        sa.Column("snapshot_new_claim_count", sa.Integer(), nullable=False),
        sa.Column("snapshot_conflict_count", sa.Integer(), nullable=False),
        sa.Column("why_it_matters", sa.Text(), nullable=True),
        sa.Column("personalized_angle", sa.Text(), nullable=True),
        sa.Column("matched_scope_ids", postgresql.ARRAY(sa.String(32)), nullable=False),
        sa.Column("matched_focus_ids", postgresql.ARRAY(sa.String(32)), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("snapshot_position >= 0", name="ck_personalized_events_position"),
        sa.CheckConstraint("snapshot_new_claim_count >= 0 AND snapshot_conflict_count >= 0", name="ck_personalized_events_counts"),
        sa.CheckConstraint("priority IN ('critical','high','normal','low')", name="ck_personalized_events_priority"),
        sa.CheckConstraint("snapshot_state IN ('developing','confirmed','conflicting','cooling')", name="ck_personalized_events_state"),
        sa.CheckConstraint("(relevant AND why_it_matters IS NOT NULL AND personalized_angle IS NOT NULL AND cardinality(matched_scope_ids) > 0 AND cardinality(matched_focus_ids) > 0) OR (NOT relevant AND why_it_matters IS NULL AND personalized_angle IS NULL AND cardinality(matched_scope_ids) = 0 AND cardinality(matched_focus_ids) = 0)", name="ck_personalized_events_relevance"),
        sa.ForeignKeyConstraint(["artifact_id", "user_id"], ["personalization_artifacts.id", "personalization_artifacts.user_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_base_analysis_id"], ["base_analyses.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("artifact_id", "event_id", name="uq_personalized_events_artifact_event"),
        sa.UniqueConstraint("artifact_id", "snapshot_position", name="uq_personalized_events_artifact_position"),
    )
    for column in ("artifact_id", "user_id", "event_id", "source_base_analysis_id"):
        op.create_index(op.f(f"ix_personalized_events_{column}"), "personalized_events", [column])
    op.create_index("ix_personalized_events_artifact_visible_order", "personalized_events", ["artifact_id", "relevant", sa.text("snapshot_display_time DESC"), "event_id"])


def downgrade() -> None:
    op.drop_table("personalized_events")
    op.drop_table("personalization_artifacts")
    op.drop_table("personalization_runs")
