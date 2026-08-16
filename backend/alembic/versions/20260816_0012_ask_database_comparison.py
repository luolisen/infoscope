"""add ask database comparison

Revision ID: 20260816_0012
Revises: 20260816_0011
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260816_0012"
down_revision: str | None = "20260816_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ask_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
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
            name="ck_ask_requests_status",
        ),
        sa.CheckConstraint(
            "stage IN ('comparing', 'awaiting_research', 'finalizing')",
            name="ck_ask_requests_stage",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_ask_requests_attempt_count"),
        sa.CheckConstraint("max_attempts > 0", name="ck_ask_requests_max_attempts"),
        sa.CheckConstraint("input_hash ~ '^[0-9a-f]{64}$'", name="ck_ask_requests_input_hash"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ask_requests_user_id"), "ask_requests", ["user_id"])
    op.create_table(
        "ask_request_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ask_request_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "position >= 0 AND position < 8", name="ck_ask_request_events_position"
        ),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["ask_request_id"], ["ask_requests.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "ask_request_id", "event_id", name="uq_ask_request_events_event"
        ),
        sa.UniqueConstraint(
            "ask_request_id", "position", name="uq_ask_request_events_position"
        ),
    )
    op.create_index(
        op.f("ix_ask_request_events_ask_request_id"),
        "ask_request_events",
        ["ask_request_id"],
    )
    op.create_index(
        op.f("ix_ask_request_events_event_id"), "ask_request_events", ["event_id"]
    )
    op.create_table(
        "ask_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ask_request_id", sa.Uuid(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed')", name="ck_ask_runs_status"
        ),
        sa.CheckConstraint("attempt > 0", name="ck_ask_runs_attempt"),
        sa.ForeignKeyConstraint(
            ["ask_request_id"], ["ask_requests.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ask_request_id", "attempt", name="uq_ask_runs_request_attempt"),
    )
    op.create_index(op.f("ix_ask_runs_ask_request_id"), "ask_runs", ["ask_request_id"])
    op.create_table(
        "ask_comparison_artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ask_request_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_run_id", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "input_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column(
            "token_usage", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "input_hash ~ '^[0-9a-f]{64}$'", name="ck_ask_comparison_artifacts_input_hash"
        ),
        sa.ForeignKeyConstraint(
            ["ask_request_id"], ["ask_requests.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["created_by_run_id"], ["ask_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ask_request_id", name="uq_ask_comparison_artifacts_request"),
        sa.UniqueConstraint("created_by_run_id", name="uq_ask_comparison_artifacts_run"),
    )
    op.create_index(
        op.f("ix_ask_comparison_artifacts_ask_request_id"),
        "ask_comparison_artifacts",
        ["ask_request_id"],
    )
    op.create_index(
        op.f("ix_ask_comparison_artifacts_created_by_run_id"),
        "ask_comparison_artifacts",
        ["created_by_run_id"],
    )


def downgrade() -> None:
    op.drop_table("ask_comparison_artifacts")
    op.drop_table("ask_runs")
    op.drop_table("ask_request_events")
    op.drop_table("ask_requests")
