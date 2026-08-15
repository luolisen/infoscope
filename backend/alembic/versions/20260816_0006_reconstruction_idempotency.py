"""enforce event reconstruction source idempotency

Revision ID: 20260816_0006
Revises: 20260816_0005
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260816_0006"
down_revision: str | None = "20260816_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pipeline_artifacts",
        sa.Column("source_artifact_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_pipeline_artifacts_source_artifact_id",
        "pipeline_artifacts",
        "pipeline_artifacts",
        ["source_artifact_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.execute(
        sa.text(
            """
            UPDATE pipeline_artifacts
            SET source_artifact_id = (payload ->> 'source_artifact_id')::uuid
            WHERE artifact_type = 'event_reconstruction'
            """
        )
    )
    op.create_unique_constraint(
        "uq_pipeline_artifacts_type_source",
        "pipeline_artifacts",
        ["artifact_type", "source_artifact_id"],
    )
    op.create_check_constraint(
        "ck_pipeline_artifacts_reconstruction_source",
        "pipeline_artifacts",
        "artifact_type != 'event_reconstruction' OR source_artifact_id IS NOT NULL",
    )
    op.create_index(
        op.f("ix_pipeline_artifacts_source_artifact_id"),
        "pipeline_artifacts",
        ["source_artifact_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_pipeline_artifacts_source_artifact_id"),
        table_name="pipeline_artifacts",
    )
    op.drop_constraint(
        "ck_pipeline_artifacts_reconstruction_source",
        "pipeline_artifacts",
        type_="check",
    )
    op.drop_constraint(
        "uq_pipeline_artifacts_type_source",
        "pipeline_artifacts",
        type_="unique",
    )
    op.drop_constraint(
        "fk_pipeline_artifacts_source_artifact_id",
        "pipeline_artifacts",
        type_="foreignkey",
    )
    op.drop_column("pipeline_artifacts", "source_artifact_id")
