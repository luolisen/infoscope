from __future__ import annotations

from datetime import datetime
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


class AskRequest(Base):
    __tablename__ = "ask_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_ask_requests_status",
        ),
        CheckConstraint(
            "stage IN ('comparing', 'awaiting_research', 'awaiting_reconciliation', 'finalizing')",
            name="ck_ask_requests_stage",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_ask_requests_attempt_count"),
        CheckConstraint("max_attempts > 0", name="ck_ask_requests_max_attempts"),
        CheckConstraint("input_hash ~ '^[0-9a-f]{64}$'", name="ck_ask_requests_input_hash"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default="comparing")
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AskRequestEvent(Base):
    __tablename__ = "ask_request_events"
    __table_args__ = (
        UniqueConstraint("ask_request_id", "event_id", name="uq_ask_request_events_event"),
        UniqueConstraint("ask_request_id", "position", name="uq_ask_request_events_position"),
        CheckConstraint("position >= 0 AND position < 8", name="ck_ask_request_events_position"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    ask_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("ask_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("events.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class AskRun(Base):
    __tablename__ = "ask_runs"
    __table_args__ = (
        UniqueConstraint("ask_request_id", "attempt", name="uq_ask_runs_request_attempt"),
        CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="ck_ask_runs_status",
        ),
        CheckConstraint("attempt > 0", name="ck_ask_runs_attempt"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    ask_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("ask_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AskComparisonArtifact(Base):
    __tablename__ = "ask_comparison_artifacts"
    __table_args__ = (
        UniqueConstraint("ask_request_id", name="uq_ask_comparison_artifacts_request"),
        UniqueConstraint("created_by_run_id", name="uq_ask_comparison_artifacts_run"),
        CheckConstraint(
            "input_hash ~ '^[0-9a-f]{64}$'", name="ck_ask_comparison_artifacts_input_hash"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    ask_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("ask_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("ask_runs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    output: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    token_usage: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AskResearchBridge(Base):
    __tablename__ = "ask_research_bridges"
    __table_args__ = (
        UniqueConstraint("ask_request_id", name="uq_ask_research_bridges_request"),
        UniqueConstraint(
            "comparison_artifact_id", name="uq_ask_research_bridges_comparison_artifact"
        ),
        UniqueConstraint("research_request_id", name="uq_ask_research_bridges_research_request"),
        UniqueConstraint("idempotency_key", name="uq_ask_research_bridges_idempotency_key"),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_ask_research_bridges_status",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_ask_research_bridges_attempt_count"),
        CheckConstraint("max_attempts > 0", name="ck_ask_research_bridges_max_attempts"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    ask_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("ask_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    comparison_artifact_id: Mapped[UUID] = mapped_column(
        ForeignKey("ask_comparison_artifacts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    research_request_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("research_requests.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    idempotency_key: Mapped[UUID] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AskResearchArtifact(Base):
    __tablename__ = "ask_research_artifacts"
    __table_args__ = (
        UniqueConstraint("bridge_id", name="uq_ask_research_artifacts_bridge"),
        UniqueConstraint("ask_request_id", name="uq_ask_research_artifacts_request"),
        UniqueConstraint(
            "comparison_artifact_id", name="uq_ask_research_artifacts_comparison_artifact"
        ),
        UniqueConstraint(
            "research_request_id", name="uq_ask_research_artifacts_research_request"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    bridge_id: Mapped[UUID] = mapped_column(
        ForeignKey("ask_research_bridges.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ask_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("ask_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    comparison_artifact_id: Mapped[UUID] = mapped_column(
        ForeignKey("ask_comparison_artifacts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    research_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_requests.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AskEventReconciliation(Base):
    __tablename__ = "ask_event_reconciliations"
    __table_args__ = (
        UniqueConstraint("ask_request_id", name="uq_ask_event_reconciliations_request"),
        UniqueConstraint("source_bridge_artifact_id", name="uq_ask_event_reconciliations_source"),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_ask_event_reconciliations_status",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_ask_event_reconciliations_attempt_count"),
        CheckConstraint("max_attempts > 0", name="ck_ask_event_reconciliations_max_attempts"),
        CheckConstraint(
            "input_hash IS NULL OR input_hash ~ '^[0-9a-f]{64}$'",
            name="ck_ask_event_reconciliations_input_hash",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    ask_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("ask_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_bridge_artifact_id: Mapped[UUID] = mapped_column(
        ForeignKey("ask_research_artifacts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AskEventReconciliationRun(Base):
    __tablename__ = "ask_event_reconciliation_runs"
    __table_args__ = (
        UniqueConstraint(
            "reconciliation_id", "attempt", name="uq_ask_event_reconciliation_runs_attempt"
        ),
        CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="ck_ask_event_reconciliation_runs_status",
        ),
        CheckConstraint("attempt > 0", name="ck_ask_event_reconciliation_runs_attempt"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    reconciliation_id: Mapped[UUID] = mapped_column(
        ForeignKey("ask_event_reconciliations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AskEventReconciliationArtifact(Base):
    __tablename__ = "ask_event_reconciliation_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "reconciliation_id", name="uq_ask_event_reconciliation_artifacts_reconciliation"
        ),
        UniqueConstraint("created_by_run_id", name="uq_ask_event_reconciliation_artifacts_run"),
        UniqueConstraint("ask_request_id", name="uq_ask_event_reconciliation_artifacts_request"),
        UniqueConstraint(
            "source_bridge_artifact_id", name="uq_ask_event_reconciliation_artifacts_source"
        ),
        CheckConstraint(
            "input_hash ~ '^[0-9a-f]{64}$'",
            name="ck_ask_event_reconciliation_artifacts_input_hash",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    reconciliation_id: Mapped[UUID] = mapped_column(
        ForeignKey("ask_event_reconciliations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("ask_event_reconciliation_runs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    ask_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("ask_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_bridge_artifact_id: Mapped[UUID] = mapped_column(
        ForeignKey("ask_research_artifacts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    token_usage: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
