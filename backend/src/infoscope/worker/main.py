from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4, uuid5

import httpx
from sqlalchemy import and_, func, or_, select, update

from infoscope.analysis.ask_schemas import AskRequestSpec
from infoscope.analysis.backwrite_schemas import BackwriteSnapshotSpec
from infoscope.analysis.client import DeepSeekAnalysisClient
from infoscope.analysis.intelligence_client import DeepSeekIntelligenceClient
from infoscope.analysis.localization_client import EventLocalizationClient
from infoscope.analysis.reconstruction_client import DeepSeekEventReconstructionClient
from infoscope.analysis.schemas import WindowAnalysisBatchArtifact, WindowAnalysisPayload
from infoscope.config import get_settings
from infoscope.db import close_database, ping_database, session_factory
from infoscope.integrations.research.client import OpenClawResearchClient
from infoscope.integrations.research.fetcher import DirectHTTPSResearchFetcher
from infoscope.integrations.research.grok import GrokBuildConfig, GrokBuildResearchClient
from infoscope.integrations.research.health import AgentReachHealthChecker
from infoscope.integrations.research.runtime import (
    research_capability_checker,
    research_runtime_config,
)
from infoscope.integrations.research.schemas import ResearchRequestSpec
from infoscope.integrations.telegram import (
    TelegramCollector,
    TelegramNewsClient,
    load_telegram_config,
)
from infoscope.integrations.trendradar import TrendRadarCollector, load_trendradar_config
from infoscope.integrations.trendradar.client import NewsNowClient, RSSClient
from infoscope.models import (
    AskRequest,
    BriefRun,
    EventLocalizationRun,
    MaintenanceRun,
    PipelineArtifact,
    PipelineRun,
    PipelineRunStatus,
    User,
)
from infoscope.schemas.model_settings import ModelSelection
from infoscope.services.acquisition import AcquisitionRepository
from infoscope.services.ask_comparison import AskComparisonRepository, AskComparisonRunner
from infoscope.services.ask_event_reconciliation import (
    AskEventReconciliationRepository,
    AskEventReconciliationRunner,
)
from infoscope.services.ask_finalization import AskFinalizationRepository, AskFinalizationRunner
from infoscope.services.ask_research_bridge import (
    AskResearchBridgeRepository,
    AskResearchBridgeRunner,
)
from infoscope.services.backwrite import (
    BackwriteRepository,
    BackwriteRunner,
    UnavailableUserVisibleEventSnapshotProvider,
    UserVisibleEventSnapshotProvider,
)
from infoscope.services.base_analysis import BaseAnalysisRepository, BaseAnalysisRunner
from infoscope.services.brief import BriefRepository, BriefRunner
from infoscope.services.claims_timeline import (
    ClaimExtractionRunner,
    ConflictAnalysisRunner,
    IntelligenceRepository,
    IntelligenceResult,
    TimelineReconstructionRunner,
)
from infoscope.services.deduplication import DeduplicationResult, ExactDeduplicationRunner
from infoscope.services.event_localization_worker import (
    EventLocalizationRepository,
    EventLocalizationRunner,
)
from infoscope.services.event_reconstruction import (
    EventReconstructionResult,
    EventReconstructionRunner,
    EventRepository,
)
from infoscope.services.maintenance import (
    MAINTENANCE_BACKWRITE_NAMESPACE,
    MAINTENANCE_PHASES,
    MaintenanceError,
    MaintenanceRepository,
    MaintenanceRunner,
)
from infoscope.services.model_settings import (
    analysis_config_for_selection,
    analysis_config_for_user,
    shared_fact_analysis_config,
)
from infoscope.services.normalization import NormalizationResult, NormalizationRunner
from infoscope.services.personalization import (
    PersonalizationRepository,
    PersonalizationRunner,
    PersonalizationVisibleEventSnapshotProvider,
)
from infoscope.services.pipeline import PipelineRepository
from infoscope.services.research import ResearchRepository, ResearchRunner
from infoscope.services.window_analysis import WindowAnalysisRunner, WindowRunResult
from infoscope.services.worker_health import record_worker_heartbeat, remove_worker_heartbeat

logger = logging.getLogger("infoscope.worker")
QueueProcessor = Callable[[], Awaitable[bool]]


async def _run_heartbeat(
    worker_id: UUID,
    process_started_at: datetime,
    interval_seconds: float,
    stop: asyncio.Event,
) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        except TimeoutError:
            try:
                await record_worker_heartbeat(worker_id, process_started_at)
            except Exception:
                logger.exception("worker heartbeat update failed worker_id=%s", worker_id)


async def _process_queue_once(name: str, processor: QueueProcessor) -> bool:
    try:
        return await processor()
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("%s queue stage failed", name)
        return False


async def _run_serial_queue_group(
    processors: tuple[tuple[str, QueueProcessor], ...],
) -> bool:
    processed = False
    for name, processor in processors:
        processed = await _process_queue_once(name, processor) or processed
    return processed


async def _run_queue_lane(
    name: str,
    processor: QueueProcessor,
    stop: asyncio.Event,
    poll_seconds: float,
) -> None:
    while not stop.is_set():
        processed = await _process_queue_once(name, processor)
        if processed:
            continue
        try:
            await asyncio.wait_for(stop.wait(), timeout=poll_seconds)
        except TimeoutError:
            continue


