import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from infoscope.worker.main import _run_heartbeat, process_ask_queue_once, run


async def test_heartbeat_runs_independently_until_stopped() -> None:
    stop = asyncio.Event()
    worker_id = uuid4()
    started_at = datetime.now(UTC)
    record = AsyncMock()

    with patch("infoscope.worker.main.record_worker_heartbeat", record):
        task = asyncio.create_task(_run_heartbeat(worker_id, started_at, 0.01, stop))
        await asyncio.sleep(0.025)
        stop.set()
        await task

    assert record.await_count >= 2
    record.assert_awaited_with(worker_id, started_at)


async def test_worker_once_checks_database_and_exits() -> None:
    database_ping = AsyncMock()
    database_close = AsyncMock()

    with (
        patch("infoscope.worker.main.ping_database", database_ping),
        patch("infoscope.worker.main.close_database", database_close),
    ):
        await run(once=True)

    database_ping.assert_awaited_once()
    database_close.assert_awaited_once()


async def test_worker_trendradar_mode_collects_once_and_exits() -> None:
    database_ping = AsyncMock()
    database_close = AsyncMock()
    collect = AsyncMock()

    with (
        patch("infoscope.worker.main.ping_database", database_ping),
        patch("infoscope.worker.main.close_database", database_close),
        patch("infoscope.worker.main.collect_trendradar_once", collect),
    ):
        await run(collect_trendradar=True)

    database_ping.assert_awaited_once()
    collect.assert_awaited_once()
    database_close.assert_awaited_once()


async def test_worker_telegram_mode_collects_once_and_exits() -> None:
    database_ping = AsyncMock()
    database_close = AsyncMock()
    collect = AsyncMock()

    with (
        patch("infoscope.worker.main.ping_database", database_ping),
        patch("infoscope.worker.main.close_database", database_close),
        patch("infoscope.worker.main.collect_telegram_once", collect),
    ):
        await run(collect_telegram=True)

    database_ping.assert_awaited_once()
    collect.assert_awaited_once()
    database_close.assert_awaited_once()


async def test_worker_normalization_mode_runs_one_batch_and_exits() -> None:
    database_ping = AsyncMock()
    database_close = AsyncMock()
    normalize = AsyncMock()

    with (
        patch("infoscope.worker.main.ping_database", database_ping),
        patch("infoscope.worker.main.close_database", database_close),
        patch("infoscope.worker.main.normalize_once", normalize),
    ):
        await run(normalize=True)

    database_ping.assert_awaited_once()
    normalize.assert_awaited_once_with(retry_failed=False)
    database_close.assert_awaited_once()


async def test_worker_deduplication_mode_runs_and_exits() -> None:
    database_ping = AsyncMock()
    database_close = AsyncMock()
    deduplicate = AsyncMock()

    with (
        patch("infoscope.worker.main.ping_database", database_ping),
        patch("infoscope.worker.main.close_database", database_close),
        patch("infoscope.worker.main.deduplicate_once", deduplicate),
    ):
        await run(deduplicate=True)

    database_ping.assert_awaited_once()
    deduplicate.assert_awaited_once_with()
    database_close.assert_awaited_once()


async def test_worker_window_analysis_mode_runs_and_exits() -> None:
    database_ping = AsyncMock()
    database_close = AsyncMock()
    analyze = AsyncMock()

    with (
        patch("infoscope.worker.main.ping_database", database_ping),
        patch("infoscope.worker.main.close_database", database_close),
        patch("infoscope.worker.main.analyze_windows_once", analyze),
    ):
        await run(analyze_windows=True)

    database_ping.assert_awaited_once()
    analyze.assert_awaited_once_with(retry_run_id=None, replay_run_id=None)
    database_close.assert_awaited_once()


async def test_worker_replays_a_window_run_and_exits() -> None:
    database_ping = AsyncMock()
    database_close = AsyncMock()
    analyze = AsyncMock()
    run_id = uuid4()

    with (
        patch("infoscope.worker.main.ping_database", database_ping),
        patch("infoscope.worker.main.close_database", database_close),
        patch("infoscope.worker.main.analyze_windows_once", analyze),
    ):
        await run(replay_window_run=run_id)

    database_ping.assert_awaited_once()
    analyze.assert_awaited_once_with(retry_run_id=None, replay_run_id=run_id)
    database_close.assert_awaited_once()


async def test_worker_reconstructs_one_window_artifact_and_exits() -> None:
    database_ping = AsyncMock()
    database_close = AsyncMock()
    reconstruct = AsyncMock()
    artifact_id = uuid4()

    with (
        patch("infoscope.worker.main.ping_database", database_ping),
        patch("infoscope.worker.main.close_database", database_close),
        patch("infoscope.worker.main.reconstruct_event_once", reconstruct),
    ):
        await run(reconstruct_window_artifact=artifact_id)

    database_ping.assert_awaited_once()
    reconstruct.assert_awaited_once_with(artifact_id)
    database_close.assert_awaited_once()


