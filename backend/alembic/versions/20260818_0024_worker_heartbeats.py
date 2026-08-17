"""add worker heartbeats

Revision ID: 20260818_0024
Revises: 20260817_0023
Create Date: 2026-08-18 09:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260818_0024"
down_revision: str | None = "20260817_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "worker_heartbeats",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("process_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "heartbeat_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("role = 'queue'", name="ck_worker_heartbeats_role"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_worker_heartbeats_heartbeat_at"),
        "worker_heartbeats",
        ["heartbeat_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_worker_heartbeats_heartbeat_at"), table_name="worker_heartbeats")
    op.drop_table("worker_heartbeats")
