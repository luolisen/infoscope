import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete

from infoscope.db import session_factory
from infoscope.models import PipelineRun, PipelineRunStatus
from infoscope.services.pipeline import PipelineRepository

pytestmark = pytest.mark.skipif(
    os.environ.get("INFOSCOPE_POSTGRES_INTEGRATION") != "1",
    reason="requires the local PostgreSQL integration database",
)


@pytest.mark.asyncio(loop_scope="module")
async def test_recover_stale_running_preserves_fresh_run() -> None:
    now = datetime.now(UTC)
    window_start = datetime(2098, 1, 1, tzinfo=UTC)
    stale = PipelineRun(
        id=uuid4(),
        pipeline_name="test_stale_recovery",
        status=PipelineRunStatus.RUNNING.value,
        window_start=window_start,
        window_end=window_start + timedelta(hours=1),
        attempt=1,
        started_at=now - timedelta(minutes=30),
    )
    fresh = PipelineRun(
        id=uuid4(),
        pipeline_name="test_stale_recovery",
        status=PipelineRunStatus.RUNNING.value,
        window_start=window_start + timedelta(hours=1),
        window_end=window_start + timedelta(hours=2),
        attempt=1,
        started_at=now - timedelta(minutes=1),
    )
    async with session_factory() as database:
        database.add_all([stale, fresh])
        await database.commit()
        try:
            recovered = await PipelineRepository(database).recover_stale_running(
                stale_before=now - timedelta(minutes=15),
                finished_at=now,
            )
            await database.refresh(stale)
            await database.refresh(fresh)

            assert recovered == [stale.id]
            assert stale.status == PipelineRunStatus.FAILED.value
            assert stale.error_code == "PIPELINE_WORKER_LOST"
            assert stale.finished_at == now
            assert fresh.status == PipelineRunStatus.RUNNING.value
            assert fresh.finished_at is None
            assert fresh.error_code is None
        finally:
            await database.execute(
                delete(PipelineRun).where(PipelineRun.id.in_([stale.id, fresh.id]))
            )
            await database.commit()
