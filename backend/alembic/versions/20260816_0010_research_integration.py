"""add research integration

Revision ID: 20260816_0010
Revises: 20260816_0009
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260816_0010"
down_revision: str | None = "20260816_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("trigger", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("request_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "trigger IN ('ask_missing_fact', 'backwrite_enrichment')",
            name="ck_research_requests_trigger",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'partial', 'failed')",
            name="ck_research_requests_status",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_research_requests_attempt_count"),
        sa.CheckConstraint("max_attempts > 0", name="ck_research_requests_max_attempts"),
        sa.CheckConstraint("input_hash ~ '^[0-9a-f]{64}$'", name="ck_research_requests_input_hash"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_research_requests_idempotency_key"),
    )
    op.create_table(
        "research_request_events",
        sa.Column("research_request_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["research_request_id"], ["research_requests.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("research_request_id", "event_id"),
    )
    op.create_table(
        "research_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("research_request_id", sa.Uuid(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'partial', 'failed')",
            name="ck_research_runs_status",
        ),
        sa.CheckConstraint("attempt > 0", name="ck_research_runs_attempt"),
        sa.ForeignKeyConstraint(
            ["research_request_id"], ["research_requests.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "research_request_id", "attempt", name="uq_research_runs_request_attempt"
        ),
    )
    op.create_index(op.f("ix_research_runs_research_request_id"), "research_runs", ["research_request_id"])
    op.create_table(
        "research_discovery_artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("research_request_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_run_id", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("runtime", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("token_usage", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("input_hash ~ '^[0-9a-f]{64}$'", name="ck_research_discovery_input_hash"),
        sa.ForeignKeyConstraint(["created_by_run_id"], ["research_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["research_request_id"], ["research_requests.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("research_request_id", name="uq_research_discovery_request"),
    )
    op.create_index(
        op.f("ix_research_discovery_artifacts_research_request_id"),
        "research_discovery_artifacts",
        ["research_request_id"],
    )
    op.create_index(
        op.f("ix_research_discovery_artifacts_created_by_run_id"),
        "research_discovery_artifacts",
        ["created_by_run_id"],
    )
    op.create_table(
        "research_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("research_request_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_index", sa.Integer(), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("canonical_url_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("raw_information_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("candidate_index >= 0", name="ck_research_sources_candidate_index"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_research_sources_attempt_count"),
        sa.CheckConstraint(
            "source_kind IN ('web_page', 'github_document')",
            name="ck_research_sources_kind",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed')",
            name="ck_research_sources_status",
        ),
        sa.CheckConstraint(
            "canonical_url_hash ~ '^[0-9a-f]{64}$'",
            name="ck_research_sources_url_hash",
        ),
        sa.ForeignKeyConstraint(
            ["raw_information_id"], ["raw_information.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["research_request_id"], ["research_requests.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "research_request_id", "candidate_index", name="uq_research_sources_index"
        ),
        sa.UniqueConstraint(
            "research_request_id", "canonical_url_hash", name="uq_research_sources_url"
        ),
    )
    op.create_index(op.f("ix_research_sources_research_request_id"), "research_sources", ["research_request_id"])
    op.create_index(op.f("ix_research_sources_raw_information_id"), "research_sources", ["raw_information_id"])


def downgrade() -> None:
    op.drop_table("research_sources")
    op.drop_table("research_discovery_artifacts")
    op.drop_table("research_runs")
    op.drop_table("research_request_events")
    op.drop_table("research_requests")
