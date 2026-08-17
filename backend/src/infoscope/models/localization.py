from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from infoscope.models.base import Base


class EventLocalizationRun(Base):
    __tablename__ = "event_localization_runs"
    __table_args__ = (
        UniqueConstraint("locale", "active_slot", name="uq_event_localization_runs_active"),
        CheckConstraint("locale = 'zh-CN'", name="ck_event_localization_runs_locale"),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_event_localization_runs_status",
        ),
        CheckConstraint(
            "(status IN ('pending', 'running') AND active_slot = 1) OR "
            "(status IN ('completed', 'failed') AND active_slot IS NULL)",
            name="ck_event_localization_runs_active_slot",
        ),
        CheckConstraint(
            "total_event_count >= 0 AND batch_count >= 0 AND completed_batch_count >= 0 "
            "AND failed_batch_count >= 0 AND completed_batch_count + failed_batch_count "
            "<= batch_count",
            name="ck_event_localization_runs_counts",
        ),
        CheckConstraint(
            "batch_size BETWEEN 1 AND 10", name="ck_event_localization_runs_batch_size"
        ),
        CheckConstraint(
            "batch_concurrency BETWEEN 1 AND 3",
            name="ck_event_localization_runs_concurrency",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    locale: Mapped[str] = mapped_column(String(16), nullable=False, default="zh-CN")
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    active_slot: Mapped[int | None] = mapped_column(SmallInteger, nullable=True, default=1)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    batch_size: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    batch_concurrency: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    total_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    batch_count: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_batch_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_batch_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    token_usage: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class EventLocalizationArtifact(Base):
    __tablename__ = "event_localization_artifacts"
    __table_args__ = (
        UniqueConstraint("locale", "input_hash", name="uq_event_localization_artifacts_input"),
        CheckConstraint("locale = 'zh-CN'", name="ck_event_localization_artifacts_locale"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    locale: Mapped[str] = mapped_column(String(16), nullable=False, default="zh-CN")
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    output_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    token_usage: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EventLocalizationBatch(Base):
    __tablename__ = "event_localization_batches"
    __table_args__ = (
        UniqueConstraint("run_id", "batch_index", name="uq_event_localization_batches_position"),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_event_localization_batches_status",
        ),
        CheckConstraint("batch_index >= 0", name="ck_event_localization_batches_index"),
        CheckConstraint(
            "attempt_count >= 0 AND max_attempts > 0",
            name="ck_event_localization_batches_attempts",
        ),
        CheckConstraint(
            "cardinality(event_ids) BETWEEN 1 AND 10",
            name="ck_event_localization_batches_event_count",
        ),
        CheckConstraint(
            "(status = 'completed' AND artifact_id IS NOT NULL) OR "
            "(status != 'completed' AND artifact_id IS NULL)",
            name="ck_event_localization_batches_artifact",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("event_localization_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    batch_index: Mapped[int] = mapped_column(Integer, nullable=False)
    event_ids: Mapped[list[UUID]] = mapped_column(ARRAY(PGUUID(as_uuid=True)), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    artifact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("event_localization_artifacts.id", ondelete="RESTRICT"), nullable=True
    )
    artifact_reused: Mapped[bool] = mapped_column(nullable=False, default=False)
    token_usage: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class EventLocalization(Base):
    __tablename__ = "event_localizations"
    __table_args__ = (
        UniqueConstraint("event_id", "locale", name="uq_event_localizations_event_locale"),
        CheckConstraint("locale = 'zh-CN'", name="ck_event_localizations_locale"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    locale: Mapped[str] = mapped_column(String(16), nullable=False, default="zh-CN")
    source_artifact_id: Mapped[UUID] = mapped_column(
        ForeignKey("event_localization_artifacts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    event_input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    overview: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
