"""add grounded brief snapshots

Revision ID: 20260816_0019
Revises: 20260816_0018
Create Date: 2026-08-16 22:15:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260816_0019"
down_revision: str | None = "20260816_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_personalized_events_source_scope",
        "personalized_events",
        ["id", "artifact_id", "user_id", "event_id"],
    )
    op.create_table(
        "brief_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("source_personalization_artifact_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("active_slot", sa.SmallInteger(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(128), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('pending','running','completed','failed')", name="ck_brief_runs_status"
        ),
        sa.CheckConstraint(
            "(status IN ('pending','running') AND active_slot = 1) OR (status IN ('completed','failed') AND active_slot IS NULL)",
            name="ck_brief_runs_active_slot",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_brief_runs_attempt_count"),
        sa.CheckConstraint("max_attempts > 0", name="ck_brief_runs_max_attempts"),
        sa.CheckConstraint("input_hash ~ '^[0-9a-f]{64}$'", name="ck_brief_runs_input_hash"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_personalization_artifact_id", "user_id"],
            ["personalization_artifacts.id", "personalization_artifacts.user_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_brief_runs_idempotency_key"),
        sa.UniqueConstraint("id", "user_id", name="uq_brief_runs_id_user"),
        sa.UniqueConstraint("source_personalization_artifact_id", name="uq_brief_runs_source"),
        sa.UniqueConstraint("user_id", "input_hash", name="uq_brief_runs_user_input"),
        sa.UniqueConstraint("user_id", "active_slot", name="uq_brief_runs_user_active"),
    )
    for column in ("user_id", "source_personalization_artifact_id"):
        op.create_index(op.f(f"ix_brief_runs_{column}"), "brief_runs", [column])
    op.create_table(
        "brief_artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_run_id", sa.Uuid(), nullable=False),
        sa.Column("source_personalization_artifact_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_kind", sa.String(32), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("input_payload", postgresql.JSONB(), nullable=False),
        sa.Column("output_payload", postgresql.JSONB(), nullable=False),
        sa.Column("provider", sa.String(64), nullable=True),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("token_usage", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "artifact_kind IN ('model','deterministic_empty')", name="ck_brief_artifacts_kind"
        ),
        sa.CheckConstraint("input_hash ~ '^[0-9a-f]{64}$'", name="ck_brief_artifacts_input_hash"),
        sa.CheckConstraint(
            "(artifact_kind = 'model' AND provider IS NOT NULL AND model IS NOT NULL AND token_usage IS NOT NULL) OR (artifact_kind = 'deterministic_empty' AND provider IS NULL AND model IS NULL AND token_usage IS NULL)",
            name="ck_brief_artifacts_metadata",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_run_id", "user_id"],
            ["brief_runs.id", "brief_runs.user_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_personalization_artifact_id", "user_id"],
            ["personalization_artifacts.id", "personalization_artifacts.user_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("created_by_run_id", name="uq_brief_artifacts_run"),
        sa.UniqueConstraint("source_personalization_artifact_id", name="uq_brief_artifacts_source"),
        sa.UniqueConstraint("user_id", "input_hash", name="uq_brief_artifacts_user_input"),
        sa.UniqueConstraint(
            "id", "user_id", "source_personalization_artifact_id", name="uq_brief_artifacts_scope"
        ),
    )
    for column in ("user_id", "created_by_run_id", "source_personalization_artifact_id"):
        op.create_index(op.f(f"ix_brief_artifacts_{column}"), "brief_artifacts", [column])
    op.create_table(
        "brief_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("source_personalization_artifact_id", sa.Uuid(), nullable=False),
        sa.Column("source_personalized_event_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("snapshot_title", sa.String(512), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("why_it_matters", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("position >= 0", name="ck_brief_items_position"),
        sa.ForeignKeyConstraint(
            ["artifact_id", "user_id", "source_personalization_artifact_id"],
            [
                "brief_artifacts.id",
                "brief_artifacts.user_id",
                "brief_artifacts.source_personalization_artifact_id",
            ],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            [
                "source_personalized_event_id",
                "source_personalization_artifact_id",
                "user_id",
                "event_id",
            ],
            [
                "personalized_events.id",
                "personalized_events.artifact_id",
                "personalized_events.user_id",
                "personalized_events.event_id",
            ],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("artifact_id", "event_id", name="uq_brief_items_artifact_event"),
        sa.UniqueConstraint("artifact_id", "position", name="uq_brief_items_artifact_position"),
    )
    for column in (
        "artifact_id",
        "user_id",
        "source_personalization_artifact_id",
        "source_personalized_event_id",
        "event_id",
    ):
        op.create_index(op.f(f"ix_brief_items_{column}"), "brief_items", [column])


def downgrade() -> None:
    op.drop_table("brief_items")
    op.drop_table("brief_artifacts")
    op.drop_table("brief_runs")
    op.drop_constraint("uq_personalized_events_source_scope", "personalized_events", type_="unique")
