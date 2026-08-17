from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from infoscope.config import get_settings
from infoscope.db import session_factory
from infoscope.models import WorkerHeartbeat


async def record_worker_heartbeat(
    worker_id: UUID,
    process_started_at: datetime,
    *,
    factory: async_sessionmaker[AsyncSession] = session_factory,
) -> None:
    now = datetime.now(UTC)
    stale_cutoff = now - timedelta(seconds=get_settings().worker_stale_after_seconds)
    async with factory() as database:
        await database.execute(
            delete(WorkerHeartbeat).where(
                WorkerHeartbeat.id != worker_id,
                WorkerHeartbeat.heartbeat_at < stale_cutoff,
            )
        )
        heartbeat = await database.get(WorkerHeartbeat, worker_id)
        if heartbeat is None:
            database.add(
                WorkerHeartbeat(
                    id=worker_id,
                    role="queue",
                    process_started_at=process_started_at,
                    heartbeat_at=now,
                )
            )
        else:
            heartbeat.heartbeat_at = now
        await database.commit()


async def remove_worker_heartbeat(
    worker_id: UUID,
    *,
    factory: async_sessionmaker[AsyncSession] = session_factory,
) -> None:
    async with factory() as database:
        await database.execute(delete(WorkerHeartbeat).where(WorkerHeartbeat.id == worker_id))
        await database.commit()


async def worker_is_available(
    *,
    factory: async_sessionmaker[AsyncSession] = session_factory,
    now: datetime | None = None,
    stale_after_seconds: float | None = None,
) -> bool:
    settings = get_settings()
    cutoff = (now or datetime.now(UTC)) - timedelta(
        seconds=stale_after_seconds or settings.worker_stale_after_seconds
    )
    async with factory() as database:
        worker_id = (
            await database.execute(
                select(WorkerHeartbeat.id)
                .where(
                    WorkerHeartbeat.role == "queue",
                    WorkerHeartbeat.heartbeat_at >= cutoff,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
    return worker_id is not None
