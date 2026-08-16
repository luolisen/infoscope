"""add ask research bridge

Revision ID: 20260816_0013
Revises: 20260816_0012
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260816_0013"
down_revision: str | None = "20260816_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_ask_requests_stage", "ask_requests", type_="check")
    op.create_check_constraint(
        "ck_ask_requests_stage",
        "ask_requests",
        "stage IN ('comparing', 'awaiting_research', 'awaiting_reconciliation', 'finalizing')",
    )
    op.create_table(
        "ask_research_bridges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ask_request_id", sa.Uuid(), nullable=False),
        sa.Column("comparison_artifact_id", sa.Uuid(), nullable=False),
        sa.Column("research_request_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
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
            name="ck_ask_research_bridges_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0", name="ck_ask_research_bridges_attempt_count"
        ),
        sa.CheckConstraint(
            "max_attempts > 0", name="ck_ask_research_bridges_max_attempts"
        ),
        sa.ForeignKeyConstraint(
            ["ask_request_id"], ["ask_requests.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["comparison_artifact_id"],
            ["ask_comparison_artifacts.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["research_request_id"], ["research_requests.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ask_request_id", name="uq_ask_research_bridges_request"),
        sa.UniqueConstraint(
            "comparison_artifact_id", name="uq_ask_research_bridges_comparison_artifact"
        ),
        sa.UniqueConstraint(
            "research_request_id", name="uq_ask_research_bridges_research_request"
        ),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_ask_research_bridges_idempotency_key"
        ),
    )
    for column in (
        "ask_request_id",
        "comparison_artifact_id",
        "research_request_id",
    ):
        op.create_index(
            op.f(f"ix_ask_research_bridges_{column}"),
            "ask_research_bridges",
            [column],
        )
    op.create_table(
        "ask_research_artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("bridge_id", sa.Uuid(), nullable=False),
        sa.Column("ask_request_id", sa.Uuid(), nullable=False),
        sa.Column("comparison_artifact_id", sa.Uuid(), nullable=False),
        sa.Column("research_request_id", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["bridge_id"], ["ask_research_bridges.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["ask_request_id"], ["ask_requests.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["comparison_artifact_id"],
            ["ask_comparison_artifacts.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["research_request_id"], ["research_requests.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bridge_id", name="uq_ask_research_artifacts_bridge"),
        sa.UniqueConstraint("ask_request_id", name="uq_ask_research_artifacts_request"),
        sa.UniqueConstraint(
            "comparison_artifact_id", name="uq_ask_research_artifacts_comparison_artifact"
        ),
        sa.UniqueConstraint(
            "research_request_id", name="uq_ask_research_artifacts_research_request"
        ),
    )
    for column in (
        "bridge_id",
        "ask_request_id",
        "comparison_artifact_id",
        "research_request_id",
    ):
        op.create_index(
            op.f(f"ix_ask_research_artifacts_{column}"),
            "ask_research_artifacts",
            [column],
        )


def downgrade() -> None:
    op.drop_table("ask_research_artifacts")
    op.drop_table("ask_research_bridges")
    op.drop_constraint("ck_ask_requests_stage", "ask_requests", type_="check")
    op.create_check_constraint(
        "ck_ask_requests_stage",
        "ask_requests",
        "stage IN ('comparing', 'awaiting_research', 'finalizing')",
    )
