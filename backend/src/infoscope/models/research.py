from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from infoscope.models.base import Base


class ResearchTrigger(StrEnum):
    ASK_MISSING_FACT = "ask_missing_fact"
    BACKWRITE_ENRICHMENT = "backwrite_enrichment"


class ResearchStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"


class ResearchSourceKind(StrEnum):
    WEB_PAGE = "web_page"
    GITHUB_DOCUMENT = "github_document"


class ResearchSourceStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ResearchRequest(Base):
    __tablename__ = "research_requests"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_research_requests_idempotency_key"),
        CheckConstraint(
            "trigger IN ('ask_missing_fact', 'backwrite_enrichment')",
            name="ck_research_requests_trigger",
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'partial', 'failed')",
            name="ck_research_requests_status",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_research_requests_attempt_count"),
        CheckConstraint("max_attempts > 0", name="ck_research_requests_max_attempts"),
        CheckConstraint("input_hash ~ '^[0-9a-f]{64}$'", name="ck_research_requests_input_hash"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    idempotency_key: Mapped[UUID] = mapped_column(nullable=False)
    trigger: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ResearchRequestEvent(Base):
    __tablename__ = "research_request_events"

    research_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_requests.id", ondelete="CASCADE"), primary_key=True
    )
    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("events.id", ondelete="RESTRICT"), primary_key=True
    )


class ResearchRun(Base):
    __tablename__ = "research_runs"
    __table_args__ = (
        UniqueConstraint(
            "research_request_id", "attempt", name="uq_research_runs_request_attempt"
        ),
        CheckConstraint(
            "status IN ('running', 'succeeded', 'partial', 'failed')",
            name="ck_research_runs_status",
        ),
        CheckConstraint("attempt > 0", name="ck_research_runs_attempt"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    research_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ResearchDiscoveryArtifact(Base):
    __tablename__ = "research_discovery_artifacts"
    __table_args__ = (
        UniqueConstraint("research_request_id", name="uq_research_discovery_request"),
        CheckConstraint(
            "input_hash ~ '^[0-9a-f]{64}$'", name="ck_research_discovery_input_hash"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    research_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_runs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    runtime: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    token_usage: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ResearchSource(Base):
    __tablename__ = "research_sources"
    __table_args__ = (
        UniqueConstraint(
            "research_request_id", "candidate_index", name="uq_research_sources_index"
        ),
        UniqueConstraint(
            "research_request_id", "canonical_url_hash", name="uq_research_sources_url"
        ),
        CheckConstraint(
            "source_kind IN ('web_page', 'github_document')",
            name="ck_research_sources_kind",
        ),
        CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed')",
            name="ck_research_sources_status",
        ),
        CheckConstraint("candidate_index >= 0", name="ck_research_sources_candidate_index"),
        CheckConstraint("attempt_count >= 0", name="ck_research_sources_attempt_count"),
        CheckConstraint(
            "canonical_url_hash ~ '^[0-9a-f]{64}$'",
            name="ck_research_sources_url_hash",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    research_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    candidate_index: Mapped[int] = mapped_column(Integer, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    raw_information_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("raw_information.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
