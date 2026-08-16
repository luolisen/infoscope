"""add ask finalization

Revision ID: 20260816_0015
Revises: 20260816_0014
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260816_0015"
down_revision: str | None = "20260816_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ask_finalizations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ask_request_id", sa.Uuid(), nullable=False),
        sa.Column("source_comparison_artifact_id", sa.Uuid(), nullable=False),
        sa.Column("source_reconciliation_artifact_id", sa.Uuid(), nullable=True),
        sa.Column("finalization_kind", sa.String(length=32), nullable=False),
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
            "finalization_kind IN ('direct_reuse', 'researched_model')",
            name="ck_ask_finalizations_kind",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_ask_finalizations_status",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_ask_finalizations_attempt_count"),
        sa.CheckConstraint("max_attempts > 0", name="ck_ask_finalizations_max_attempts"),
        sa.CheckConstraint(
            "input_hash IS NULL OR input_hash ~ '^[0-9a-f]{64}$'",
            name="ck_ask_finalizations_input_hash",
        ),
        sa.CheckConstraint(
            "(finalization_kind = 'direct_reuse' AND "
            "source_reconciliation_artifact_id IS NULL) OR "
            "(finalization_kind = 'researched_model' AND "
            "source_reconciliation_artifact_id IS NOT NULL)",
            name="ck_ask_finalizations_source_kind",
        ),
        sa.ForeignKeyConstraint(["ask_request_id"], ["ask_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_comparison_artifact_id"], ["ask_comparison_artifacts.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_reconciliation_artifact_id"],
            ["ask_event_reconciliation_artifacts.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ask_request_id", name="uq_ask_finalizations_request"),
        sa.UniqueConstraint(
            "source_comparison_artifact_id", name="uq_ask_finalizations_comparison_source"
        ),
        sa.UniqueConstraint(
            "source_reconciliation_artifact_id", name="uq_ask_finalizations_reconciliation_source"
        ),
    )
    for column in (
        "ask_request_id",
        "source_comparison_artifact_id",
        "source_reconciliation_artifact_id",
    ):
        op.create_index(op.f(f"ix_ask_finalizations_{column}"), "ask_finalizations", [column])

    op.create_table(
        "ask_finalization_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("finalization_id", sa.Uuid(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("attempt > 0", name="ck_ask_finalization_runs_attempt"),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed')", name="ck_ask_finalization_runs_status"
        ),
        sa.ForeignKeyConstraint(["finalization_id"], ["ask_finalizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("finalization_id", "attempt", name="uq_ask_finalization_runs_attempt"),
    )
    op.create_index(
        op.f("ix_ask_finalization_runs_finalization_id"),
        "ask_finalization_runs",
        ["finalization_id"],
    )

    op.create_table(
        "ask_final_artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("finalization_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_run_id", sa.Uuid(), nullable=False),
        sa.Column("ask_request_id", sa.Uuid(), nullable=False),
        sa.Column("finalization_kind", sa.String(length=32), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=True),
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
            "finalization_kind IN ('direct_reuse', 'researched_model')",
            name="ck_ask_final_artifacts_kind",
        ),
        sa.CheckConstraint(
            "input_hash IS NULL OR input_hash ~ '^[0-9a-f]{64}$'",
            name="ck_ask_final_artifacts_input_hash",
        ),
        sa.CheckConstraint(
            "(finalization_kind = 'direct_reuse' AND provider IS NULL AND "
            "model IS NULL AND token_usage IS NULL) OR "
            "(finalization_kind = 'researched_model' AND provider IS NOT NULL AND "
            "model IS NOT NULL AND token_usage IS NOT NULL)",
            name="ck_ask_final_artifacts_model_metadata",
        ),
        sa.ForeignKeyConstraint(["finalization_id"], ["ask_finalizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_run_id"], ["ask_finalization_runs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["ask_request_id"], ["ask_requests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("finalization_id", name="uq_ask_final_artifacts_finalization"),
        sa.UniqueConstraint("created_by_run_id", name="uq_ask_final_artifacts_run"),
        sa.UniqueConstraint("ask_request_id", name="uq_ask_final_artifacts_request"),
    )
    for column in ("finalization_id", "created_by_run_id", "ask_request_id"):
        op.create_index(op.f(f"ix_ask_final_artifacts_{column}"), "ask_final_artifacts", [column])


def downgrade() -> None:
    op.drop_table("ask_final_artifacts")
    op.drop_table("ask_finalization_runs")
    op.drop_table("ask_finalizations")
