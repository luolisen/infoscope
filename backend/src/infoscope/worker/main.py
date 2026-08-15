from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from datetime import UTC, datetime

import httpx

from infoscope.analysis import DeepSeekAnalysisClient, load_analysis_config
from infoscope.config import get_settings
from infoscope.db import close_database, ping_database, session_factory
from infoscope.integrations.telegram import (
    TelegramCollector,
    TelegramNewsClient,
    load_telegram_config,
)
from infoscope.integrations.trendradar import TrendRadarCollector, load_trendradar_config
from infoscope.integrations.trendradar.client import NewsNowClient, RSSClient
from infoscope.services.acquisition import AcquisitionRepository
from infoscope.services.deduplication import DeduplicationResult, ExactDeduplicationRunner
from infoscope.services.normalization import NormalizationResult, NormalizationRunner
from infoscope.services.pipeline import PipelineRepository
from infoscope.services.window_analysis import WindowAnalysisRunner, WindowRunResult

logger = logging.getLogger("infoscope.worker")


async def collect_trendradar_once() -> None:
    settings = get_settings()
    config = load_trendradar_config(settings.resolved_trendradar_config_path)
    async with httpx.AsyncClient(follow_redirects=True) as client:
        async with session_factory() as database:
            collector = TrendRadarCollector(
                config=config,
                hotlists=NewsNowClient(client, config.newsnow),
                rss=RSSClient(client, timeout_seconds=config.rss.timeout_seconds),
                repository=AcquisitionRepository(database),
            )
            result = await collector.collect()
    logger.info(
        "trendradar collection complete inserted=%d duplicates=%d failures=%d",
        result.inserted,
        result.duplicates,
        len(result.failures),
    )
    for failure in result.failures:
        logger.warning(
            "trendradar source failed source_id=%s error_code=%s",
            failure.source_id,
            failure.error_code,
        )


async def login_telegram() -> None:
    config = load_telegram_config(get_settings())
    client = TelegramNewsClient(config)
    await client.login()
    logger.info("telegram session authorized")


async def collect_telegram_once() -> None:
    config = load_telegram_config(get_settings())
    client = TelegramNewsClient(config)
    await client.connect()
    try:
        async with session_factory() as database:
            result = await TelegramCollector(
                client=client,
                repository=AcquisitionRepository(database),
            ).collect()
    finally:
        await client.disconnect()
    logger.info(
        "telegram collection complete dialogs=%d inserted=%d duplicates=%d failures=%d",
        result.dialogs,
        result.inserted,
        result.duplicates,
        len(result.failures),
    )
    for failure in result.failures:
        logger.warning("telegram dialog failed error_code=%s", failure.error_code)


async def normalize_once(*, retry_failed: bool = False) -> NormalizationResult:
    settings = get_settings()
    async with session_factory() as database:
        result = await NormalizationRunner(
            repository=AcquisitionRepository(database),
        ).run_once(
            retry_failed=retry_failed,
            limit=settings.normalization_batch_size,
        )
    logger.info(
        "normalization complete processed=%d succeeded=%d failed=%d retry_failed=%s",
        result.processed,
        result.succeeded,
        result.failed,
        retry_failed,
    )
    return result


async def deduplicate_once() -> DeduplicationResult:
    settings = get_settings()
    async with session_factory() as database:
        result = await ExactDeduplicationRunner(
            repository=AcquisitionRepository(database),
        ).run(batch_size=settings.deduplication_batch_size)
    logger.info(
        "deduplication complete scanned=%d duplicates_linked=%d",
        result.scanned,
        result.duplicates_linked,
    )
    return result


async def analyze_windows_once() -> WindowRunResult:
    settings = get_settings()
    config = load_analysis_config(settings)
    async with httpx.AsyncClient() as client:
        async with session_factory() as database:
            result = await WindowAnalysisRunner(
                acquisition=AcquisitionRepository(database),
                pipeline=PipelineRepository(database),
                client=DeepSeekAnalysisClient(client=client, config=config),
                max_signals=settings.window_analysis_max_signals,
                max_input_chars=settings.window_analysis_max_input_chars,
            ).run_available(
                watermark=datetime.now(UTC),
                max_windows=settings.window_analysis_max_windows,
            )
    logger.info(
        "window analysis complete succeeded=%d failed=%d raws=%d signals=%d",
        result.windows_succeeded,
        result.windows_failed,
        result.raws_scanned,
        result.signals_analyzed,
    )
    return result


async def run(
    *,
    once: bool = False,
    collect_trendradar: bool = False,
    collect_telegram: bool = False,
    normalize: bool = False,
    retry_normalization: bool = False,
    deduplicate: bool = False,
    analyze_windows: bool = False,
) -> None:
    settings = get_settings()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    for signal_name in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signal_name, stop.set)

    try:
        while not stop.is_set():
            await ping_database()
            if collect_trendradar:
                await collect_trendradar_once()
            if collect_telegram:
                await collect_telegram_once()
            if normalize or retry_normalization:
                await normalize_once(retry_failed=retry_normalization)
            if deduplicate:
                await deduplicate_once()
            if analyze_windows:
                await analyze_windows_once()
            logger.info("worker heartbeat")
            if (
                once
                or collect_trendradar
                or collect_telegram
                or normalize
                or retry_normalization
                or deduplicate
                or analyze_windows
            ):
                return
            try:
                await asyncio.wait_for(stop.wait(), timeout=settings.worker_poll_seconds)
            except TimeoutError:
                continue
    finally:
        await close_database()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Infoscope worker")
    parser.add_argument("--once", action="store_true", help="Check dependencies once and exit")
    parser.add_argument(
        "--collect-trendradar",
        action="store_true",
        help="Collect the frozen TrendRadar sources once and exit",
    )
    parser.add_argument(
        "--telegram-login",
        action="store_true",
        help="Authorize the local Telegram user session interactively",
    )
    parser.add_argument(
        "--collect-telegram",
        action="store_true",
        help="Collect text messages from the configured Telegram folder once",
    )
    normalization_group = parser.add_mutually_exclusive_group()
    normalization_group.add_argument(
        "--normalize",
        action="store_true",
        help="Normalize one batch of pending Raw records",
    )
    normalization_group.add_argument(
        "--retry-normalization",
        action="store_true",
        help="Retry one batch of failed Raw normalization records",
    )
    parser.add_argument(
        "--deduplicate",
        action="store_true",
        help="Link exact normalized-text duplicate Signals",
    )
    parser.add_argument(
        "--analyze-windows",
        action="store_true",
        help="Analyze available complete one-hour windows",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    if args.telegram_login:
        asyncio.run(login_telegram())
    else:
        asyncio.run(
            run(
                once=args.once,
                collect_trendradar=args.collect_trendradar,
                collect_telegram=args.collect_telegram,
                normalize=args.normalize,
                retry_normalization=args.retry_normalization,
                deduplicate=args.deduplicate,
                analyze_windows=args.analyze_windows,
            )
        )
    return 0