async def _run_queue_lanes(
    processors: tuple[tuple[str, QueueProcessor], ...],
    stop: asyncio.Event,
    poll_seconds: float,
) -> None:
    tasks = [
        asyncio.create_task(
            _run_queue_lane(name, processor, stop, poll_seconds),
            name=f"infoscope-queue-{name}",
        )
        for name, processor in processors
    ]
    try:
        await stop.wait()
    finally:
        stop.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def collect_trendradar_once() -> None:
    settings = get_settings()
    config = load_trendradar_config(settings.resolved_trendradar_config_path)
    async with httpx.AsyncClient(follow_redirects=True, trust_env=False) as client:
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


async def analyze_windows_once(
    *,
    retry_run_id: UUID | None = None,
    replay_run_id: UUID | None = None,
) -> WindowRunResult:
    if retry_run_id is not None and replay_run_id is not None:
        raise ValueError("retry_run_id and replay_run_id are mutually exclusive")
    settings = get_settings()
    config = shared_fact_analysis_config(settings)
    async with httpx.AsyncClient(trust_env=False) as client:
        async with session_factory() as database:
            runner = WindowAnalysisRunner(
                acquisition=AcquisitionRepository(database),
                pipeline=PipelineRepository(database),
                client=DeepSeekAnalysisClient(client=client, config=config),
                max_signals=settings.window_analysis_max_signals,
                max_input_chars=settings.window_analysis_max_input_chars,
                max_batches=settings.window_analysis_max_batches,
                batch_concurrency=settings.window_analysis_batch_concurrency,
            )
            if retry_run_id is not None:
                result = await runner.retry_run(retry_run_id)
            elif replay_run_id is not None:
                result = await runner.replay_run(replay_run_id)
            else:
                result = await runner.run_available(
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


async def reconstruct_event_once(source_artifact_id: UUID) -> EventReconstructionResult:
    settings = get_settings()
    config = shared_fact_analysis_config(settings)
    async with httpx.AsyncClient(trust_env=False) as client:
        async with session_factory() as database:
            result = await EventReconstructionRunner(
                events=EventRepository(database),
                pipeline=PipelineRepository(database),
                client=DeepSeekEventReconstructionClient(client=client, config=config),
                candidate_limit=settings.event_reconstruction_candidate_limit,
            ).reconstruct(source_artifact_id)
    logger.info(
        "event reconstruction complete run_id=%s created=%d updated=%d attached=%d reused=%s",
        result.run_id,
        result.events_created,
        result.events_updated,
        result.signals_attached,
        result.reused_artifact,
    )
    return result


async def extract_claims_once(source_artifact_id: UUID) -> IntelligenceResult:
    config = shared_fact_analysis_config(get_settings())
    async with httpx.AsyncClient(trust_env=False) as client:
        async with session_factory() as database:
            result = await ClaimExtractionRunner(
                repository=IntelligenceRepository(database),
                pipeline=PipelineRepository(database),
                client=DeepSeekIntelligenceClient(client=client, config=config),
            ).run(source_artifact_id)
    logger.info(
        "claim extraction complete run_id=%s created=%d updated=%d attached=%d reused=%s",
        result.run_id,
        result.created,
        result.updated,
        result.attached,
        result.reused_artifact,
    )
    return result


async def reconstruct_timeline_once(source_artifact_id: UUID) -> IntelligenceResult:
    config = shared_fact_analysis_config(get_settings())
    async with httpx.AsyncClient(trust_env=False) as client:
        async with session_factory() as database:
            result = await TimelineReconstructionRunner(
                repository=IntelligenceRepository(database),
                pipeline=PipelineRepository(database),
                client=DeepSeekIntelligenceClient(client=client, config=config),
            ).run(source_artifact_id)
    logger.info(
        "timeline reconstruction complete run_id=%s created=%d updated=%d attached=%d reused=%s",
        result.run_id,
        result.created,
        result.updated,
        result.attached,
        result.reused_artifact,
    )
    return result


async def analyze_conflicts_once(source_artifact_id: UUID) -> IntelligenceResult:
    config = shared_fact_analysis_config(get_settings())
    async with httpx.AsyncClient(trust_env=False) as client:
        async with session_factory() as database:
            result = await ConflictAnalysisRunner(
                repository=IntelligenceRepository(database),
                pipeline=PipelineRepository(database),
                client=DeepSeekIntelligenceClient(client=client, config=config),
            ).run(source_artifact_id)
    logger.info(
        "conflict analysis complete run_id=%s created=%d updated=%d attached=%d reused=%s",
        result.run_id,
        result.created,
        result.updated,
        result.attached,
        result.reused_artifact,
    )
    return result


async def analyze_base_once(source_artifact_id: UUID) -> IntelligenceResult:
    config = shared_fact_analysis_config(get_settings())
    async with httpx.AsyncClient(trust_env=False) as client:
        async with session_factory() as database:
            result = await BaseAnalysisRunner(
                repository=BaseAnalysisRepository(database),
                pipeline=PipelineRepository(database),
                client=DeepSeekIntelligenceClient(client=client, config=config),
            ).run(source_artifact_id)
    logger.info(
        "base analysis complete run_id=%s created=%d updated=%d reused=%s",
        result.run_id,
        result.created,
        result.updated,
        result.reused_artifact,
    )
    return result


async def research_once(
    *,
    request_file: Path | None = None,
    retry_request_id: UUID | None = None,
) -> None:
    if (request_file is None) == (retry_request_id is None):
        raise ValueError("exactly one research request input is required")
    settings = get_settings()
    config = research_runtime_config()
    timeout = httpx.Timeout(connect=10, read=30, write=10, pool=10)
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
        trust_env=False,
    ) as client:
        async with session_factory() as database:
            runner = ResearchRunner(
                repository=ResearchRepository(database),
                acquisition=AcquisitionRepository(database),
                client=OpenClawResearchClient(config),
                fetcher=DirectHTTPSResearchFetcher(client),
                max_attempts=settings.research_max_attempts,
                health_checker=AgentReachHealthChecker(
                    settings.research_agent_reach_executable,
                    state_dir=settings.resolved_research_openclaw_state_dir,
                ),
            )
            if request_file is not None:
                request_document = await asyncio.to_thread(request_file.read_text, "utf-8")
                spec = ResearchRequestSpec.model_validate_json(request_document)
                request = await runner.create_and_run(spec)
            else:
                request = await runner.run(retry_request_id)  # type: ignore[arg-type]
    logger.info(
        "research complete request_id=%s status=%s attempts=%d error_code=%s",
        request.id,
        request.status,
        request.attempt_count,
        request.error_code,
    )


