"""add a local display name without replacing internal auth identity

Revision ID: 20260819_0029
Revises: 20260818_0028
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260819_0029"
down_revision: str | None = "20260818_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("display_name", sa.String(length=64), nullable=False, server_default=""),
    )
    op.execute("UPDATE users SET display_name = username WHERE display_name = ''")


def downgrade() -> None:
    op.drop_column("users", "display_name")
