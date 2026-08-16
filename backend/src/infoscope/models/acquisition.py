from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from infoscope.models.base import Base


class SourceVisibility(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"


class NormalizationStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class EvidenceVisibility(StrEnum):
    PUBLIC = "public"
    PRIVATE_SANITIZED = "private_sanitized"


class PipelineRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class RawInformation(Base):
    __tablename__ = "raw_information"
    __table_args__ = (
        UniqueConstraint("source_type", "source_key", name="uq_raw_information_source"),
        CheckConstraint(
            "source_visibility IN ('public', 'private')",
            name="ck_raw_information_source_visibility",
        ),
        CheckConstraint(
            "normalization_status IN ('pending', 'processing', 'succeeded', 'failed')",
            name="ck_raw_information_normalization_status",
        ),
        CheckConstraint(
            "normalization_attempts >= 0",
            name="ck_raw_information_normalization_attempts",
        ),
        Index(
            "ix_raw_information_normalization_cursor",
            "normalization_status",
            "acquired_at",
            "id",
        ),
        Index("ix_raw_information_acquisition_cursor", "acquired_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_key: Mapped[str] = mapped_column(String(512), nullable=False)
    source_visibility: Mapped[str] = mapped_column(String(16), nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    collector_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    normalization_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=NormalizationStatus.PENDING.value,
        server_default=NormalizationStatus.PENDING.value,
    )
    normalization_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    normalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Signal(Base):
    __tablename__ = "signals"
    __table_args__ = (
        UniqueConstraint(
            "raw_information_id", "signal_index", name="uq_signals_raw_information_index"
        ),
        CheckConstraint("signal_index >= 0", name="ck_signals_signal_index"),
        CheckConstraint(
            "evidence_visibility IN ('public', 'private_sanitized')",
            name="ck_signals_evidence_visibility",
        ),
        Index("ix_signals_content_hash", "content_hash"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    raw_information_id: Mapped[UUID] = mapped_column(
        ForeignKey("raw_information.id", ondelete="CASCADE"), nullable=False, index=True
    )
    signal_index: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_visibility: Mapped[str] = mapped_column(String(24), nullable=False)
    public_provenance: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    duplicate_of_signal_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("signals.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed')",
            name="ck_pipeline_runs_status",
        ),
        CheckConstraint("attempt > 0", name="ck_pipeline_runs_attempt"),
        CheckConstraint(
            "window_end = window_start + interval '1 hour'", name="ck_pipeline_runs_window"
        ),
        CheckConstraint(
            "(lower_cursor_acquired_at IS NULL) = (lower_cursor_raw_id IS NULL)",
            name="ck_pipeline_runs_lower_cursor_pair",
        ),
        CheckConstraint(
            "(upper_cursor_acquired_at IS NULL) = (upper_cursor_raw_id IS NULL)",
            name="ck_pipeline_runs_upper_cursor_pair",
        ),
        Index("ix_pipeline_runs_pipeline_window", "pipeline_name", "window_start"),
        Index("ix_pipeline_runs_pipeline_status", "pipeline_name", "status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    pipeline_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=PipelineRunStatus.PENDING.value,
        server_default=PipelineRunStatus.PENDING.value,
    )
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lower_cursor_acquired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lower_cursor_raw_id: Mapped[UUID | None] = mapped_column(nullable=True)
    upper_cursor_acquired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    upper_cursor_raw_id: Mapped[UUID | None] = mapped_column(nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PipelineCheckpoint(Base):
    __tablename__ = "pipeline_checkpoints"
    __table_args__ = (
        CheckConstraint(
            "(last_acquired_at IS NULL) = (last_raw_id IS NULL)",
            name="ck_pipeline_checkpoints_cursor_pair",
        ),
    )

    pipeline_name: Mapped[str] = mapped_column(String(128), primary_key=True)
    last_acquired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_raw_id: Mapped[UUID | None] = mapped_column(nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class PipelineArtifact(Base):
    __tablename__ = "pipeline_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "pipeline_run_id",
            "artifact_type",
            name="uq_pipeline_artifacts_run_type",
        ),
        UniqueConstraint(
            "artifact_type",
            "source_artifact_id",
            name="uq_pipeline_artifacts_type_source",
        ),
        CheckConstraint(
            "input_hash ~ '^[0-9a-f]{64}$'",
            name="ck_pipeline_artifacts_input_hash",
        ),
        CheckConstraint(
            "artifact_type NOT IN ('event_reconstruction', 'claim_extraction', "
            "'timeline_reconstruction', 'conflict_analysis') OR source_artifact_id IS NOT NULL",
            name="ck_pipeline_artifacts_derived_source",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    pipeline_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_artifact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("pipeline_artifacts.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    token_usage: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
