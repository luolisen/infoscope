"""add privacy-safe research source audit

Revision ID: 20260816_0011
Revises: 20260816_0010
Create Date: 2026-08-16
"""

from collections.abc import Sequence
from hashlib import sha256
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260816_0011"
down_revision: str | None = "20260816_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tables():
    sources = sa.table(
        "research_sources",
        sa.column("id", sa.Uuid()),
        sa.column("research_request_id", sa.Uuid()),
        sa.column("candidate_index", sa.Integer()),
        sa.column("source_kind", sa.String()),
        sa.column("candidate_url_hash", sa.String()),
        sa.column("canonical_url", sa.Text()),
        sa.column("canonical_url_hash", sa.String()),
        sa.column("status", sa.String()),
        sa.column("attempt_count", sa.Integer()),
        sa.column("error_code", sa.String()),
    )
    artifacts = sa.table(
        "research_discovery_artifacts",
        sa.column("id", sa.Uuid()),
        sa.column("research_request_id", sa.Uuid()),
        sa.column("schema_version", sa.String()),
        sa.column("payload", postgresql.JSONB()),
    )
    return sources, artifacts


def _redact_legacy_artifacts() -> None:
    connection = op.get_bind()
    sources, artifacts = _tables()
    artifact_rows = list(
        connection.execute(
            sa.select(
                artifacts.c.id,
                artifacts.c.research_request_id,
                artifacts.c.payload,
            ).where(artifacts.c.schema_version == "research_discovery.v1")
        ).mappings()
    )
    for artifact in artifact_rows:
        request_id = artifact["research_request_id"]
        source_rows = list(
            connection.execute(
                sa.select(sources).where(sources.c.research_request_id == request_id)
            ).mappings()
        )
        source_by_index = {row["candidate_index"]: row for row in source_rows}
        legacy_payload = artifact["payload"] if isinstance(artifact["payload"], dict) else {}
        legacy_candidates = legacy_payload.get("candidates")
        if not isinstance(legacy_candidates, list):
            legacy_candidates = []
        safe_candidates: list[dict[str, object | None]] = []
        for index, candidate in enumerate(legacy_candidates):
            candidate = candidate if isinstance(candidate, dict) else {}
            source_url = candidate.get("source_url")
            source_url = source_url if isinstance(source_url, str) else ""
            candidate_url_hash = sha256(source_url.encode("utf-8")).hexdigest()
            source = source_by_index.get(index)
            if source is not None:
                connection.execute(
                    sources.update()
                    .where(sources.c.id == source["id"])
                    .values(candidate_url_hash=candidate_url_hash)
                )
                safe_candidates.append(
                    {
                        "candidate_index": index,
                        "source_kind": source["source_kind"],
                        "candidate_url_hash": candidate_url_hash,
                        "decision": "accepted",
                        "canonical_url": source["canonical_url"],
                        "relevance_summary": candidate.get("relevance_summary"),
                        "error_code": None,
                    }
                )
                continue
            source_kind = candidate.get("source_kind")
            source_kind = source_kind if isinstance(source_kind, str) else "web_page"
            error_code = "RESEARCH_LEGACY_CANDIDATE_REDACTED"
            connection.execute(
                sources.insert().values(
                    id=uuid4(),
                    research_request_id=request_id,
                    candidate_index=index,
                    source_kind=source_kind,
                    candidate_url_hash=candidate_url_hash,
                    canonical_url=None,
                    canonical_url_hash=None,
                    status="failed",
                    attempt_count=0,
                    error_code=error_code,
                )
            )
            safe_candidates.append(
                {
                    "candidate_index": index,
                    "source_kind": source_kind,
                    "candidate_url_hash": candidate_url_hash,
                    "decision": "rejected",
                    "canonical_url": None,
                    "relevance_summary": None,
                    "error_code": error_code,
                }
            )
        safe_payload = {
            "schema_version": "research_discovery_audit.v1",
            "request_id": str(request_id),
            "candidate_count": len(safe_candidates),
            "candidates": safe_candidates,
        }
        connection.execute(
            artifacts.update()
            .where(artifacts.c.id == artifact["id"])
            .values(schema_version="research_discovery_audit.v1", payload=safe_payload)
        )


def upgrade() -> None:
    op.add_column(
        "research_sources",
        sa.Column("candidate_url_hash", sa.String(length=64), nullable=True),
    )
    op.alter_column("research_sources", "canonical_url", nullable=True)
    op.alter_column("research_sources", "canonical_url_hash", nullable=True)
    _redact_legacy_artifacts()
    op.execute(
        "UPDATE research_sources "
        "SET candidate_url_hash = canonical_url_hash "
        "WHERE candidate_url_hash IS NULL"
    )
    op.alter_column("research_sources", "candidate_url_hash", nullable=False)
    op.create_check_constraint(
        "ck_research_sources_candidate_url_hash",
        "research_sources",
        "candidate_url_hash ~ '^[0-9a-f]{64}$'",
    )


def downgrade() -> None:
    connection = op.get_bind()
    sources, artifacts = _tables()
    artifact_rows = list(
        connection.execute(
            sa.select(artifacts.c.id, artifacts.c.research_request_id, artifacts.c.payload).where(
                artifacts.c.schema_version == "research_discovery_audit.v1"
            )
        ).mappings()
    )
    for artifact in artifact_rows:
        payload = artifact["payload"] if isinstance(artifact["payload"], dict) else {}
        candidates = payload.get("candidates")
        candidates = candidates if isinstance(candidates, list) else []
        legacy_candidates = [
            {
                "source_kind": candidate.get("source_kind"),
                "source_url": candidate.get("canonical_url"),
                "relevance_summary": candidate.get("relevance_summary"),
            }
            for candidate in candidates
            if isinstance(candidate, dict) and candidate.get("decision") == "accepted"
        ]
        connection.execute(
            artifacts.update()
            .where(artifacts.c.id == artifact["id"])
            .values(
                schema_version="research_discovery.v1",
                payload={
                    "schema_version": "research_discovery.v1",
                    "request_id": str(artifact["research_request_id"]),
                    "candidates": legacy_candidates,
                },
            )
        )
    op.execute("DELETE FROM research_sources WHERE canonical_url IS NULL")
    op.alter_column("research_sources", "canonical_url_hash", nullable=False)
    op.alter_column("research_sources", "canonical_url", nullable=False)
    op.drop_constraint(
        "ck_research_sources_candidate_url_hash",
        "research_sources",
        type_="check",
    )
    op.drop_column("research_sources", "candidate_url_hash")
