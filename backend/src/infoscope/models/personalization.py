from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from infoscope.models.base import Base


class PersonalizationRun(Base):
    __tablename__ = "personalization_runs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_personalization_runs_idempotency_key"),
        UniqueConstraint("id", "user_id", name="uq_personalization_runs_id_user"),
        UniqueConstraint("user_id", "input_hash", name="uq_personalization_runs_user_input"),
        UniqueConstraint("user_id", "active_slot", name="uq_personalization_runs_user_active"),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_personalization_runs_status",
        ),
        CheckConstraint(
            "(status IN ('pending', 'running') AND active_slot = 1) OR "
            "(status IN ('completed', 'failed') AND active_slot IS NULL)",
            name="ck_personalization_runs_active_slot",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_personalization_runs_attempt_count"),
        CheckConstraint("max_attempts > 0", name="ck_personalization_runs_max_attempts"),
        CheckConstraint("input_hash ~ '^[0-9a-f]{64}$'", name="ck_personalization_runs_input_hash"),
        CheckConstraint(
            "profile_hash ~ '^[0-9a-f]{64}$'", name="ck_personalization_runs_profile_hash"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    idempotency_key: Mapped[UUID] = mapped_column(nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    captured_update_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
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


class PersonalizationArtifact(Base):
    __tablename__ = "personalization_artifacts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["created_by_run_id", "user_id"],
            ["personalization_runs.id", "personalization_runs.user_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("created_by_run_id", name="uq_personalization_artifacts_run"),
        UniqueConstraint("user_id", "input_hash", name="uq_personalization_artifacts_user_input"),
        UniqueConstraint("id", "user_id", name="uq_personalization_artifacts_id_user"),
        CheckConstraint(
            "artifact_kind IN ('model', 'deterministic_empty')",
            name="ck_personalization_artifacts_kind",
        ),
        CheckConstraint(
            "input_hash ~ '^[0-9a-f]{64}$'", name="ck_personalization_artifacts_input_hash"
        ),
        CheckConstraint(
            "window_started_at < window_ended_at", name="ck_personalization_artifacts_window"
        ),
        CheckConstraint(
            "raw_information_count >= 0 AND event_count >= 0 "
            "AND relevant_event_count >= 0 AND relevant_event_count <= event_count",
            name="ck_personalization_artifacts_counts",
        ),
        CheckConstraint(
            "(artifact_kind = 'model' AND provider IS NOT NULL AND model IS NOT NULL "
            "AND token_usage IS NOT NULL) OR (artifact_kind = 'deterministic_empty' "
            "AND provider IS NULL AND model IS NULL AND token_usage IS NULL "
            "AND event_count = 0 AND relevant_event_count = 0)",
            name="ck_personalization_artifacts_metadata",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_run_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
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
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_information_count: Mapped[int] = mapped_column(Integer, nullable=False)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    relevant_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PersonalizedEvent(Base):
    __tablename__ = "personalized_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["artifact_id", "user_id"],
            ["personalization_artifacts.id", "personalization_artifacts.user_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("artifact_id", "event_id", name="uq_personalized_events_artifact_event"),
        UniqueConstraint(
            "artifact_id", "snapshot_position", name="uq_personalized_events_artifact_position"
        ),
        CheckConstraint("snapshot_position >= 0", name="ck_personalized_events_position"),
        CheckConstraint(
            "snapshot_new_claim_count >= 0 AND snapshot_conflict_count >= 0",
            name="ck_personalized_events_counts",
        ),
        CheckConstraint(
            "priority IN ('critical', 'high', 'normal', 'low')",
            name="ck_personalized_events_priority",
        ),
        CheckConstraint(
            "snapshot_state IN ('developing', 'confirmed', 'conflicting', 'cooling')",
            name="ck_personalized_events_state",
        ),
        CheckConstraint(
            "(relevant AND why_it_matters IS NOT NULL AND personalized_angle IS NOT NULL "
            "AND cardinality(matched_scope_ids) > 0 AND cardinality(matched_focus_ids) > 0) OR "
            "(NOT relevant AND why_it_matters IS NULL AND personalized_angle IS NULL "
            "AND cardinality(matched_scope_ids) = 0 AND cardinality(matched_focus_ids) = 0)",
            name="ck_personalized_events_relevance",
        ),
        Index(
            "ix_personalized_events_artifact_visible_order",
            "artifact_id",
            "relevant",
            "snapshot_display_time",
            "event_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    artifact_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    user_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("events.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_base_analysis_id: Mapped[UUID] = mapped_column(
        ForeignKey("base_analyses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    snapshot_position: Mapped[int] = mapped_column(Integer, nullable=False)
    relevant: Mapped[bool] = mapped_column(Boolean, nullable=False)
    priority: Mapped[str] = mapped_column(String(16), nullable=False)
    snapshot_title: Mapped[str] = mapped_column(String(512), nullable=False)
    snapshot_overview: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_state: Mapped[str] = mapped_column(String(24), nullable=False)
    snapshot_display_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    snapshot_event_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    snapshot_topics: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    snapshot_new_claim_count: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_conflict_count: Mapped[int] = mapped_column(Integer, nullable=False)
    why_it_matters: Mapped[str | None] = mapped_column(Text, nullable=True)
    personalized_angle: Mapped[str | None] = mapped_column(Text, nullable=True)
    matched_scope_ids: Mapped[list[str]] = mapped_column(ARRAY(String(32)), nullable=False)
    matched_focus_ids: Mapped[list[str]] = mapped_column(ARRAY(String(32)), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
