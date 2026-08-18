"""persist the per-Ask Grok search preference

Revision ID: 20260818_0028
Revises: 20260818_0027
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260818_0028"
down_revision: str | None = "20260818_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ask_requests",
        sa.Column("grok_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("ask_requests", "grok_enabled", server_default=None)


def downgrade() -> None:
    op.drop_column("ask_requests", "grok_enabled")
