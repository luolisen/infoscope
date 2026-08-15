"""add onboarding and scope selections

Revision ID: 20260816_0002
Revises: 20260816_0001
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260816_0002"
down_revision: str | None = "20260816_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    empty_array = sa.text("'{}'::character varying[]")
    op.add_column(
        "users",
        sa.Column(
            "scope_ids",
            postgresql.ARRAY(sa.String(length=32)),
            server_default=empty_array,
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "investment_market_ids",
            postgresql.ARRAY(sa.String(length=32)),
            server_default=empty_array,
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "focus_ids",
            postgresql.ARRAY(sa.String(length=32)),
            server_default=empty_array,
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column("personalization_update_requested_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "personalization_update_requested_at")
    op.drop_column("users", "focus_ids")
    op.drop_column("users", "investment_market_ids")
    op.drop_column("users", "scope_ids")