async def check_research_capability_once() -> None:
    await research_capability_checker().check()
    logger.info("research capability ready")


async def compare_ask_once(
    *,
    request_file: Path | None = None,
    retry_request_id: UUID | None = None,
) -> None:
    if (request_file is None) == (retry_request_id is None):
        raise ValueError("exactly one Ask comparison request input is required")
    settings = get_settings()
    async with httpx.AsyncClient(trust_env=False) as client:
        async with session_factory() as database:
            if request_file is not None:
                request_document = await asyncio.to_thread(request_file.read_text, "utf-8")
                spec = AskRequestSpec.model_validate_json(request_document)
                user_id = spec.user_id
            else:
                existing = await database.get(AskRequest, retry_request_id)
                if existing is None:
                    raise ValueError("Ask request not found")
                user_id = existing.user_id
            config = await analysis_config_for_user(database, user_id, settings)
            runner = AskComparisonRunner(
                repository=AskComparisonRepository(database),
                client=DeepSeekIntelligenceClient(client=client, config=config),
                max_attempts=settings.ask_comparison_max_attempts,
                research_capability_check=research_capability_checker().check,
            )
            if request_file is not None:
                request = await runner.create_and_run(spec)
            else:
                request = await runner.run(retry_request_id)  # type: ignore[arg-type]
    logger.info(
        "Ask comparison complete request_id=%s status=%s stage=%s attempts=%d error_code=%s",
        request.id,
        request.status,
        request.stage,
        request.attempt_count,
        request.error_code,
    )


async def run_ask_research_bridge_once(ask_id: UUID) -> None:
    settings = get_settings()
    config = research_runtime_config()
    timeout = httpx.Timeout(connect=10, read=30, write=10, pool=10)
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
        trust_env=False,
    ) as client:
        async with session_factory() as database:
            acquisition = AcquisitionRepository(database)
            research_repository = ResearchRepository(database)
            ask_request = await database.get(AskRequest, ask_id)
            use_grok = bool(ask_request and ask_request.grok_enabled)
            grok_client = (
                GrokBuildResearchClient(
                    GrokBuildConfig(
                        executable=settings.research_grok_executable,
                        model=settings.research_grok_model,
                        timeout_seconds=settings.research_grok_timeout_seconds,
                    )
                )
                if use_grok
                else None
            )
            research_runner = ResearchRunner(
                repository=research_repository,
                acquisition=acquisition,
                client=grok_client or OpenClawResearchClient(config),
                fetcher=grok_client or DirectHTTPSResearchFetcher(client),
                max_attempts=settings.research_max_attempts,
                health_checker=None
                if use_grok
                else AgentReachHealthChecker(
                    settings.research_agent_reach_executable,
                    state_dir=settings.resolved_research_openclaw_state_dir,
                ),
            )
            request = await AskResearchBridgeRunner(
                repository=AskResearchBridgeRepository(database),
                research_repository=research_repository,
                research_runner=research_runner,
                acquisition=acquisition,
                max_attempts=settings.ask_research_bridge_max_attempts,
                research_max_attempts=settings.research_max_attempts,
            ).run(ask_id)
    logger.info(
        "Ask Research Bridge complete request_id=%s status=%s stage=%s error_code=%s",
        request.id,
        request.status,
        request.stage,
        request.error_code,
    )


async def run_ask_event_reconciliation_once(ask_id: UUID) -> None:
    settings = get_settings()
    async with httpx.AsyncClient(trust_env=False) as client:
        async with session_factory() as database:
            request = await database.get(AskRequest, ask_id)
            if request is None:
                raise ValueError("Ask request not found")
            config = await analysis_config_for_user(database, request.user_id, settings)
            request = await AskEventReconciliationRunner(
                repository=AskEventReconciliationRepository(database),
                client=DeepSeekIntelligenceClient(client=client, config=config),
                max_attempts=settings.ask_event_reconciliation_max_attempts,
            ).run(ask_id)
    logger.info(
        "Ask Event Reconciliation complete request_id=%s status=%s stage=%s error_code=%s",
        request.id,
        request.status,
        request.stage,
        request.error_code,
    )


async def run_ask_finalization_once(ask_id: UUID) -> None:
    settings = get_settings()
    async with httpx.AsyncClient(trust_env=False) as client:
        async with session_factory() as database:
            request = await database.get(AskRequest, ask_id)
            if request is None:
                raise ValueError("Ask request not found")
            config = await analysis_config_for_user(database, request.user_id, settings)
            request = await AskFinalizationRunner(
                repository=AskFinalizationRepository(database),
                client=DeepSeekIntelligenceClient(client=client, config=config),
                max_attempts=settings.ask_finalization_max_attempts,
            ).run(ask_id)
    logger.info(
        "Ask Finalization complete request_id=%s status=%s stage=%s error_code=%s",
        request.id,
        request.status,
        request.stage,
        request.error_code,
    )


