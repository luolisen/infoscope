from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from infoscope.models.base import Base


class BriefRun(Base):
    __tablename__ = "brief_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_personalization_artifact_id", "user_id"],
            ["personalization_artifacts.id", "personalization_artifacts.user_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("idempotency_key", name="uq_brief_runs_idempotency_key"),
        UniqueConstraint("id", "user_id", name="uq_brief_runs_id_user"),
        UniqueConstraint("source_personalization_artifact_id", name="uq_brief_runs_source"),
        UniqueConstraint("user_id", "input_hash", name="uq_brief_runs_user_input"),
        UniqueConstraint("user_id", "active_slot", name="uq_brief_runs_user_active"),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_brief_runs_status",
        ),
        CheckConstraint(
            "(status IN ('pending', 'running') AND active_slot = 1) OR "
            "(status IN ('completed', 'failed') AND active_slot IS NULL)",
            name="ck_brief_runs_active_slot",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_brief_runs_attempt_count"),
        CheckConstraint("max_attempts > 0", name="ck_brief_runs_max_attempts"),
        CheckConstraint("input_hash ~ '^[0-9a-f]{64}$'", name="ck_brief_runs_input_hash"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_personalization_artifact_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    idempotency_key: Mapped[UUID] = mapped_column(nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    active_slot: Mapped[int | None] = mapped_column(SmallInteger, nullable=True, default=1)
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


class BriefArtifact(Base):
    __tablename__ = "brief_artifacts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["created_by_run_id", "user_id"],
            ["brief_runs.id", "brief_runs.user_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_personalization_artifact_id", "user_id"],
            ["personalization_artifacts.id", "personalization_artifacts.user_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("created_by_run_id", name="uq_brief_artifacts_run"),
        UniqueConstraint("source_personalization_artifact_id", name="uq_brief_artifacts_source"),
        UniqueConstraint("user_id", "input_hash", name="uq_brief_artifacts_user_input"),
        UniqueConstraint(
            "id", "user_id", "source_personalization_artifact_id", name="uq_brief_artifacts_scope"
        ),
        CheckConstraint(
            "artifact_kind IN ('model', 'deterministic_empty')",
            name="ck_brief_artifacts_kind",
        ),
        CheckConstraint("input_hash ~ '^[0-9a-f]{64}$'", name="ck_brief_artifacts_input_hash"),
        CheckConstraint(
            "(artifact_kind = 'model' AND provider IS NOT NULL AND model IS NOT NULL "
            "AND token_usage IS NOT NULL) OR (artifact_kind = 'deterministic_empty' "
            "AND provider IS NULL AND model IS NULL AND token_usage IS NULL)",
            name="ck_brief_artifacts_metadata",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    created_by_run_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    source_personalization_artifact_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    artifact_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    output_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    token_usage: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BriefItem(Base):
    __tablename__ = "brief_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["artifact_id", "user_id", "source_personalization_artifact_id"],
            [
                "brief_artifacts.id",
                "brief_artifacts.user_id",
                "brief_artifacts.source_personalization_artifact_id",
            ],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            [
                "source_personalized_event_id",
                "source_personalization_artifact_id",
                "user_id",
                "event_id",
            ],
            [
                "personalized_events.id",
                "personalized_events.artifact_id",
                "personalized_events.user_id",
                "personalized_events.event_id",
            ],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("artifact_id", "event_id", name="uq_brief_items_artifact_event"),
        UniqueConstraint("artifact_id", "position", name="uq_brief_items_artifact_position"),
        CheckConstraint("position >= 0", name="ck_brief_items_position"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    artifact_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    user_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    source_personalization_artifact_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    source_personalized_event_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    event_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_title: Mapped[str] = mapped_column(String(512), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    why_it_matters: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
