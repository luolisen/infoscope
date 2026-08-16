from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from infoscope.models.base import Base


class BackwriteCycle(Base):
    __tablename__ = "backwrite_cycles"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_backwrite_cycles_idempotency_key"),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'partial', 'failed')",
            name="ck_backwrite_cycles_status",
        ),
        CheckConstraint("input_hash ~ '^[0-9a-f]{64}$'", name="ck_backwrite_cycles_input_hash"),
        CheckConstraint("item_count >= 0", name="ck_backwrite_cycles_item_count"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    idempotency_key: Mapped[UUID] = mapped_column(nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class BackwriteItem(Base):
    __tablename__ = "backwrite_items"
    __table_args__ = (
        UniqueConstraint("cycle_id", "event_id", name="uq_backwrite_items_cycle_event"),
        UniqueConstraint(
            "cycle_id", "snapshot_position", name="uq_backwrite_items_snapshot_position"
        ),
        UniqueConstraint("cycle_id", "queue_position", name="uq_backwrite_items_queue_position"),
        CheckConstraint(
            "status IN ('pending', 'researching', 'reconciling', 'completed', 'failed')",
            name="ck_backwrite_items_status",
        ),
        CheckConstraint(
            "outcome IS NULL OR outcome IN ('updated', 'no_change')",
            name="ck_backwrite_items_outcome",
        ),
        CheckConstraint("snapshot_position >= 0", name="ck_backwrite_items_snapshot_position"),
        CheckConstraint("queue_position >= 0", name="ck_backwrite_items_queue_position"),
        CheckConstraint("attempt_count >= 0", name="ck_backwrite_items_attempt_count"),
        CheckConstraint("max_attempts > 0", name="ck_backwrite_items_max_attempts"),
        CheckConstraint(
            "input_hash IS NULL OR input_hash ~ '^[0-9a-f]{64}$'",
            name="ck_backwrite_items_input_hash",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    cycle_id: Mapped[UUID] = mapped_column(
        ForeignKey("backwrite_cycles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("events.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    snapshot_position: Mapped[int] = mapped_column(Integer, nullable=False)
    queue_position: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    outcome: Mapped[str | None] = mapped_column(String(16), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    research_request_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("research_requests.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    source_artifact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("backwrite_research_artifacts.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class BackwriteReconciliationRun(Base):
    __tablename__ = "backwrite_reconciliation_runs"
    __table_args__ = (
        UniqueConstraint("item_id", "attempt", name="uq_backwrite_reconciliation_runs_attempt"),
        CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="ck_backwrite_reconciliation_runs_status",
        ),
        CheckConstraint("attempt > 0", name="ck_backwrite_reconciliation_runs_attempt"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    item_id: Mapped[UUID] = mapped_column(
        ForeignKey("backwrite_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BackwriteResearchArtifact(Base):
    __tablename__ = "backwrite_research_artifacts"
    __table_args__ = (
        UniqueConstraint("item_id", name="uq_backwrite_research_artifacts_item"),
        UniqueConstraint("research_request_id", name="uq_backwrite_research_artifacts_request"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    item_id: Mapped[UUID] = mapped_column(
        ForeignKey("backwrite_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    research_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_requests.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BackwriteReconciliationArtifact(Base):
    __tablename__ = "backwrite_reconciliation_artifacts"
    __table_args__ = (
        UniqueConstraint("item_id", name="uq_backwrite_reconciliation_artifacts_item"),
        UniqueConstraint("created_by_run_id", name="uq_backwrite_reconciliation_artifacts_run"),
        CheckConstraint(
            "artifact_kind IN ('model', 'deterministic_no_change')",
            name="ck_backwrite_reconciliation_artifacts_kind",
        ),
        CheckConstraint(
            "input_hash ~ '^[0-9a-f]{64}$'",
            name="ck_backwrite_reconciliation_artifacts_input_hash",
        ),
        CheckConstraint(
            "(artifact_kind = 'deterministic_no_change' AND provider IS NULL AND model IS NULL "
            "AND token_usage IS NULL) OR (artifact_kind = 'model' AND provider IS NOT NULL "
            "AND model IS NOT NULL AND token_usage IS NOT NULL)",
            name="ck_backwrite_reconciliation_artifacts_model_metadata",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    item_id: Mapped[UUID] = mapped_column(
        ForeignKey("backwrite_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("backwrite_reconciliation_runs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    research_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_requests.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_artifact_id: Mapped[UUID] = mapped_column(
        ForeignKey("backwrite_research_artifacts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    artifact_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    token_usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