async def run_backwrite_spec_once(
    spec: BackwriteSnapshotSpec,
    *,
    provider: UserVisibleEventSnapshotProvider,
) -> None:
    settings = get_settings()
    async with session_factory() as database:
        cycle, _inserted = await BackwriteRepository(
            database,
            stale_after=timedelta(seconds=settings.maintenance_stale_after_seconds),
        ).create_or_reuse_cycle(
            spec,
            provider=provider,
            max_attempts=settings.backwrite_max_attempts,
        )
    if cycle.item_count == 0:
        logger.info(
            "Backwrite cycle complete cycle_id=%s status=%s item_count=0 error_code=%s",
            cycle.id,
            cycle.status,
            cycle.error_code,
        )
        return
    analysis_config = shared_fact_analysis_config(settings)
    openclaw_config = research_runtime_config()
    timeout = httpx.Timeout(connect=10, read=30, write=10, pool=10)
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
        trust_env=False,
    ) as research_client:
        async with httpx.AsyncClient(trust_env=False) as analysis_client:
            async with session_factory() as database:
                acquisition = AcquisitionRepository(database)
                research_repository = ResearchRepository(database)
                research_runner = ResearchRunner(
                    repository=research_repository,
                    acquisition=acquisition,
                    client=OpenClawResearchClient(openclaw_config),
                    fetcher=DirectHTTPSResearchFetcher(research_client),
                    max_attempts=settings.research_max_attempts,
                    health_checker=AgentReachHealthChecker(
                        settings.research_agent_reach_executable,
                        state_dir=settings.resolved_research_openclaw_state_dir,
                    ),
                )
                repository = BackwriteRepository(
                    database,
                    stale_after=timedelta(seconds=settings.maintenance_stale_after_seconds),
                )
                cycle = await BackwriteRunner(
                    repository=repository,
                    research_repository=research_repository,
                    research_runner=research_runner,
                    acquisition=acquisition,
                    client=DeepSeekIntelligenceClient(
                        client=analysis_client,
                        config=analysis_config,
                    ),
                    max_attempts=settings.backwrite_max_attempts,
                ).run_cycle(cycle.id)
    if cycle.status != "completed":
        raise MaintenanceError(cycle.error_code or "MAINTENANCE_BACKWRITE_FAILED")
    logger.info(
        "Backwrite cycle complete cycle_id=%s status=%s item_count=%d error_code=%s",
        cycle.id,
        cycle.status,
        cycle.item_count,
        cycle.error_code,
    )


async def run_backwrite_snapshot_once(snapshot_file: Path) -> None:
    document = await asyncio.to_thread(snapshot_file.read_text, "utf-8")
    spec = BackwriteSnapshotSpec.model_validate_json(document)
    await run_backwrite_spec_once(
        spec,
        provider=UnavailableUserVisibleEventSnapshotProvider(),
    )


async def personalize_user_once(user_id: UUID) -> None:
    settings = get_settings()
    async with httpx.AsyncClient(trust_env=False) as client:
        async with session_factory() as database:
            config = await analysis_config_for_user(database, user_id, settings)
            runner = PersonalizationRunner(
                PersonalizationRepository(database),
                DeepSeekIntelligenceClient(client=client, config=config),
                max_attempts=settings.personalization_max_attempts,
                batch_size=settings.personalization_batch_size,
                batch_concurrency=settings.personalization_batch_concurrency,
            )
            while True:
                run = await runner.run_user(user_id)
                if run.status != "pending":
                    break
    logger.info(
        "personalization run complete run_id=%s user_id=%s status=%s error_code=%s",
        run.id,
        user_id,
        run.status,
        run.error_code,
    )
    if run.status != "completed":
        raise MaintenanceError(run.error_code or "PERSONALIZATION_FAILED")


async def process_personalization_queue_once() -> bool:
    async with session_factory() as database:
        user_id = (
            await database.execute(
                select(User.id)
                .where(
                    User.onboarding_completed.is_(True),
                    User.personalization_update_requested_at.is_not(None),
                )
                .order_by(User.personalization_update_requested_at, User.id)
                .limit(1)
            )
        ).scalar_one_or_none()
    if user_id is None:
        return False
    await personalize_user_once(user_id)
    return True


async def generate_brief_once(user_id: UUID) -> None:
    settings = get_settings()
    async with httpx.AsyncClient(trust_env=False) as client:
        async with session_factory() as database:
            config = await analysis_config_for_user(database, user_id, settings)
            runner = BriefRunner(
                BriefRepository(database),
                DeepSeekIntelligenceClient(client=client, config=config),
                max_attempts=settings.brief_max_attempts,
            )
            while True:
                run = await runner.run_user(user_id)
                if run.status != "pending":
                    break
    logger.info(
        "brief run complete run_id=%s user_id=%s status=%s error_code=%s",
        run.id,
        user_id,
        run.status,
        run.error_code,
    )


async def process_brief_queue_once() -> bool:
    async with session_factory() as database:
        user_ids = list(
            (
                await database.execute(
                    select(User.id).where(User.onboarding_completed.is_(True)).order_by(User.id)
                )
            ).scalars()
        )
        repository = BriefRepository(database)
        user_id = None
        for candidate_id in user_ids:
            source = await repository.latest_personalization_artifact(candidate_id)
            if source is None:
                continue
            prior = (
                await database.execute(
                    select(BriefRun).where(BriefRun.source_personalization_artifact_id == source.id)
                )
            ).scalar_one_or_none()
            if prior is None or prior.status == "pending":
                user_id = candidate_id
                break
    if user_id is None:
        return False
    await generate_brief_once(user_id)
    return True


