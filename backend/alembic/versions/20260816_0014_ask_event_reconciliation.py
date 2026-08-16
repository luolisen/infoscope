"""add ask event reconciliation

Revision ID: 20260816_0014
Revises: 20260816_0013
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260816_0014"
down_revision: str | None = "20260816_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ask_event_reconciliations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ask_request_id", sa.Uuid(), nullable=False),
        sa.Column("source_bridge_artifact_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
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
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_ask_event_reconciliations_status",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_ask_event_reconciliations_attempt_count"),
        sa.CheckConstraint("max_attempts > 0", name="ck_ask_event_reconciliations_max_attempts"),
        sa.CheckConstraint(
            "input_hash IS NULL OR input_hash ~ '^[0-9a-f]{64}$'",
            name="ck_ask_event_reconciliations_input_hash",
        ),
        sa.ForeignKeyConstraint(["ask_request_id"], ["ask_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_bridge_artifact_id"],
            ["ask_research_artifacts.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ask_request_id", name="uq_ask_event_reconciliations_request"),
        sa.UniqueConstraint(
            "source_bridge_artifact_id", name="uq_ask_event_reconciliations_source"
        ),
    )
    for column in ("ask_request_id", "source_bridge_artifact_id"):
        op.create_index(
            op.f(f"ix_ask_event_reconciliations_{column}"),
            "ask_event_reconciliations",
            [column],
        )

    op.create_table(
        "ask_event_reconciliation_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("reconciliation_id", sa.Uuid(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("attempt > 0", name="ck_ask_event_reconciliation_runs_attempt"),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="ck_ask_event_reconciliation_runs_status",
        ),
        sa.ForeignKeyConstraint(
            ["reconciliation_id"], ["ask_event_reconciliations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "reconciliation_id",
            "attempt",
            name="uq_ask_event_reconciliation_runs_attempt",
        ),
    )
    op.create_index(
        op.f("ix_ask_event_reconciliation_runs_reconciliation_id"),
        "ask_event_reconciliation_runs",
        ["reconciliation_id"],
    )

    op.alter_column("event_signals", "attached_by_pipeline_run_id", nullable=True)
    op.add_column(
        "event_signals",
        sa.Column("attached_by_ask_reconciliation_run_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_event_signals_attached_by_ask_reconciliation_run_id",
        "event_signals",
        "ask_event_reconciliation_runs",
        ["attached_by_ask_reconciliation_run_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        op.f("ix_event_signals_attached_by_ask_reconciliation_run_id"),
        "event_signals",
        ["attached_by_ask_reconciliation_run_id"],
    )
    op.create_check_constraint(
        "ck_event_signals_exactly_one_source",
        "event_signals",
        "(attached_by_pipeline_run_id IS NOT NULL) <> "
        "(attached_by_ask_reconciliation_run_id IS NOT NULL)",
    )

    op.create_table(
        "ask_event_reconciliation_artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("reconciliation_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_run_id", sa.Uuid(), nullable=False),
        sa.Column("ask_request_id", sa.Uuid(), nullable=False),
        sa.Column("source_bridge_artifact_id", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("token_usage", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "input_hash ~ '^[0-9a-f]{64}$'",
            name="ck_ask_event_reconciliation_artifacts_input_hash",
        ),
        sa.ForeignKeyConstraint(
            ["reconciliation_id"], ["ask_event_reconciliations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_run_id"],
            ["ask_event_reconciliation_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["ask_request_id"], ["ask_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_bridge_artifact_id"],
            ["ask_research_artifacts.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "reconciliation_id", name="uq_ask_event_reconciliation_artifacts_reconciliation"
        ),
        sa.UniqueConstraint("created_by_run_id", name="uq_ask_event_reconciliation_artifacts_run"),
        sa.UniqueConstraint("ask_request_id", name="uq_ask_event_reconciliation_artifacts_request"),
        sa.UniqueConstraint(
            "source_bridge_artifact_id", name="uq_ask_event_reconciliation_artifacts_source"
        ),
    )
    for column in (
        "reconciliation_id",
        "created_by_run_id",
        "ask_request_id",
        "source_bridge_artifact_id",
    ):
        op.create_index(
            op.f(f"ix_ask_event_reconciliation_artifacts_{column}"),
            "ask_event_reconciliation_artifacts",
            [column],
        )


def downgrade() -> None:
    op.drop_table("ask_event_reconciliation_artifacts")
    op.drop_constraint("ck_event_signals_exactly_one_source", "event_signals", type_="check")
    op.drop_index(
        op.f("ix_event_signals_attached_by_ask_reconciliation_run_id"),
        table_name="event_signals",
    )
    op.drop_constraint(
        "fk_event_signals_attached_by_ask_reconciliation_run_id",
        "event_signals",
        type_="foreignkey",
    )
    op.drop_column("event_signals", "attached_by_ask_reconciliation_run_id")
    op.alter_column("event_signals", "attached_by_pipeline_run_id", nullable=False)
    op.drop_table("ask_event_reconciliation_runs")
    op.drop_table("ask_event_reconciliations")
