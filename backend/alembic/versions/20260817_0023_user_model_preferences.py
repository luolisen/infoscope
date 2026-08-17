"""add user model preferences

Revision ID: 20260817_0023
Revises: 20260817_0022
Create Date: 2026-08-17 21:15:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260817_0023"
down_revision: str | None = "20260817_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_model_preferences",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.String(length=32), nullable=False),
        sa.Column("model_id", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "source_id IN ('deepseek_official', 'gpt_5_5', 'ai_ping')",
            name="ck_user_model_preferences_source",
        ),
        sa.CheckConstraint(
            "(source_id = 'deepseek_official' AND model_id IN "
            "('deepseek-v4-flash', 'deepseek-v4-pro')) OR "
            "(source_id = 'gpt_5_5' AND model_id = 'gpt-5.5') OR "
            "(source_id = 'ai_ping' AND model_id IN "
            "('DeepSeek-V4-Flash-0731', 'Kimi-K3', 'Qwen3.8-Max'))",
            name="ck_user_model_preferences_source_model",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("user_model_preferences")
