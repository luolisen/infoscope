from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

MaintenanceStatus = Literal["idle", "running", "failed"]
MaintenanceRunStatus = Literal["pending", "running", "completed", "failed"]
MaintenancePhase = Literal[
    "window_analysis", "event_backwrite", "reconciliation", "personalization"
]


class MaintenanceStatusResponse(BaseModel):
    status: MaintenanceStatus
    phase: MaintenancePhase | None
    cycle_started_at: datetime | None
    cycle_finished_at: datetime | None
    next_cycle_at: datetime | None


class MaintenanceAcceptedResponse(BaseModel):
    run_id: UUID
    status: Literal["pending"] = "pending"


class MaintenanceRunResponse(BaseModel):
    run_id: UUID
    status: MaintenanceRunStatus
    phase: MaintenancePhase | None
    started_at: datetime | None
    finished_at: datetime | None
