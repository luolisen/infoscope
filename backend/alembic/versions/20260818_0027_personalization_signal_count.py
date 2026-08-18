"""add canonical Signal count to Personalization snapshots

Revision ID: 20260818_0027
Revises: 20260818_0026
Create Date: 2026-08-18 15:45:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260818_0027"
down_revision: str | None = "20260818_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "personalization_artifacts",
        sa.Column("signal_count", sa.Integer(), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE personalization_artifacts AS artifact
            SET signal_count = (
                SELECT count(signal.id)
                FROM signals AS signal
                JOIN raw_information AS raw
                  ON raw.id = signal.raw_information_id
                WHERE signal.duplicate_of_signal_id IS NULL
                  AND raw.acquired_at >= artifact.window_started_at
                  AND raw.acquired_at < artifact.window_ended_at
            )
            """
        )
    )
    op.alter_column(
        "personalization_artifacts",
        "signal_count",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.drop_constraint(
        "ck_personalization_artifacts_counts",
        "personalization_artifacts",
        type_="check",
    )
    op.create_check_constraint(
        "ck_personalization_artifacts_counts",
        "personalization_artifacts",
        "raw_information_count >= 0 AND signal_count >= 0 AND event_count >= 0 "
        "AND relevant_event_count >= 0 AND relevant_event_count <= event_count",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_personalization_artifacts_counts",
        "personalization_artifacts",
        type_="check",
    )
    op.create_check_constraint(
        "ck_personalization_artifacts_counts",
        "personalization_artifacts",
        "raw_information_count >= 0 AND event_count >= 0 "
        "AND relevant_event_count >= 0 AND relevant_event_count <= event_count",
    )
    op.drop_column("personalization_artifacts", "signal_count")
