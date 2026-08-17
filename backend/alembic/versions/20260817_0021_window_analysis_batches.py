"""support multiple window analysis artifacts per run

Revision ID: 20260817_0021
Revises: 20260816_0020
Create Date: 2026-08-17 02:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260817_0021"
down_revision: str | None = "20260816_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pipeline_artifacts",
        sa.Column("artifact_key", sa.String(length=64), server_default="default", nullable=False),
    )
    op.drop_constraint(
        "uq_pipeline_artifacts_run_type", "pipeline_artifacts", type_="unique"
    )
    op.create_unique_constraint(
        "uq_pipeline_artifacts_run_type",
        "pipeline_artifacts",
        ["pipeline_run_id", "artifact_type", "artifact_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_pipeline_artifacts_run_type", "pipeline_artifacts", type_="unique"
    )
    op.create_unique_constraint(
        "uq_pipeline_artifacts_run_type",
        "pipeline_artifacts",
        ["pipeline_run_id", "artifact_type"],
    )
    op.drop_column("pipeline_artifacts", "artifact_key")
