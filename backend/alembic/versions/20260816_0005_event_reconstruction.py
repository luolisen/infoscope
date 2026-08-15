"""add event reconstruction tables

Revision ID: 20260816_0005
Revises: 20260816_0004
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260816_0005"
down_revision: str | None = "20260816_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("overview", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("display_time", sa.DateTime(timezone=True), nullable=False),
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
            "state IN ('developing', 'confirmed', 'conflicting', 'cooling')",
            name="ck_events_state",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "event_signals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("signal_id", sa.Uuid(), nullable=False),
        sa.Column("attached_by_pipeline_run_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["attached_by_pipeline_run_id"],
            ["pipeline_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["signal_id"], ["signals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "signal_id", name="uq_event_signals_event_signal"),
    )
    op.create_index(op.f("ix_event_signals_event_id"), "event_signals", ["event_id"])
    op.create_index(
        op.f("ix_event_signals_attached_by_pipeline_run_id"),
        "event_signals",
        ["attached_by_pipeline_run_id"],
    )
    op.create_index(op.f("ix_event_signals_signal_id"), "event_signals", ["signal_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_event_signals_signal_id"), table_name="event_signals")
    op.drop_index(
        op.f("ix_event_signals_attached_by_pipeline_run_id"),
        table_name="event_signals",
    )
    op.drop_index(op.f("ix_event_signals_event_id"), table_name="event_signals")
    op.drop_table("event_signals")
    op.drop_table("events")