async def localize_events_once() -> EventLocalizationRun:
    settings = get_settings()
    config = analysis_config_for_selection(
        settings,
        ModelSelection(source_id="ai_ping", model_id="DeepSeek-V4-Flash-0731"),
    )
    async with httpx.AsyncClient(trust_env=False) as client:
        run = await EventLocalizationRunner(
            session_factory,
            EventLocalizationClient(client=client, config=config),
            provider=config.provider,
            model=config.model,
            batch_size=settings.event_localization_batch_size,
            batch_concurrency=settings.event_localization_batch_concurrency,
            max_attempts=settings.event_localization_max_attempts,
            stale_after=timedelta(
                seconds=max(settings.analysis_timeout_seconds + 60, 300)
            ),
        ).run()
    logger.info(
        "event localization run status run_id=%s status=%s completed=%d failed=%d total=%d",
        run.id,
        run.status,
        run.completed_batch_count,
        run.failed_batch_count,
        run.batch_count,
    )
    return run


async def process_event_localization_queue_once() -> bool:
    async with session_factory() as database:
        if not await EventLocalizationRepository(database).localization_needed():
            return False
    await localize_events_once()
    return True


async def _derived_artifact(source_artifact_id: UUID, artifact_type: str) -> PipelineArtifact:
    async with session_factory() as database:
        artifact = (
            await database.execute(
                select(PipelineArtifact).where(
                    PipelineArtifact.source_artifact_id == source_artifact_id,
                    PipelineArtifact.artifact_type == artifact_type,
                )
            )
        ).scalar_one_or_none()
    if artifact is None:
        raise MaintenanceError("MAINTENANCE_FACT_PIPELINE_INCOMPLETE")
    return artifact


async def reconcile_window_artifacts_once() -> None:
    settings = get_settings()
    recovery_time = datetime.now(UTC)
    async with session_factory() as database:
        recovered = await PipelineRepository(database).recover_stale_running(
            stale_before=recovery_time
            - timedelta(seconds=settings.maintenance_stale_after_seconds),
            finished_at=recovery_time,
        )
        if recovered:
            logger.warning(
                "recovered stale pipeline runs count=%d error_code=PIPELINE_WORKER_LOST",
                len(recovered),
            )
        windows = list(
            (
                await database.execute(
                    select(PipelineArtifact)
                    .join(PipelineRun, PipelineRun.id == PipelineArtifact.pipeline_run_id)
                    .where(
                        PipelineRun.status == PipelineRunStatus.SUCCEEDED.value,
                        or_(
                            and_(
                                PipelineArtifact.artifact_type == "window_analysis",
                                PipelineArtifact.schema_version == "window_analysis.v1",
                            ),
                            and_(
                                PipelineArtifact.artifact_type == "window_analysis_batch",
                                PipelineArtifact.schema_version == "window_analysis_batch.v2",
                            ),
                        ),
                    )
                    .order_by(
                        PipelineRun.window_start,
                        PipelineArtifact.artifact_key,
                        PipelineArtifact.id,
                    )
                )
            ).scalars()
        )
    for window in windows:
        if window.artifact_type == "window_analysis_batch":
            payload = WindowAnalysisBatchArtifact.model_validate(window.payload).model_output
        else:
            payload = WindowAnalysisPayload.model_validate(window.payload)
        if not payload.signal_analyses:
            continue
        try:
            reconstruction = await _derived_artifact(window.id, "event_reconstruction")
        except MaintenanceError:
            await reconstruct_event_once(window.id)
            reconstruction = await _derived_artifact(window.id, "event_reconstruction")
        try:
            claims = await _derived_artifact(reconstruction.id, "claim_extraction")
        except MaintenanceError:
            await extract_claims_once(reconstruction.id)
            claims = await _derived_artifact(reconstruction.id, "claim_extraction")
        try:
            timeline = await _derived_artifact(claims.id, "timeline_reconstruction")
        except MaintenanceError:
            await reconstruct_timeline_once(claims.id)
            timeline = await _derived_artifact(claims.id, "timeline_reconstruction")
        try:
            conflicts = await _derived_artifact(timeline.id, "conflict_analysis")
        except MaintenanceError:
            await analyze_conflicts_once(timeline.id)
            conflicts = await _derived_artifact(timeline.id, "conflict_analysis")
        try:
            await _derived_artifact(conflicts.id, "base_analysis")
        except MaintenanceError:
            await analyze_base_once(conflicts.id)
            await _derived_artifact(conflicts.id, "base_analysis")


