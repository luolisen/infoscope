from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid5
from uuid import UUID as UUIDType

import httpx
from sqlalchemy import select

from infoscope.analysis import (
    DeepSeekAnalysisClient,
    DeepSeekEventReconstructionClient,
    DeepSeekIntelligenceClient,
    load_analysis_config,
)
from infoscope.analysis.ask_schemas import AskRequestSpec
from infoscope.analysis.backwrite_schemas import BackwriteSnapshotSpec
from infoscope.config import get_settings
from infoscope.db import close_database, ping_database, session_factory
from infoscope.integrations.research.client import OpenClawConfig, OpenClawResearchClient
from infoscope.integrations.research.fetcher import DirectHTTPSResearchFetcher
from infoscope.integrations.research.health import AgentReachHealthChecker
from infoscope.integrations.research.schemas import ResearchRequestSpec
from infoscope.integrations.telegram import (
    TelegramCollector,
    TelegramNewsClient,
    load_telegram_config,
)
from infoscope.integrations.trendradar import TrendRadarCollector, load_trendradar_config
from infoscope.integrations.trendradar.client import NewsNowClient, RSSClient
from infoscope.models import AskRequest, BriefRun, MaintenanceRun, PipelineArtifact, User
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
from infoscope.services.event_reconstruction import (
    EventReconstructionResult,
    EventReconstructionRunner,
    EventRepository,
)
from infoscope.services.maintenance import (
    MAINTENANCE_PHASES,
    MaintenanceError,
    MaintenanceRepository,
    MaintenanceRunner,
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

logger = logging.getLogger("infoscope.worker")
MAINTENANCE_BACKWRITE_NAMESPACE = UUIDType("44a8817e-991a-4c8c-883a-520677418a2d")


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
    config = load_analysis_config(settings)
    async with httpx.AsyncClient(trust_env=False) as client:
        async with session_factory() as database:
            runner = WindowAnalysisRunner(
                acquisition=AcquisitionRepository(database),
                pipeline=PipelineRepository(database),
                client=DeepSeekAnalysisClient(client=client, config=config),
                max_signals=settings.window_analysis_max_signals,
                max_input_chars=settings.window_analysis_max_input_chars,
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
    config = load_analysis_config(settings)
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
    config = load_analysis_config(get_settings())
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
    config = load_analysis_config(get_settings())
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
    config = load_analysis_config(get_settings())
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
    config = load_analysis_config(get_settings())
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
    config = OpenClawConfig(
        executable=settings.research_openclaw_executable,
        config_path=settings.resolved_research_openclaw_config_path,
        state_dir=settings.resolved_research_openclaw_state_dir,
        model=settings.research_openclaw_model,
        timeout_seconds=settings.research_timeout_seconds,
    )
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


async def compare_ask_once(
    *,
    request_file: Path | None = None,
    retry_request_id: UUID | None = None,
) -> None:
    if (request_file is None) == (retry_request_id is None):
        raise ValueError("exactly one Ask comparison request input is required")
    settings = get_settings()
    config = load_analysis_config(settings)
    async with httpx.AsyncClient(trust_env=False) as client:
        async with session_factory() as database:
            runner = AskComparisonRunner(
                repository=AskComparisonRepository(database),
                client=DeepSeekIntelligenceClient(client=client, config=config),
                max_attempts=settings.ask_comparison_max_attempts,
            )
            if request_file is not None:
                request_document = await asyncio.to_thread(request_file.read_text, "utf-8")
                spec = AskRequestSpec.model_validate_json(request_document)
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
    config = OpenClawConfig(
        executable=settings.research_openclaw_executable,
        config_path=settings.resolved_research_openclaw_config_path,
        state_dir=settings.resolved_research_openclaw_state_dir,
        model=settings.research_openclaw_model,
        timeout_seconds=settings.research_timeout_seconds,
    )
    timeout = httpx.Timeout(connect=10, read=30, write=10, pool=10)
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
        trust_env=False,
    ) as client:
        async with session_factory() as database:
            acquisition = AcquisitionRepository(database)
            research_repository = ResearchRepository(database)
            research_runner = ResearchRunner(
                repository=research_repository,
                acquisition=acquisition,
                client=OpenClawResearchClient(config),
                fetcher=DirectHTTPSResearchFetcher(client),
                max_attempts=settings.research_max_attempts,
                health_checker=AgentReachHealthChecker(
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
    config = load_analysis_config(settings)
    async with httpx.AsyncClient(trust_env=False) as client:
        async with session_factory() as database:
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
    config = load_analysis_config(settings)
    async with httpx.AsyncClient(trust_env=False) as client:
        async with session_factory() as database:
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
        cycle, _inserted = await BackwriteRepository(database).create_or_reuse_cycle(
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
    analysis_config = load_analysis_config(settings)
    openclaw_config = OpenClawConfig(
        executable=settings.research_openclaw_executable,
        config_path=settings.resolved_research_openclaw_config_path,
        state_dir=settings.resolved_research_openclaw_state_dir,
        model=settings.research_openclaw_model,
        timeout_seconds=settings.research_timeout_seconds,
    )
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
                repository = BackwriteRepository(database)
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
    config = load_analysis_config(settings)
    async with httpx.AsyncClient(trust_env=False) as client:
        async with session_factory() as database:
            runner = PersonalizationRunner(
                PersonalizationRepository(database),
                DeepSeekIntelligenceClient(client=client, config=config),
                max_attempts=settings.personalization_max_attempts,
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
    config = load_analysis_config(settings)
    async with httpx.AsyncClient(trust_env=False) as client:
        async with session_factory() as database:
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
                    select(BriefRun).where(
                        BriefRun.source_personalization_artifact_id == source.id
                    )
                )
            ).scalar_one_or_none()
            if prior is None or prior.status == "pending":
                user_id = candidate_id
                break
    if user_id is None:
        return False
    await generate_brief_once(user_id)
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
    async with session_factory() as database:
        windows = list(
            (
                await database.execute(
                    select(PipelineArtifact)
                    .where(PipelineArtifact.artifact_type == "window_analysis")
                    .order_by(PipelineArtifact.created_at, PipelineArtifact.id)
                )
            ).scalars()
        )
    for window in windows:
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
    async with session_factory() as database:
        provider = snapshot_provider or PersonalizationVisibleEventSnapshotProvider(database)
        repository = MaintenanceRepository(database)
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
    process_brief_queue: bool = False,
    backwrite_snapshot_file: Path | None = None,
) -> None:
    settings = get_settings()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    for signal_name in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signal_name, stop.set)

    try:
        while not stop.is_set():
            ask_processed = False
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
            if process_personalization_queue:
                try:
                    await process_personalization_queue_once()
                except Exception:
                    logger.exception("Personalization queue stage failed")
            if process_brief_queue:
                try:
                    await process_brief_queue_once()
                except Exception:
                    logger.exception("Brief queue stage failed")
            if process_maintenance_queue:
                try:
                    await process_maintenance_queue_once()
                except Exception:
                    logger.exception("Maintenance queue stage failed")
            if backwrite_snapshot_file is not None:
                await run_backwrite_snapshot_once(backwrite_snapshot_file)
            logger.info("worker heartbeat")
            if (
                once
                or collect_trendradar
                or collect_telegram
                or normalize
                or retry_normalization
                or deduplicate
                or analyze_windows
                or retry_window_run is not None
                or replay_window_run is not None
                or reconstruct_window_artifact is not None
                or extract_claims_artifact is not None
                or reconstruct_timeline_artifact is not None
                or analyze_conflicts_artifact is not None
                or analyze_base_artifact is not None
                or research_request_file is not None
                or retry_research_request is not None
                or ask_comparison_request_file is not None
                or retry_ask_comparison is not None
                or ask_research_bridge is not None
                or ask_event_reconciliation is not None
                or ask_finalization is not None
                or backwrite_snapshot_file is not None
            ):
                return
            if ask_processed:
                continue
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
        "--process-brief-queue",
        action="store_true",
        help="Continuously generate Briefs for completed Personalization snapshots",
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
                retry_window_run=args.retry_window_run,
                replay_window_run=args.replay_window_run,
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
                process_brief_queue=args.process_brief_queue,
                backwrite_snapshot_file=args.backwrite_snapshot_file,
            )
        )
    return 0
