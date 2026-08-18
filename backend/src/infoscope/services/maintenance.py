from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Protocol
from uuid import UUID, uuid4, uuid5

from fastapi import Depends, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from infoscope.db import get_session
from infoscope.errors import ApiError
from infoscope.models import BackwriteCycle, MaintenanceRun, User
from infoscope.schemas.maintenance import (
    MaintenanceAcceptedResponse,
    MaintenanceRunResponse,
    MaintenanceStatusResponse,
)

MAINTENANCE_DELAY = timedelta(hours=1)
MAINTENANCE_BACKWRITE_NAMESPACE = UUID("44a8817e-991a-4c8c-883a-520677418a2d")
logger = logging.getLogger("infoscope.maintenance")
MAINTENANCE_PHASES = (
    "window_analysis",
    "reconciliation",
    "event_backwrite",
    "personalization",
)


class MaintenanceError(RuntimeError):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


class MaintenanceRepository:
    def __init__(
        self,
        database: AsyncSession,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        stale_after: timedelta = timedelta(minutes=15),
    ) -> None:
        self.database = database
        self.clock = clock
        self.stale_after = stale_after

    async def create(self, user_id: UUID) -> MaintenanceRun:
        run_id = uuid4()
        inserted_id = (
            await self.database.execute(
                insert(MaintenanceRun)
                .values(
                    id=run_id,
                    requested_by_user_id=user_id,
                    status="pending",
                    phase=None,
                    active_slot=1,
                    error_code=None,
                    started_at=None,
                    finished_at=None,
                )
                .on_conflict_do_nothing(index_elements=[MaintenanceRun.active_slot])
                .returning(MaintenanceRun.id)
            )
        ).scalar_one_or_none()
        if inserted_id is None:
            await self.database.rollback()
            raise MaintenanceError("MAINTENANCE_ALREADY_RUNNING")
        await self.database.commit()
        run = await self.database.get(MaintenanceRun, run_id)
        if run is None:
            raise MaintenanceError("MAINTENANCE_RUN_NOT_FOUND")
        return run

    async def latest(self) -> MaintenanceRun | None:
        return (
            await self.database.execute(
                select(MaintenanceRun).order_by(MaintenanceRun.created_at.desc(), MaintenanceRun.id)
            )
        ).scalars().first()

    async def enqueue_due(self) -> MaintenanceRun | None:
        latest = await self.latest()
        if latest is None or latest.status in {"pending", "running"}:
            return None
        if latest.finished_at is None or latest.finished_at + MAINTENANCE_DELAY > self.clock():
            return None
        try:
            return await self.create(latest.requested_by_user_id)
        except MaintenanceError as error:
            if error.error_code == "MAINTENANCE_ALREADY_RUNNING":
                return None
            raise

    async def get_for_user(self, run_id: UUID, user_id: UUID) -> MaintenanceRun | None:
        return (
            await self.database.execute(
                select(MaintenanceRun).where(
                    MaintenanceRun.id == run_id,
                    MaintenanceRun.requested_by_user_id == user_id,
                )
            )
        ).scalar_one_or_none()

    async def claim_next(self) -> MaintenanceRun | None:
        await self.recover_stale_running()
        recovered_backwrites = await self.recover_terminal_maintenance_backwrites()
        if recovered_backwrites:
            await self.database.commit()
        run = (
            await self.database.execute(
                select(MaintenanceRun)
                .where(MaintenanceRun.status == "pending")
                .order_by(MaintenanceRun.created_at, MaintenanceRun.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if run is None:
            return None
        run.status = "running"
        run.phase = MAINTENANCE_PHASES[0]
        run.started_at = self.clock()
        await self.database.commit()
        return run

    async def recover_stale_running(self) -> list[MaintenanceRun]:
        stale = list(
            (
                await self.database.execute(
                    select(MaintenanceRun)
                    .where(
                        MaintenanceRun.status == "running",
                        MaintenanceRun.updated_at < self.clock() - self.stale_after,
                    )
                    .order_by(MaintenanceRun.created_at, MaintenanceRun.id)
                    .with_for_update(skip_locked=True)
                )
            ).scalars()
        )
        for run in stale:
            run.status = "failed"
            run.phase = None
            run.active_slot = None
            run.error_code = "MAINTENANCE_WORKER_LOST"
            run.finished_at = self.clock()
        if stale:
            await self.database.commit()
        return stale

    async def recover_terminal_maintenance_backwrites(self) -> list[BackwriteCycle]:
        """Fail closed Backwrite queues abandoned by terminal Maintenance runs."""
        terminal_run_ids = list(
            (
                await self.database.execute(
                    select(MaintenanceRun.id).where(
                        MaintenanceRun.status.in_(("completed", "failed"))
                    )
                )
            ).scalars()
        )
        if not terminal_run_ids:
            return []
        active_cycles = list(
            (
                await self.database.execute(
                    select(BackwriteCycle.idempotency_key, BackwriteCycle.user_id).where(
                        BackwriteCycle.status.in_(("pending", "running"))
                    )
                )
            ).all()
        )
        abandoned_keys = {
            idempotency_key
            for idempotency_key, user_id in active_cycles
            if any(
                idempotency_key
                == uuid5(
                    MAINTENANCE_BACKWRITE_NAMESPACE,
                    f"{run_id}:{user_id}:event_backwrite.v1",
                )
                for run_id in terminal_run_ids
            )
        }
        if not abandoned_keys:
            return []
        # Imported lazily to keep Maintenance's public API dependency surface small.
        from infoscope.services.backwrite import BackwriteRepository

        cycles = await BackwriteRepository(
            self.database,
            stale_after=self.stale_after,
        ).fail_abandoned_cycles(abandoned_keys)
        return cycles

    async def set_phase(self, run_id: UUID, phase: str) -> MaintenanceRun:
        if phase not in MAINTENANCE_PHASES:
            raise MaintenanceError("MAINTENANCE_PHASE_INVALID")
        run = await self._locked_running(run_id)
        run.phase = phase
        await self.database.commit()
        return run

    async def complete(self, run_id: UUID) -> MaintenanceRun:
        run = await self._locked_running(run_id)
        run.status = "completed"
        run.phase = None
        run.active_slot = None
        run.error_code = None
        run.finished_at = self.clock()
        await self.database.commit()
        return run

    async def fail(self, run_id: UUID, error_code: str) -> MaintenanceRun:
        await self.database.rollback()
        run = await self._locked_running(run_id)
        run.status = "failed"
        run.phase = None
        run.active_slot = None
        run.error_code = error_code[:128]
        run.finished_at = self.clock()
        await self.database.commit()
        return run

    async def _locked_running(self, run_id: UUID) -> MaintenanceRun:
        run = (
            await self.database.execute(
                select(MaintenanceRun)
                .where(MaintenanceRun.id == run_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if run is None:
            raise MaintenanceError("MAINTENANCE_RUN_NOT_FOUND")
        if run.status != "running":
            raise MaintenanceError("MAINTENANCE_RUN_NOT_RUNNING")
        return run


MaintenancePhaseExecutor = Callable[[MaintenanceRun], Awaitable[None]]


class MaintenanceHeartbeat(Protocol):
    async def __call__(self, run_id: UUID, stop: asyncio.Event) -> None: ...


class MaintenanceRunner:
    def __init__(
        self,
        repository: MaintenanceRepository,
        executors: dict[str, MaintenancePhaseExecutor],
        heartbeat: MaintenanceHeartbeat | None = None,
    ) -> None:
        if tuple(executors) != MAINTENANCE_PHASES:
            raise ValueError("maintenance executors must follow the frozen phase order")
        self.repository = repository
        self.executors = executors
        self.heartbeat = heartbeat

    async def run_next(self) -> MaintenanceRun | None:
        run = await self.repository.claim_next()
        if run is None:
            return None
        heartbeat_stop = asyncio.Event()
        heartbeat_task = (
            asyncio.create_task(self.heartbeat(run.id, heartbeat_stop))
            if self.heartbeat is not None
            else None
        )
        try:
            for phase, execute in self.executors.items():
                if run.phase != phase:
                    run = await self.repository.set_phase(run.id, phase)
                await execute(run)
            return await self.repository.complete(run.id)
        except Exception as error:
            error_code = getattr(error, "error_code", "MAINTENANCE_FAILED")
            logger.exception(
                "maintenance phase failed run_id=%s phase=%s error_type=%s error_code=%s",
                run.id,
                run.phase,
                type(error).__name__,
                error_code,
            )
            return await self.repository.fail(run.id, error_code)
        finally:
            heartbeat_stop.set()
            if heartbeat_task is not None:
                await heartbeat_task


class MaintenanceService:
    def __init__(self, database: AsyncSession) -> None:
        self.repository = MaintenanceRepository(database)

    async def status(self) -> MaintenanceStatusResponse:
        run = await self.repository.latest()
        if run is None:
            return MaintenanceStatusResponse(
                status="idle",
                phase=None,
                cycle_started_at=None,
                cycle_finished_at=None,
                next_cycle_at=None,
            )
        if run.status in {"pending", "running"}:
            return MaintenanceStatusResponse(
                status="running",
                phase=run.phase,
                cycle_started_at=run.started_at,
                cycle_finished_at=None,
                next_cycle_at=None,
            )
        return MaintenanceStatusResponse(
            status="failed" if run.status == "failed" else "idle",
            phase=None,
            cycle_started_at=run.started_at,
            cycle_finished_at=run.finished_at,
            next_cycle_at=(run.finished_at + MAINTENANCE_DELAY if run.finished_at else None),
        )

    async def create(self, user: User) -> MaintenanceAcceptedResponse:
        try:
            run = await self.repository.create(user.id)
        except MaintenanceError as error:
            if error.error_code == "MAINTENANCE_ALREADY_RUNNING":
                raise ApiError(
                    status_code=status.HTTP_409_CONFLICT,
                    code="MAINTENANCE_ALREADY_RUNNING",
                    message="A maintenance run is already active.",
                ) from error
            raise
        return MaintenanceAcceptedResponse(run_id=run.id)

    async def get(self, user: User, run_id: UUID) -> MaintenanceRunResponse:
        run = await self.repository.get_for_user(run_id, user.id)
        if run is None:
            raise ApiError(
                status_code=status.HTTP_404_NOT_FOUND,
                code="MAINTENANCE_RUN_NOT_FOUND",
                message="Maintenance run was not found.",
            )
        return MaintenanceRunResponse(
            run_id=run.id,
            status=run.status,
            phase=run.phase,
            started_at=run.started_at,
            finished_at=run.finished_at,
        )


def get_maintenance_service(
    database: Annotated[AsyncSession, Depends(get_session)],
) -> MaintenanceService:
    return MaintenanceService(database)