async def process_maintenance_queue_once(
    *,
    snapshot_provider: UserVisibleEventSnapshotProvider | None = None,
) -> bool:
    settings = get_settings()

    async def heartbeat(run_id: UUID, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=settings.worker_heartbeat_seconds)
            except TimeoutError:
                try:
                    async with session_factory() as heartbeat_database:
                        await heartbeat_database.execute(
                            update(MaintenanceRun)
                            .where(
                                MaintenanceRun.id == run_id,
                                MaintenanceRun.status == "running",
                            )
                            .values(updated_at=func.now())
                        )
                        await heartbeat_database.commit()
                except Exception:
                    logger.exception("Maintenance heartbeat failed run_id=%s", run_id)

    async with session_factory() as database:
        provider = snapshot_provider or PersonalizationVisibleEventSnapshotProvider(database)
        repository = MaintenanceRepository(
            database,
            stale_after=timedelta(seconds=settings.maintenance_stale_after_seconds),
        )
        await repository.enqueue_due()

        async def window_analysis(_run: MaintenanceRun) -> None:
            result = await analyze_windows_once()
            if result.windows_failed:
                raise MaintenanceError("MAINTENANCE_WINDOW_ANALYSIS_FAILED")

        async def reconciliation(_run: MaintenanceRun) -> None:
            await reconcile_window_artifacts_once()

        async def event_backwrite(run: MaintenanceRun) -> None:
            async with session_factory() as user_database:
                user_ids = list(
                    (
                        await user_database.execute(
                            select(User.id)
                            .where(User.onboarding_completed.is_(True))
                            .order_by(User.id)
                        )
                    ).scalars()
                )
            for user_id in user_ids:
                await run_backwrite_spec_once(
                    BackwriteSnapshotSpec(
                        user_id=user_id,
                        idempotency_key=uuid5(
                            MAINTENANCE_BACKWRITE_NAMESPACE,
                            f"{run.id}:{user_id}:event_backwrite.v1",
                        ),
                    ),
                    provider=provider,
                )

        async def personalization(_run: MaintenanceRun) -> None:
            async with session_factory() as user_database:
                user_ids = list(
                    (
                        await user_database.execute(
                            select(User.id)
                            .where(User.onboarding_completed.is_(True))
                            .order_by(User.id)
                        )
                    ).scalars()
                )
            for user_id in user_ids:
                await personalize_user_once(user_id)

        result = await MaintenanceRunner(
            repository,
            dict(
                zip(
                    MAINTENANCE_PHASES,
                    (window_analysis, reconciliation, event_backwrite, personalization),
                    strict=True,
                )
            ),
            heartbeat=heartbeat,
        ).run_next()
    if result is None:
        return False
    logger.info(
        "maintenance run complete run_id=%s status=%s error_code=%s",
        result.id,
        result.status,
        result.error_code,
    )
    return True


async def process_ask_queue_once() -> bool:
    async with session_factory() as database:
        request = (
            await database.execute(
                select(AskRequest)
                .where(AskRequest.status == "pending")
                .order_by(AskRequest.created_at, AskRequest.id)
                .limit(1)
            )
        ).scalar_one_or_none()
    if request is None:
        return False
    try:
        if request.stage == "comparing":
            await compare_ask_once(retry_request_id=request.id)
        elif request.stage == "awaiting_research":
            await run_ask_research_bridge_once(request.id)
        elif request.stage == "awaiting_reconciliation":
            await run_ask_event_reconciliation_once(request.id)
        elif request.stage == "finalizing":
            await run_ask_finalization_once(request.id)
        else:
            logger.error(
                "Ask has unsupported stage request_id=%s stage=%s", request.id, request.stage
            )
            return False
    except Exception:
        logger.exception("Ask queue stage failed request_id=%s stage=%s", request.id, request.stage)
    return True