async def test_worker_extracts_claims_from_one_artifact_and_exits() -> None:
    database_ping = AsyncMock()
    database_close = AsyncMock()
    extract = AsyncMock()
    artifact_id = uuid4()

    with (
        patch("infoscope.worker.main.ping_database", database_ping),
        patch("infoscope.worker.main.close_database", database_close),
        patch("infoscope.worker.main.extract_claims_once", extract),
    ):
        await run(extract_claims_artifact=artifact_id)

    extract.assert_awaited_once_with(artifact_id)
    database_close.assert_awaited_once()


async def test_worker_reconstructs_timeline_from_one_artifact_and_exits() -> None:
    database_ping = AsyncMock()
    database_close = AsyncMock()
    reconstruct = AsyncMock()
    artifact_id = uuid4()

    with (
        patch("infoscope.worker.main.ping_database", database_ping),
        patch("infoscope.worker.main.close_database", database_close),
        patch("infoscope.worker.main.reconstruct_timeline_once", reconstruct),
    ):
        await run(reconstruct_timeline_artifact=artifact_id)

    reconstruct.assert_awaited_once_with(artifact_id)
    database_close.assert_awaited_once()


async def test_worker_runs_one_ask_comparison_and_exits() -> None:
    database_ping = AsyncMock()
    database_close = AsyncMock()
    compare = AsyncMock()
    request_id = uuid4()

    with (
        patch("infoscope.worker.main.ping_database", database_ping),
        patch("infoscope.worker.main.close_database", database_close),
        patch("infoscope.worker.main.compare_ask_once", compare),
    ):
        await run(retry_ask_comparison=request_id)

    compare.assert_awaited_once_with(
        request_file=None,
        retry_request_id=request_id,
    )
    database_close.assert_awaited_once()


async def test_worker_runs_one_ask_research_bridge_and_exits() -> None:
    database_ping = AsyncMock()
    database_close = AsyncMock()
    bridge = AsyncMock()
    ask_id = uuid4()

    with (
        patch("infoscope.worker.main.ping_database", database_ping),
        patch("infoscope.worker.main.close_database", database_close),
        patch("infoscope.worker.main.run_ask_research_bridge_once", bridge),
    ):
        await run(ask_research_bridge=ask_id)

    bridge.assert_awaited_once_with(ask_id)
    database_close.assert_awaited_once()


async def test_worker_runs_one_ask_event_reconciliation_and_exits() -> None:
    database_ping = AsyncMock()
    database_close = AsyncMock()
    reconcile = AsyncMock()
    ask_id = uuid4()

    with (
        patch("infoscope.worker.main.ping_database", database_ping),
        patch("infoscope.worker.main.close_database", database_close),
        patch("infoscope.worker.main.run_ask_event_reconciliation_once", reconcile),
    ):
        await run(ask_event_reconciliation=ask_id)

    reconcile.assert_awaited_once_with(ask_id)
    database_close.assert_awaited_once()


async def test_worker_runs_one_ask_finalization_and_exits() -> None:
    database_ping = AsyncMock()
    database_close = AsyncMock()
    finalize = AsyncMock()
    ask_id = uuid4()

    with (
        patch("infoscope.worker.main.ping_database", database_ping),
        patch("infoscope.worker.main.close_database", database_close),
        patch("infoscope.worker.main.run_ask_finalization_once", finalize),
    ):
        await run(ask_finalization=ask_id)

    finalize.assert_awaited_once_with(ask_id)
    database_close.assert_awaited_once()


class _ScalarResult:
    def __init__(self, request) -> None:
        self.request = request

    def scalar_one_or_none(self):
        return self.request


class _QueueSession:
    def __init__(self, request) -> None:
        self.request = request

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def execute(self, statement):
        return _ScalarResult(self.request)


@pytest.mark.parametrize(
    ("stage", "target"),
    [
        ("comparing", "compare_ask_once"),
        ("awaiting_research", "run_ask_research_bridge_once"),
        ("awaiting_reconciliation", "run_ask_event_reconciliation_once"),
        ("finalizing", "run_ask_finalization_once"),
    ],
)
async def test_persisted_ask_stage_routes_to_exactly_one_worker(stage: str, target: str) -> None:
    ask_id = uuid4()
    request = SimpleNamespace(id=ask_id, stage=stage)
    dispatch = AsyncMock()
    with (
        patch("infoscope.worker.main.session_factory", lambda: _QueueSession(request)),
        patch(f"infoscope.worker.main.{target}", dispatch),
    ):
        assert await process_ask_queue_once() is True

    if stage == "comparing":
        dispatch.assert_awaited_once_with(retry_request_id=ask_id)
    else:
        dispatch.assert_awaited_once_with(ask_id)
