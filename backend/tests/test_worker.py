from unittest.mock import AsyncMock, patch

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
    analyze.assert_awaited_once_with()
    database_close.assert_awaited_once()
