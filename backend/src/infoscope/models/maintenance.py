from __future__ import annotations

from datetime import datetime
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
from sqlalchemy.orm import Mapped, mapped_column

from infoscope.models.base import Base


class MaintenanceRun(Base):
    __tablename__ = "maintenance_runs"
    __table_args__ = (
        UniqueConstraint("active_slot", name="uq_maintenance_runs_active_slot"),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_maintenance_runs_status",
        ),
        CheckConstraint(
            "phase IS NULL OR phase IN "
            "('window_analysis', 'event_backwrite', 'reconciliation', 'personalization')",
            name="ck_maintenance_runs_phase",
        ),
        CheckConstraint(
            "(status = 'pending' AND phase IS NULL AND started_at IS NULL "
            "AND finished_at IS NULL) OR "
            "(status = 'running' AND phase IS NOT NULL AND started_at IS NOT NULL "
            "AND finished_at IS NULL) OR "
            "(status IN ('completed', 'failed') AND phase IS NULL "
            "AND started_at IS NOT NULL AND finished_at IS NOT NULL)",
            name="ck_maintenance_runs_lifecycle",
        ),
        CheckConstraint(
            "(status IN ('pending', 'running') AND active_slot = 1) OR "
            "(status IN ('completed', 'failed') AND active_slot IS NULL)",
            name="ck_maintenance_runs_active_slot",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    requested_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    phase: Mapped[str | None] = mapped_column(String(32), nullable=True)
    active_slot: Mapped[int | None] = mapped_column(Integer, nullable=True, default=1)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
