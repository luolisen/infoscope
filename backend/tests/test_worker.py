from unittest.mock import AsyncMock, patch
from uuid import uuid4

from infoscope.worker.main import run


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
