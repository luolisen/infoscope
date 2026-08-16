from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from infoscope.api.app import app
from infoscope.api.dependencies import get_ready_user
from infoscope.models import User
from infoscope.schemas.maintenance import (
    MaintenanceAcceptedResponse,
    MaintenanceRunResponse,
    MaintenanceStatusResponse,
)
from infoscope.services.maintenance import (
    MAINTENANCE_DELAY,
    MAINTENANCE_PHASES,
    MaintenanceRunner,
    get_maintenance_service,
)


def _user() -> User:
    return User(
        id=uuid4(),
        username="alan",
        username_normalized="alan",
        password_hash="unused",
        onboarding_completed=True,
    )


class _ApiService:
    def __init__(self) -> None:
        self.run_id = uuid4()
        self.finished_at = datetime(2026, 8, 16, 13, tzinfo=UTC)

    async def status(self):
        return MaintenanceStatusResponse(
            status="idle",
            phase=None,
            cycle_started_at=self.finished_at - timedelta(minutes=20),
            cycle_finished_at=self.finished_at,
            next_cycle_at=self.finished_at + MAINTENANCE_DELAY,
        )

    async def create(self, _user):
        return MaintenanceAcceptedResponse(run_id=self.run_id)

    async def get(self, _user, run_id):
        assert run_id == self.run_id
        return MaintenanceRunResponse(
            run_id=run_id,
            status="running",
            phase="event_backwrite",
            started_at=self.finished_at,
            finished_at=None,
        )


@pytest.mark.asyncio
async def test_maintenance_public_contract_uses_backend_next_cycle_time() -> None:
    service = _ApiService()
    app.dependency_overrides[get_ready_user] = _user
    app.dependency_overrides[get_maintenance_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            status_response = await client.get("/api/v1/maintenance/status")
            accepted = await client.post("/api/v1/maintenance/runs")
            running = await client.get(f"/api/v1/maintenance/runs/{service.run_id}")
    finally:
        app.dependency_overrides.clear()

    assert status_response.status_code == 200
    assert status_response.json()["next_cycle_at"] == "2026-08-16T14:00:00Z"
    assert accepted.status_code == 202
    assert accepted.json() == {"run_id": str(service.run_id), "status": "pending"}
    assert running.json()["phase"] == "event_backwrite"


class _RunnerRepository:
    def __init__(self) -> None:
        self.run = SimpleNamespace(id=uuid4(), phase="window_analysis", status="running")
        self.transitions: list[str] = []
        self.error_code = None

    async def claim_next(self):
        return self.run

    async def set_phase(self, _run_id, phase):
        self.run.phase = phase
        self.transitions.append(phase)
        return self.run

    async def complete(self, _run_id):
        self.run.status = "completed"
        return self.run

    async def fail(self, _run_id, error_code):
        self.run.status = "failed"
        self.error_code = error_code
        return self.run


@pytest.mark.asyncio
async def test_maintenance_runner_executes_frozen_phase_order() -> None:
    repository = _RunnerRepository()
    executed: list[str] = []

    async def execute(run):
        executed.append(run.phase)

    result = await MaintenanceRunner(
        repository,  # type: ignore[arg-type]
        {phase: execute for phase in MAINTENANCE_PHASES},
    ).run_next()

    assert result.status == "completed"
    assert executed == list(MAINTENANCE_PHASES)
    assert repository.transitions == ["reconciliation", "event_backwrite"]


@pytest.mark.asyncio
async def test_maintenance_runner_isolates_phase_failure() -> None:
    repository = _RunnerRepository()

    async def window(_run):
        return None

    async def reconciliation(_run):
        raise RuntimeError("provider details must not leak")

    async def backwrite(_run):
        raise AssertionError("later phases must not run")

    result = await MaintenanceRunner(
        repository,  # type: ignore[arg-type]
        {
            "window_analysis": window,
            "reconciliation": reconciliation,
            "event_backwrite": backwrite,
        },
    ).run_next()

    assert result.status == "failed"
    assert repository.error_code == "MAINTENANCE_FAILED"
