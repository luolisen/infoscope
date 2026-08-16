"""add user event saves

Revision ID: 20260816_0020
Revises: 20260816_0019
Create Date: 2026-08-16 22:20:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260816_0020"
down_revision: str | None = "20260816_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "event_saves",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column(
            "saved_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "event_id", name="uq_event_saves_user_event"),
    )
    op.create_index(op.f("ix_event_saves_user_id"), "event_saves", ["user_id"])
    op.create_index(op.f("ix_event_saves_event_id"), "event_saves", ["event_id"])


def downgrade() -> None:
    op.drop_table("event_saves")
