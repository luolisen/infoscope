"""allow a new localization run after terminal failure

Revision ID: 20260818_0026
Revises: 20260818_0025
Create Date: 2026-08-18 10:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260818_0026"
down_revision: str | None = "20260818_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_event_localization_runs_input",
        "event_localization_runs",
        type_="unique",
    )
    op.add_column(
        "event_localization_batches",
        sa.Column("artifact_reused", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "event_localization_batches",
        sa.Column(
            "token_usage",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("event_localization_batches", "token_usage")
    op.drop_column("event_localization_batches", "artifact_reused")
    op.create_unique_constraint(
        "uq_event_localization_runs_input",
        "event_localization_runs",
        ["locale", "input_hash"],
    )
