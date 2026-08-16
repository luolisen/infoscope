"""add privacy-safe research source audit

Revision ID: 20260816_0011
Revises: 20260816_0010
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260816_0011"
down_revision: str | None = "20260816_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "research_sources",
        sa.Column("candidate_url_hash", sa.String(length=64), nullable=True),
    )
    op.execute(
        "UPDATE research_sources "
        "SET candidate_url_hash = canonical_url_hash "
        "WHERE candidate_url_hash IS NULL"
    )
    op.alter_column("research_sources", "candidate_url_hash", nullable=False)
    op.alter_column("research_sources", "canonical_url", nullable=True)
    op.alter_column("research_sources", "canonical_url_hash", nullable=True)
    op.create_check_constraint(
        "ck_research_sources_candidate_url_hash",
        "research_sources",
        "candidate_url_hash ~ '^[0-9a-f]{64}$'",
    )
    op.execute(
        "UPDATE research_discovery_artifacts "
        "SET schema_version = 'research_discovery_audit.v1', "
        "payload = jsonb_build_object("
        "'schema_version', 'research_discovery_audit.v1', "
        "'request_id', research_request_id::text, "
        "'candidate_count', jsonb_array_length(COALESCE(payload->'candidates', '[]'::jsonb))"
        ") "
        "WHERE schema_version = 'research_discovery.v1'"
    )


def downgrade() -> None:
    op.execute("DELETE FROM research_sources WHERE canonical_url IS NULL")
    op.alter_column("research_sources", "canonical_url_hash", nullable=False)
    op.alter_column("research_sources", "canonical_url", nullable=False)
    op.drop_constraint(
        "ck_research_sources_candidate_url_hash",
        "research_sources",
        type_="check",
    )
    op.drop_column("research_sources", "candidate_url_hash")
    op.execute(
        "UPDATE research_discovery_artifacts "
        "SET schema_version = 'research_discovery.v1', "
        "payload = jsonb_build_object("
        "'schema_version', 'research_discovery.v1', "
        "'request_id', research_request_id::text, "
        "'candidates', '[]'::jsonb"
        ") "
        "WHERE schema_version = 'research_discovery_audit.v1'"
    )
