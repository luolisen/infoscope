"""add event backwrite

Revision ID: 20260816_0016
Revises: 20260816_0015
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260816_0016"
down_revision: str | None = "20260816_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "backwrite_cycles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("snapshot_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('pending', 'running', 'completed', 'partial', 'failed')",
            name="ck_backwrite_cycles_status",
        ),
        sa.CheckConstraint("input_hash ~ '^[0-9a-f]{64}$'", name="ck_backwrite_cycles_input_hash"),
        sa.CheckConstraint("item_count >= 0", name="ck_backwrite_cycles_item_count"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_backwrite_cycles_idempotency_key"),
    )
    op.create_index(op.f("ix_backwrite_cycles_user_id"), "backwrite_cycles", ["user_id"])

    op.create_table(
        "backwrite_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("cycle_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_position", sa.Integer(), nullable=False),
        sa.Column("queue_position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("research_request_id", sa.Uuid(), nullable=True),
        sa.Column("source_artifact_id", sa.Uuid(), nullable=True),
        sa.Column("input_hash", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('pending', 'researching', 'reconciling', 'completed', 'failed')",
            name="ck_backwrite_items_status",
        ),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN ('updated', 'no_change')",
            name="ck_backwrite_items_outcome",
        ),
        sa.CheckConstraint("snapshot_position >= 0", name="ck_backwrite_items_snapshot_position"),
        sa.CheckConstraint("queue_position >= 0", name="ck_backwrite_items_queue_position"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_backwrite_items_attempt_count"),
        sa.CheckConstraint("max_attempts > 0", name="ck_backwrite_items_max_attempts"),
        sa.CheckConstraint(
            "input_hash IS NULL OR input_hash ~ '^[0-9a-f]{64}$'",
            name="ck_backwrite_items_input_hash",
        ),
        sa.ForeignKeyConstraint(["cycle_id"], ["backwrite_cycles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["research_request_id"], ["research_requests.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cycle_id", "event_id", name="uq_backwrite_items_cycle_event"),
        sa.UniqueConstraint(
            "cycle_id", "snapshot_position", name="uq_backwrite_items_snapshot_position"
        ),
        sa.UniqueConstraint("cycle_id", "queue_position", name="uq_backwrite_items_queue_position"),
    )
    for column in ("cycle_id", "event_id", "research_request_id", "source_artifact_id"):
        op.create_index(op.f(f"ix_backwrite_items_{column}"), "backwrite_items", [column])

    op.create_table(
        "backwrite_reconciliation_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("attempt > 0", name="ck_backwrite_reconciliation_runs_attempt"),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="ck_backwrite_reconciliation_runs_status",
        ),
        sa.ForeignKeyConstraint(["item_id"], ["backwrite_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("item_id", "attempt", name="uq_backwrite_reconciliation_runs_attempt"),
    )
    op.create_index(
        op.f("ix_backwrite_reconciliation_runs_item_id"),
        "backwrite_reconciliation_runs",
        ["item_id"],
    )

    op.create_table(
        "backwrite_research_artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("research_request_id", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["item_id"], ["backwrite_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["research_request_id"], ["research_requests.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("item_id", name="uq_backwrite_research_artifacts_item"),
        sa.UniqueConstraint("research_request_id", name="uq_backwrite_research_artifacts_request"),
    )
    for column in ("item_id", "research_request_id"):
        op.create_index(
            op.f(f"ix_backwrite_research_artifacts_{column}"),
            "backwrite_research_artifacts",
            [column],
        )
    op.create_foreign_key(
        "fk_backwrite_items_source_artifact_id",
        "backwrite_items",
        "backwrite_research_artifacts",
        ["source_artifact_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.drop_constraint("ck_event_signals_exactly_one_source", "event_signals", type_="check")
    op.add_column(
        "event_signals",
        sa.Column("attached_by_backwrite_reconciliation_run_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_event_signals_attached_by_backwrite_reconciliation_run_id",
        "event_signals",
        "backwrite_reconciliation_runs",
        ["attached_by_backwrite_reconciliation_run_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        op.f("ix_event_signals_attached_by_backwrite_reconciliation_run_id"),
        "event_signals",
        ["attached_by_backwrite_reconciliation_run_id"],
    )
    op.create_check_constraint(
        "ck_event_signals_exactly_one_source",
        "event_signals",
        "(CASE WHEN attached_by_pipeline_run_id IS NOT NULL THEN 1 ELSE 0 END + "
        "CASE WHEN attached_by_ask_reconciliation_run_id IS NOT NULL THEN 1 ELSE 0 END + "
        "CASE WHEN attached_by_backwrite_reconciliation_run_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
    )

    op.create_table(
        "backwrite_reconciliation_artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_run_id", sa.Uuid(), nullable=False),
        sa.Column("research_request_id", sa.Uuid(), nullable=False),
        sa.Column("source_artifact_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_kind", sa.String(length=32), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("token_usage", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "artifact_kind IN ('model', 'deterministic_no_change')",
            name="ck_backwrite_reconciliation_artifacts_kind",
        ),
        sa.CheckConstraint(
            "input_hash ~ '^[0-9a-f]{64}$'",
            name="ck_backwrite_reconciliation_artifacts_input_hash",
        ),
        sa.CheckConstraint(
            "(artifact_kind = 'deterministic_no_change' AND provider IS NULL AND model IS NULL "
            "AND token_usage IS NULL) OR (artifact_kind = 'model' AND provider IS NOT NULL "
            "AND model IS NOT NULL AND token_usage IS NOT NULL)",
            name="ck_backwrite_reconciliation_artifacts_model_metadata",
        ),
        sa.ForeignKeyConstraint(["item_id"], ["backwrite_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_run_id"], ["backwrite_reconciliation_runs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["research_request_id"], ["research_requests.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_artifact_id"], ["backwrite_research_artifacts.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("item_id", name="uq_backwrite_reconciliation_artifacts_item"),
        sa.UniqueConstraint("created_by_run_id", name="uq_backwrite_reconciliation_artifacts_run"),
    )
    for column in (
        "item_id",
        "created_by_run_id",
        "research_request_id",
        "source_artifact_id",
    ):
        op.create_index(
            op.f(f"ix_backwrite_reconciliation_artifacts_{column}"),
            "backwrite_reconciliation_artifacts",
            [column],
        )


def downgrade() -> None:
    op.drop_table("backwrite_reconciliation_artifacts")
    op.drop_constraint("ck_event_signals_exactly_one_source", "event_signals", type_="check")
    op.drop_index(
        op.f("ix_event_signals_attached_by_backwrite_reconciliation_run_id"),
        table_name="event_signals",
    )
    op.drop_constraint(
        "fk_event_signals_attached_by_backwrite_reconciliation_run_id",
        "event_signals",
        type_="foreignkey",
    )
    op.drop_column("event_signals", "attached_by_backwrite_reconciliation_run_id")
    op.create_check_constraint(
        "ck_event_signals_exactly_one_source",
        "event_signals",
        "(attached_by_pipeline_run_id IS NOT NULL) <> "
        "(attached_by_ask_reconciliation_run_id IS NOT NULL)",
    )
    op.drop_constraint(
        "fk_backwrite_items_source_artifact_id", "backwrite_items", type_="foreignkey"
    )
    op.drop_table("backwrite_research_artifacts")
    op.drop_table("backwrite_reconciliation_runs")
    op.drop_table("backwrite_items")
    op.drop_table("backwrite_cycles")
