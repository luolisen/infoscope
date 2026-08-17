import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete

from infoscope.db import session_factory
from infoscope.models import WorkerHeartbeat
from infoscope.services.worker_health import (
    record_worker_heartbeat,
    remove_worker_heartbeat,
    worker_is_available,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("INFOSCOPE_POSTGRES_INTEGRATION") != "1",
    reason="requires the local PostgreSQL integration database",
)


@pytest.mark.asyncio
async def test_worker_heartbeat_availability_and_cleanup() -> None:
    worker_id = uuid4()
    stale_id = uuid4()
    now = datetime.now(UTC)
    try:
        async with session_factory() as database:
            database.add(
                WorkerHeartbeat(
                    id=stale_id,
                    role="queue",
                    process_started_at=now - timedelta(minutes=2),
                    heartbeat_at=now - timedelta(minutes=2),
                )
            )
            await database.commit()

        assert not await worker_is_available(now=now, stale_after_seconds=20)

        await record_worker_heartbeat(worker_id, now)

        assert await worker_is_available(now=now, stale_after_seconds=20)
        async with session_factory() as database:
            assert await database.get(WorkerHeartbeat, stale_id) is None

        await remove_worker_heartbeat(worker_id)
        assert not await worker_is_available(now=now, stale_after_seconds=20)
    finally:
        async with session_factory() as database:
            await database.execute(
                delete(WorkerHeartbeat).where(WorkerHeartbeat.id.in_([worker_id, stale_id]))
            )
            await database.commit()
