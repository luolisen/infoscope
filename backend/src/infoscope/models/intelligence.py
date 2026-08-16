from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from infoscope.models.base import Base


class Claim(Base):
    __tablename__ = "claims"
    __table_args__ = (
        CheckConstraint(
            "state IN ('confirmed', 'unresolved', 'conflicting', 'contradicted')",
            name="ck_claims_state",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ClaimSignal(Base):
    __tablename__ = "claim_signals"
    __table_args__ = (
        UniqueConstraint("claim_id", "signal_id", name="uq_claim_signals_claim_signal"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="CASCADE"), nullable=False, index=True
    )
    signal_id: Mapped[UUID] = mapped_column(
        ForeignKey("signals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attached_by_pipeline_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TimelineEntry(Base):
    __tablename__ = "timeline_entries"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class TimelineClaim(Base):
    __tablename__ = "timeline_claims"
    __table_args__ = (
        UniqueConstraint("timeline_entry_id", "claim_id", name="uq_timeline_claims_entry_claim"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    timeline_entry_id: Mapped[UUID] = mapped_column(
        ForeignKey("timeline_entries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attached_by_pipeline_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Conflict(Base):
    __tablename__ = "conflicts"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ConflictClaim(Base):
    __tablename__ = "conflict_claims"
    __table_args__ = (
        UniqueConstraint("conflict_id", "claim_id", name="uq_conflict_claims_conflict_claim"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    conflict_id: Mapped[UUID] = mapped_column(
        ForeignKey("conflicts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attached_by_pipeline_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ConflictSignal(Base):
    __tablename__ = "conflict_signals"
    __table_args__ = (
        UniqueConstraint("conflict_id", "signal_id", name="uq_conflict_signals_conflict_signal"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    conflict_id: Mapped[UUID] = mapped_column(
        ForeignKey("conflicts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    signal_id: Mapped[UUID] = mapped_column(
        ForeignKey("signals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attached_by_pipeline_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BaseAnalysis(Base):
    __tablename__ = "base_analyses"
    __table_args__ = (
        CheckConstraint(
            "importance IN ('low', 'medium', 'high', 'critical')",
            name="ck_base_analyses_importance",
        ),
        UniqueConstraint("event_id", name="uq_base_analyses_event"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_artifact_id: Mapped[UUID] = mapped_column(
        ForeignKey("pipeline_artifacts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    importance: Mapped[str] = mapped_column(String(16), nullable=False)
    topics: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    entities: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
