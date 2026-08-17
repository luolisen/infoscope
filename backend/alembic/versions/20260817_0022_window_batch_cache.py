"""add resumable window analysis batch cache

Revision ID: 20260817_0022
Revises: 20260817_0021
Create Date: 2026-08-17 15:40:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260817_0022"
down_revision: str | None = "20260817_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "window_analysis_batch_cache",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("token_usage", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "input_hash ~ '^[0-9a-f]{64}$'",
            name="ck_window_analysis_batch_cache_input_hash",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "input_hash", name="uq_window_analysis_batch_cache_input_hash"
        ),
    )


def downgrade() -> None:
    op.drop_table("window_analysis_batch_cache")
