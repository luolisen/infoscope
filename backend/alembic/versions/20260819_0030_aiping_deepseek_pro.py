"""allow AI Ping DeepSeek V4 Pro preferences

Revision ID: 20260819_0030
Revises: 20260819_0029
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260819_0030"
down_revision: str | None = "20260819_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_user_model_preferences_source_model",
        "user_model_preferences",
        type_="check",
    )
    op.create_check_constraint(
        "ck_user_model_preferences_source_model",
        "user_model_preferences",
        "(source_id = 'deepseek_official' AND model_id IN "
        "('deepseek-v4-flash', 'deepseek-v4-pro')) OR "
        "(source_id = 'gpt_5_5' AND model_id = 'gpt-5.5') OR "
        "(source_id = 'ai_ping' AND model_id IN "
        "('DeepSeek-V4-Flash-0731', 'DeepSeek-V4-Pro', 'Kimi-K3', 'Qwen3.8-Max'))",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_user_model_preferences_source_model",
        "user_model_preferences",
        type_="check",
    )
    op.create_check_constraint(
        "ck_user_model_preferences_source_model",
        "user_model_preferences",
        "(source_id = 'deepseek_official' AND model_id IN "
        "('deepseek-v4-flash', 'deepseek-v4-pro')) OR "
        "(source_id = 'gpt_5_5' AND model_id = 'gpt-5.5') OR "
        "(source_id = 'ai_ping' AND model_id IN "
        "('DeepSeek-V4-Flash-0731', 'Kimi-K3', 'Qwen3.8-Max'))",
    )
