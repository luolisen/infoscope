from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from infoscope.models import PipelineArtifact, PipelineRun, PipelineRunStatus
from infoscope.pipeline import AcquisitionCursor, LogicalWindow, completed_windows
from infoscope.services.pipeline import ArtifactWrite, PipelineRepository


def test_logical_window_is_exactly_one_hour_and_half_open() -> None:
    start = datetime(2026, 8, 16, 10, 15, tzinfo=UTC)
    window = LogicalWindow.starting_at(start)

    assert window.end == start + timedelta(hours=1)
    assert window.contains(start)
    assert window.contains(window.end - timedelta(microseconds=1))
    assert not window.contains(window.end)

    with pytest.raises(ValueError, match="exactly one hour"):
        LogicalWindow(start=start, end=start + timedelta(minutes=59))


def test_compensation_produces_contiguous_windows_without_partial_tail() -> None:
    start = datetime(2026, 8, 16, 8, 30, tzinfo=UTC)

    windows = completed_windows(
        start=start,
        watermark=start + timedelta(hours=3, minutes=20),
    )

    assert len(windows) == 3
    assert all(window.end - window.start == timedelta(hours=1) for window in windows)
    assert all(left.end == right.start for left, right in zip(windows, windows[1:], strict=False))
    assert windows[-1].end == start + timedelta(hours=3)


def test_cursor_orders_ties_by_raw_id_instead_of_published_time() -> None:
    acquired_at = datetime(2026, 8, 16, 10, tzinfo=UTC)
    smaller = uuid4()
    larger = uuid4()
    if smaller.int > larger.int:
        smaller, larger = larger, smaller

    assert AcquisitionCursor(acquired_at, smaller) < AcquisitionCursor(acquired_at, larger)


class FakeDatabase:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0
        self.execute = AsyncMock()

    def add(self, value: object) -> None:
        self.added.append(value)

    def add_all(self, values: list[object]) -> None:
        self.added.extend(values)

    async def commit(self) -> None:
        self.commits += 1


class FakeScalarResult:
    def __init__(self, values: list[object]) -> None:
        self.values = values

    def scalars(self) -> list[object]:
        return self.values


async def test_stale_running_pipeline_runs_fail_closed_before_reconciliation() -> None:
    database = FakeDatabase()
    stale_id = uuid4()
    database.execute.return_value = FakeScalarResult([stale_id])
    repository = PipelineRepository(database)  # type: ignore[arg-type]
    finished_at = datetime(2026, 8, 16, 10, tzinfo=UTC)

    recovered = await repository.recover_stale_running(
        stale_before=finished_at - timedelta(minutes=15),
        finished_at=finished_at,
    )

    assert recovered == [stale_id]
    assert database.commits == 1
    statement = database.execute.await_args.args[0]
    assert "pipeline_runs.status = :status_1" in str(statement)
    assert "pipeline_runs.started_at < :started_at_1" in str(statement)


async def test_failed_run_retries_the_same_window_without_recollection() -> None:
    database = FakeDatabase()
    repository = PipelineRepository(database)  # type: ignore[arg-type]
    started_at = datetime(2026, 8, 16, 10, tzinfo=UTC)
    window = LogicalWindow.starting_at(started_at - timedelta(hours=1))
    lower_cursor = AcquisitionCursor(started_at - timedelta(hours=2), uuid4())
    failed_run = PipelineRun(
        id=uuid4(),
        pipeline_name="normalize",
        status=PipelineRunStatus.FAILED.value,
        window_start=window.start,
        window_end=window.end,
        lower_cursor_acquired_at=lower_cursor.acquired_at,
        lower_cursor_raw_id=lower_cursor.raw_id,
        attempt=1,
    )

    retry = await repository.retry_run(failed_run, started_at=started_at)

    assert retry.window_start == failed_run.window_start
    assert retry.window_end == failed_run.window_end
    assert retry.lower_cursor_acquired_at == lower_cursor.acquired_at
    assert retry.lower_cursor_raw_id == lower_cursor.raw_id
    assert retry.attempt == 2
    assert retry.status == PipelineRunStatus.RUNNING.value
    assert database.added == [retry]
    assert database.commits == 1


async def test_empty_window_completes_without_moving_raw_checkpoint() -> None:
    database = FakeDatabase()
    repository = PipelineRepository(database)  # type: ignore[arg-type]
    started_at = datetime(2026, 8, 16, 10, tzinfo=UTC)
    run = PipelineRun(
        id=uuid4(),
        pipeline_name="normalize",
        status=PipelineRunStatus.RUNNING.value,
        window_start=started_at - timedelta(hours=1),
        window_end=started_at,
        attempt=1,
    )

    await repository.complete_run(run, finished_at=started_at, upper_cursor=None)

    assert run.status == PipelineRunStatus.SUCCEEDED.value
    assert run.upper_cursor_acquired_at is None
    database.execute.assert_not_awaited()
    assert database.commits == 1


async def test_successful_run_can_be_replayed_for_the_same_raw_window() -> None:
    database = FakeDatabase()
    repository = PipelineRepository(database)  # type: ignore[arg-type]
    started_at = datetime(2026, 8, 16, 10, tzinfo=UTC)
    completed = PipelineRun(
        id=uuid4(),
        pipeline_name="normalize",
        status=PipelineRunStatus.SUCCEEDED.value,
        window_start=started_at - timedelta(hours=1),
        window_end=started_at,
        attempt=1,
    )

    replay = await repository.replay_run(completed, started_at=started_at)

    assert replay.window_start == completed.window_start
    assert replay.window_end == completed.window_end
    assert replay.attempt == 2
    assert replay.status == PipelineRunStatus.RUNNING.value


async def test_window_bundle_persists_batches_manifest_and_run_in_one_commit() -> None:
    database = FakeDatabase()
    repository = PipelineRepository(database)  # type: ignore[arg-type]
    finished_at = datetime(2026, 8, 16, 10, tzinfo=UTC)
    run = PipelineRun(
        id=uuid4(),
        pipeline_name="window_analysis",
        status=PipelineRunStatus.RUNNING.value,
        window_start=finished_at - timedelta(hours=1),
        window_end=finished_at,
        attempt=1,
    )
    batch_id = uuid4()
    batch = ArtifactWrite(
        id=batch_id,
        artifact_type="window_analysis_batch",
        artifact_key="000000",
        schema_version="window_analysis_batch.v2",
        input_hash="a" * 64,
        payload={},
        provider="test",
        model="test",
        token_usage={},
    )
    manifest = ArtifactWrite(
        id=uuid4(),
        artifact_type="window_analysis",
        artifact_key="default",
        schema_version="window_analysis.v2",
        input_hash="b" * 64,
        payload={"batch_artifact_ids": [str(batch_id)]},
        provider="internal",
        model="batched",
        token_usage={},
    )

    batches, saved_manifest = await repository.persist_window_bundle(
        run=run,
        batches=[batch],
        manifest=manifest,
        finished_at=finished_at,
        upper_cursor=None,
    )

    assert run.status == PipelineRunStatus.SUCCEEDED.value
    assert database.commits == 1
    assert len(database.added) == 2
    assert isinstance(database.added[0], PipelineArtifact)
    assert batches[0].artifact_key == "000000"
    assert saved_manifest.artifact_key == "default"