async def run(
    *,
    once: bool = False,
    collect_trendradar: bool = False,
    collect_telegram: bool = False,
    normalize: bool = False,
    retry_normalization: bool = False,
    deduplicate: bool = False,
    analyze_windows: bool = False,
    retry_window_run: UUID | None = None,
    replay_window_run: UUID | None = None,
    reconcile_windows: bool = False,
    reconstruct_window_artifact: UUID | None = None,
    extract_claims_artifact: UUID | None = None,
    reconstruct_timeline_artifact: UUID | None = None,
    analyze_conflicts_artifact: UUID | None = None,
    analyze_base_artifact: UUID | None = None,
    research_request_file: Path | None = None,
    retry_research_request: UUID | None = None,
    ask_comparison_request_file: Path | None = None,
    retry_ask_comparison: UUID | None = None,
    ask_research_bridge: UUID | None = None,
    ask_event_reconciliation: UUID | None = None,
    ask_finalization: UUID | None = None,
    process_ask_queue: bool = False,
    process_maintenance_queue: bool = False,
    process_personalization_queue: bool = False,
    personalize_user: UUID | None = None,
    process_brief_queue: bool = False,
    generate_brief_user: UUID | None = None,
    localize_events: bool = False,
    process_event_localization_queue: bool = False,
    backwrite_snapshot_file: Path | None = None,
) -> None:
    settings = get_settings()
    stop = asyncio.Event()
    heartbeat_stop = asyncio.Event()
    heartbeat_task: asyncio.Task[None] | None = None
    worker_id: UUID | None = None
    loop = asyncio.get_running_loop()

    for signal_name in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signal_name, stop.set)

    single_run_requested = any(
        (
            once,
            collect_trendradar,
            collect_telegram,
            normalize,
            retry_normalization,
            deduplicate,
            analyze_windows,
            retry_window_run is not None,
            replay_window_run is not None,
            reconcile_windows,
            reconstruct_window_artifact is not None,
            extract_claims_artifact is not None,
            reconstruct_timeline_artifact is not None,
            analyze_conflicts_artifact is not None,
            analyze_base_artifact is not None,
            research_request_file is not None,
            retry_research_request is not None,
            ask_comparison_request_file is not None,
            retry_ask_comparison is not None,
            ask_research_bridge is not None,
            ask_event_reconciliation is not None,
            ask_finalization is not None,
            backwrite_snapshot_file is not None,
            personalize_user is not None,
            generate_brief_user is not None,
            localize_events,
        )
    )

    try:
        is_queue_worker = any(
            (
                process_ask_queue,
                process_maintenance_queue,
                process_personalization_queue,
                process_brief_queue,
                process_event_localization_queue,
            )
        )
        if is_queue_worker:
            worker_id = uuid4()
            process_started_at = datetime.now(UTC)
            await record_worker_heartbeat(worker_id, process_started_at)
            heartbeat_task = asyncio.create_task(
                _run_heartbeat(
                    worker_id,
                    process_started_at,
                    settings.worker_heartbeat_seconds,
                    heartbeat_stop,
                )
            )
        if is_queue_worker and not single_run_requested:
            await ping_database()
            queue_lanes: list[tuple[str, QueueProcessor]] = []
            if process_ask_queue:
                queue_lanes.append(("Ask", process_ask_queue_once))
            if process_event_localization_queue:
                queue_lanes.append(
                    ("Event localization", process_event_localization_queue_once)
                )
            core_processors: list[tuple[str, QueueProcessor]] = []
            if process_personalization_queue:
                core_processors.append(
                    ("Personalization", process_personalization_queue_once)
                )
            if process_brief_queue:
                core_processors.append(("Brief", process_brief_queue_once))
            if process_maintenance_queue:
                core_processors.append(("Maintenance", process_maintenance_queue_once))
            if core_processors:
                frozen_core_processors = tuple(core_processors)

                async def process_core_queue_once() -> bool:
                    return await _run_serial_queue_group(frozen_core_processors)

                queue_lanes.append(("Core background", process_core_queue_once))
            await _run_queue_lanes(
                tuple(queue_lanes),
                stop,
                settings.worker_poll_seconds,
            )
            return
        while not stop.is_set():
            ask_processed = False
            localization_processed = False
            await ping_database()
            if collect_trendradar:
                await collect_trendradar_once()
            if collect_telegram:
                await collect_telegram_once()
            if normalize or retry_normalization:
                await normalize_once(retry_failed=retry_normalization)
            if deduplicate:
                await deduplicate_once()
            if analyze_windows or retry_window_run is not None or replay_window_run is not None:
                await analyze_windows_once(
                    retry_run_id=retry_window_run,
                    replay_run_id=replay_window_run,
                )
            if reconcile_windows:
                await reconcile_window_artifacts_once()
            if reconstruct_window_artifact is not None:
                await reconstruct_event_once(reconstruct_window_artifact)
            if extract_claims_artifact is not None:
                await extract_claims_once(extract_claims_artifact)
            if reconstruct_timeline_artifact is not None:
                await reconstruct_timeline_once(reconstruct_timeline_artifact)
            if analyze_conflicts_artifact is not None:
                await analyze_conflicts_once(analyze_conflicts_artifact)
            if analyze_base_artifact is not None:
                await analyze_base_once(analyze_base_artifact)
            if research_request_file is not None or retry_research_request is not None:
                await research_once(
                    request_file=research_request_file,
                    retry_request_id=retry_research_request,
                )
            if ask_comparison_request_file is not None or retry_ask_comparison is not None:
                await compare_ask_once(
                    request_file=ask_comparison_request_file,
                    retry_request_id=retry_ask_comparison,
                )
            if ask_research_bridge is not None:
                await run_ask_research_bridge_once(ask_research_bridge)
            if ask_event_reconciliation is not None:
                await run_ask_event_reconciliation_once(ask_event_reconciliation)
            if ask_finalization is not None:
                await run_ask_finalization_once(ask_finalization)
            if process_ask_queue:
                ask_processed = await process_ask_queue_once()
            if process_event_localization_queue:
                try:
                    localization_processed = await process_event_localization_queue_once()
                except Exception:
                    logger.exception("Event localization queue stage failed")
            if localize_events:
                await localize_events_once()
            if process_personalization_queue:
                try:
                    await process_personalization_queue_once()
                except Exception:
                    logger.exception("Personalization queue stage failed")
            if personalize_user is not None:
                await personalize_user_once(personalize_user)
            if process_brief_queue:
                try:
                    await process_brief_queue_once()
                except Exception:
                    logger.exception("Brief queue stage failed")
            if generate_brief_user is not None:
                await generate_brief_once(generate_brief_user)
            if process_maintenance_queue:
                try:
                    await process_maintenance_queue_once()
                except Exception:
                    logger.exception("Maintenance queue stage failed")
            if backwrite_snapshot_file is not None:
                await run_backwrite_snapshot_once(backwrite_snapshot_file)
            logger.info("worker heartbeat")
            if single_run_requested:
                return
            if ask_processed or localization_processed:
                continue
            try:
                await asyncio.wait_for(stop.wait(), timeout=settings.worker_poll_seconds)
            except TimeoutError:
                continue
    finally:
        heartbeat_stop.set()
        if heartbeat_task is not None:
            await heartbeat_task
        if worker_id is not None:
            try:
                await remove_worker_heartbeat(worker_id)
            except Exception:
                logger.exception("failed to remove worker heartbeat worker_id=%s", worker_id)
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
    parser.add_argument(
        "--check-research-capability",
        action="store_true",
        help="Validate the isolated OpenClaw and Agent-Reach runtime and exit",
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
    window_group = parser.add_mutually_exclusive_group()
    window_group.add_argument(
        "--analyze-windows",
        action="store_true",
        help="Analyze available complete one-hour windows",
    )
    window_group.add_argument(
        "--retry-window-run",
        type=UUID,
        metavar="RUN_ID",
        help="Immediately retry one failed Window Analysis run",
    )
    window_group.add_argument(
        "--replay-window-run",
        type=UUID,
        metavar="RUN_ID",
        help="Replay one terminal Window Analysis run without recollection",
    )
    parser.add_argument(
        "--reconcile-windows",
        action="store_true",
        help="Complete Event and fact reconstruction for successful Window Analysis batches",
    )
    parser.add_argument(
        "--reconstruct-window-artifact",
        type=UUID,
        metavar="ARTIFACT_ID",
        help="Reconstruct Events from one successful Window Analysis artifact",
    )
    parser.add_argument(
        "--extract-claims-artifact",
        type=UUID,
        metavar="ARTIFACT_ID",
        help="Extract Claims from one canonical Event Reconstruction artifact",
    )
    parser.add_argument(
        "--reconstruct-timeline-artifact",
        type=UUID,
        metavar="ARTIFACT_ID",
        help="Reconstruct Timeline from one canonical Claim Extraction artifact",
    )
    parser.add_argument(
        "--analyze-conflicts-artifact",
        type=UUID,
        metavar="ARTIFACT_ID",
        help="Analyze Conflicts from one canonical Timeline Reconstruction artifact",
    )
    parser.add_argument(
        "--analyze-base-artifact",
        type=UUID,
        metavar="ARTIFACT_ID",
        help="Create Base Analysis from one canonical Conflict Analysis artifact",
    )
    research_group = parser.add_mutually_exclusive_group()
    research_group.add_argument(
        "--research-request-file",
        type=Path,
        metavar="JSON_FILE",
        help="Run one frozen internal Research request from JSON",
    )
    research_group.add_argument(
        "--retry-research-request",
        type=UUID,
        metavar="REQUEST_ID",
        help="Retry failed sources for one Research request",
    )
    ask_group = parser.add_mutually_exclusive_group()
    ask_group.add_argument(
        "--ask-comparison-request-file",
        type=Path,
        metavar="JSON_FILE",
        help="Run one frozen internal Ask comparison request from JSON",
    )
    ask_group.add_argument(
        "--retry-ask-comparison",
        type=UUID,
        metavar="REQUEST_ID",
        help="Retry one failed Ask Database Comparison request",
    )
    parser.add_argument(
        "--run-ask-research-bridge",
        type=UUID,
        metavar="ASK_ID",
        help="Run or retry the frozen Research Bridge for one Ask request",
    )
    parser.add_argument(
        "--run-ask-event-reconciliation",
        type=UUID,
        metavar="ASK_ID",
        help="Run or retry Event Reconciliation for one researched Ask request",
    )
    parser.add_argument(
        "--run-ask-finalization",
        type=UUID,
        metavar="ASK_ID",
        help="Run or retry Finalization for one Ask request",
    )
    parser.add_argument(
        "--process-ask-queue",
        action="store_true",
        help="Continuously process persisted pending Ask requests",
    )
    parser.add_argument(
        "--process-maintenance-queue",
        action="store_true",
        help="Continuously schedule and process persisted Maintenance runs",
    )
    parser.add_argument(
        "--process-personalization-queue",
        action="store_true",
        help="Continuously process users awaiting Personalization refresh",
    )
    parser.add_argument(
        "--personalize-user",
        type=UUID,
        metavar="USER_ID",
        help="Run or retry Personalization for one ready user and exit",
    )
    parser.add_argument(
        "--process-brief-queue",
        action="store_true",
        help="Continuously generate Briefs for completed Personalization snapshots",
    )
    parser.add_argument(
        "--generate-brief-user",
        type=UUID,
        metavar="USER_ID",
        help="Run or retry Brief generation for one ready user and exit",
    )
    localization_group = parser.add_mutually_exclusive_group()
    localization_group.add_argument(
        "--localize-events",
        action="store_true",
        help="Localize the current Event snapshot into zh-CN and exit",
    )
    localization_group.add_argument(
        "--process-event-localization-queue",
        action="store_true",
        help="Continuously localize stale or missing zh-CN Event projections",
    )
    parser.add_argument(
        "--backwrite-snapshot-file",
        type=Path,
        metavar="JSON_FILE",
        help="Run one Backend-produced frozen Backwrite Event snapshot",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    if args.check_research_capability:
        asyncio.run(check_research_capability_once())
    elif args.telegram_login:
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
                retry_window_run=args.retry_window_run,
                replay_window_run=args.replay_window_run,
                reconcile_windows=args.reconcile_windows,
                reconstruct_window_artifact=args.reconstruct_window_artifact,
                extract_claims_artifact=args.extract_claims_artifact,
                reconstruct_timeline_artifact=args.reconstruct_timeline_artifact,
                analyze_conflicts_artifact=args.analyze_conflicts_artifact,
                analyze_base_artifact=args.analyze_base_artifact,
                research_request_file=args.research_request_file,
                retry_research_request=args.retry_research_request,
                ask_comparison_request_file=args.ask_comparison_request_file,
                retry_ask_comparison=args.retry_ask_comparison,
                ask_research_bridge=args.run_ask_research_bridge,
                ask_event_reconciliation=args.run_ask_event_reconciliation,
                ask_finalization=args.run_ask_finalization,
                process_ask_queue=args.process_ask_queue,
                process_maintenance_queue=args.process_maintenance_queue,
                process_personalization_queue=args.process_personalization_queue,
                personalize_user=args.personalize_user,
                process_brief_queue=args.process_brief_queue,
                generate_brief_user=args.generate_brief_user,
                localize_events=args.localize_events,
                process_event_localization_queue=args.process_event_localization_queue,
                backwrite_snapshot_file=args.backwrite_snapshot_file,
            )
        )
    return 0
