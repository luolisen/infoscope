from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy.exc import SQLAlchemyError

from infoscope.analysis.client import AnalysisError
from infoscope.analysis.schemas import (
    BATCH_SCHEMA_VERSION,
    MANIFEST_SCHEMA_VERSION,
    AnalysisResponse,
    AnalysisSignal,
    TokenUsage,
    WindowAnalysisBatchArtifact,
    WindowAnalysisManifest,
    WindowAnalysisPayload,
)
from infoscope.models import (
    EvidenceVisibility,
    NormalizationStatus,
    PipelineRun,
    PipelineRunStatus,
    RawInformation,
)
from infoscope.pipeline import AcquisitionCursor, LogicalWindow, completed_windows
from infoscope.services.acquisition import AcquisitionRepository, cursor_for
from infoscope.services.pipeline import (
    ArtifactWrite,
    BatchCacheWrite,
    PipelineRepository,
)

PIPELINE_NAME = "window_analysis"
ARTIFACT_TYPE = "window_analysis"
BATCH_ARTIFACT_TYPE = "window_analysis_batch"
logger = logging.getLogger("infoscope.pipeline.window_analysis")


class AnalysisClientProtocol(Protocol):
    async def analyze(
        self,
        *,
        window: LogicalWindow,
        signals: list[AnalysisSignal],
    ) -> AnalysisResponse: ...


class WindowAnalysisError(Exception):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


@dataclass(frozen=True, slots=True)
class WindowRunResult:
    windows_succeeded: int
    windows_failed: int
    raws_scanned: int
    signals_analyzed: int


class WindowAnalysisRunner:
    def __init__(
        self,
        *,
        acquisition: AcquisitionRepository,
        pipeline: PipelineRepository,
        client: AnalysisClientProtocol,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        raw_page_size: int = 500,
        max_signals: int = 50,
        max_input_chars: int = 100_000,
        max_batches: int = 64,
        batch_concurrency: int = 3,
    ) -> None:
        self.acquisition = acquisition
        self.pipeline = pipeline
        self.client = client
        self.clock = clock
        if raw_page_size <= 0:
            raise ValueError("raw_page_size must be positive")
        if max_signals <= 0:
            raise ValueError("max_signals must be positive")
        if max_input_chars <= 0:
            raise ValueError("max_input_chars must be positive")
        if max_batches <= 0:
            raise ValueError("max_batches must be positive")
        if batch_concurrency <= 0:
            raise ValueError("batch_concurrency must be positive")
        self.raw_page_size = raw_page_size
        self.max_signals = max_signals
        self.max_input_chars = max_input_chars
        self.max_batches = max_batches
        self.batch_concurrency = batch_concurrency

    async def run_available(
        self,
        *,
        watermark: datetime,
        max_windows: int = 24,
    ) -> WindowRunResult:
        if max_windows <= 0:
            raise ValueError("max_windows must be positive")
        start = await self.pipeline.latest_successful_window_end(PIPELINE_NAME)
        if start is None:
            start = await self.acquisition.earliest_raw_acquired_at()
        if start is None:
            return WindowRunResult(0, 0, 0, 0)
        windows = completed_windows(start=start, watermark=watermark)[:max_windows]
        succeeded = 0
        failed = 0
        raws_scanned = 0
        signals_analyzed = 0

        for window in windows:
            lower_cursor = await self.pipeline.checkpoint_cursor(PIPELINE_NAME)
            run = await self._prepare_window_run(window=window, lower_cursor=lower_cursor)
            if run is None:
                break
            result = await self._execute_run(run)
            succeeded += result.windows_succeeded
            failed += result.windows_failed
            raws_scanned += result.raws_scanned
            signals_analyzed += result.signals_analyzed
            if result.windows_failed:
                break

        return WindowRunResult(succeeded, failed, raws_scanned, signals_analyzed)

    async def retry_run(self, run_id: UUID) -> WindowRunResult:
        previous = await self._require_pipeline_run(run_id)
        if previous.status != PipelineRunStatus.FAILED.value:
            raise WindowAnalysisError("WINDOW_RUN_NOT_FAILED")
        run = await self.pipeline.retry_run(previous, started_at=self.clock())
        return await self._execute_run(run)

    async def replay_run(self, run_id: UUID) -> WindowRunResult:
        previous = await self._require_pipeline_run(run_id)
        if previous.status not in {
            PipelineRunStatus.SUCCEEDED.value,
            PipelineRunStatus.FAILED.value,
        }:
            raise WindowAnalysisError("WINDOW_RUN_NOT_TERMINAL")
        run = await self.pipeline.replay_run(previous, started_at=self.clock())
        return await self._execute_run(run)

    async def _require_pipeline_run(self, run_id: UUID) -> PipelineRun:
        run = await self.pipeline.get_run(run_id)
        if run is None:
            raise WindowAnalysisError("WINDOW_RUN_NOT_FOUND")
        if run.pipeline_name != PIPELINE_NAME:
            raise WindowAnalysisError("WINDOW_RUN_PIPELINE_MISMATCH")
        return run

    async def _prepare_window_run(
        self,
        *,
        window: LogicalWindow,
        lower_cursor: AcquisitionCursor | None,
    ) -> PipelineRun | None:
        previous = await self.pipeline.latest_window_run(
            pipeline_name=PIPELINE_NAME,
            window=window,
        )
        now = self.clock()
        if previous is None:
            return await self.pipeline.start_run(
                pipeline_name=PIPELINE_NAME,
                window=window,
                started_at=now,
                lower_cursor=lower_cursor,
            )
        if previous.status == PipelineRunStatus.FAILED.value:
            if previous.next_retry_at is not None and previous.next_retry_at > now:
                logger.info(
                    "pipeline run deferred pipeline=%s run_id=%s window_start=%s "
                    "window_end=%s attempt=%s next_retry_at=%s",
                    PIPELINE_NAME,
                    previous.id,
                    window.start.isoformat(),
                    window.end.isoformat(),
                    previous.attempt,
                    previous.next_retry_at.isoformat(),
                )
                return None
            return await self.pipeline.retry_run(previous, started_at=now)
        logger.info(
            "pipeline window skipped pipeline=%s run_id=%s status=%s window_start=%s "
            "window_end=%s attempt=%s",
            PIPELINE_NAME,
            previous.id,
            previous.status,
            window.start.isoformat(),
            window.end.isoformat(),
            previous.attempt,
        )
        return None

    async def _execute_run(self, run: PipelineRun) -> WindowRunResult:
        window = LogicalWindow(start=run.window_start, end=run.window_end)
        lower_cursor = self._lower_cursor(run)
        logger.info(
            "pipeline run started pipeline=%s run_id=%s window_start=%s window_end=%s "
            "attempt=%s",
            PIPELINE_NAME,
            run.id,
            window.start.isoformat(),
            window.end.isoformat(),
            run.attempt,
        )
        try:
            raws = await self._load_raws(window=window, lower_cursor=lower_cursor)
            signals = await self._analysis_signals(raws)
            batches = self._partition_signals(signals)
            input_hash = self._input_hash(window=window, signals=signals)
            batch_input_hashes = [
                self._batch_input_hash(
                    window=window,
                    signals=batch,
                    batch_index=index,
                    batch_count=len(batches),
                    window_input_hash=input_hash,
                )
                for index, batch in enumerate(batches)
            ]
            responses = await self._analyze_batches(
                window=window,
                batches=batches,
                batch_input_hashes=batch_input_hashes,
                window_input_hash=input_hash,
            )
            batch_ids = [uuid4() for _ in batches]
            batch_writes = [
                ArtifactWrite(
                    id=batch_ids[index],
                    artifact_type=BATCH_ARTIFACT_TYPE,
                    artifact_key=f"{index:06d}",
                    schema_version=BATCH_SCHEMA_VERSION,
                    input_hash=batch_input_hashes[index],
                    payload=WindowAnalysisBatchArtifact(
                        batch_index=index,
                        batch_count=len(batches),
                        window_input_hash=input_hash,
                        model_output=responses[index].payload,
                    ).model_dump(mode="json"),
                    provider=responses[index].provider,
                    model=responses[index].model,
                    token_usage=responses[index].token_usage.model_dump(mode="json"),
                )
                for index, batch in enumerate(batches)
            ]
            manifest = ArtifactWrite(
                id=uuid4(),
                artifact_type=ARTIFACT_TYPE,
                artifact_key="default",
                schema_version=MANIFEST_SCHEMA_VERSION,
                input_hash=input_hash,
                payload=WindowAnalysisManifest(
                    batch_artifact_ids=batch_ids,
                    signal_count=len(signals),
                    window_input_hash=input_hash,
                ).model_dump(mode="json"),
                provider="internal",
                model="batched",
                token_usage=self._combined_usage(responses).model_dump(mode="json"),
            )
            await self.pipeline.persist_window_bundle(
                run=run,
                batches=batch_writes,
                manifest=manifest,
                finished_at=self.clock(),
                upper_cursor=cursor_for(raws[-1]) if raws else None,
            )
        except asyncio.CancelledError:
            run_id = run.id
            await self.pipeline.rollback()
            run = await self.pipeline.get_run(run_id) or run
            await self.pipeline.fail_run(
                run,
                finished_at=self.clock(),
                next_retry_at=self.clock(),
                error_code="WINDOW_RUN_INTERRUPTED",
            )
            raise
        except (AnalysisError, WindowAnalysisError, SQLAlchemyError) as error:
            run_id = run.id
            await self.pipeline.rollback()
            run = await self.pipeline.get_run(run_id) or run
            retry_at = self.clock() + timedelta(minutes=5)
            error_code = (
                error.error_code
                if isinstance(error, (AnalysisError, WindowAnalysisError))
                else "WINDOW_PERSISTENCE_FAILED"
            )
            await self.pipeline.fail_run(
                run,
                finished_at=self.clock(),
                next_retry_at=retry_at,
                error_code=error_code,
            )
            logger.warning(
                "pipeline run failed pipeline=%s run_id=%s window_start=%s window_end=%s "
                "attempt=%s error_code=%s next_retry_at=%s",
                PIPELINE_NAME,
                run.id,
                window.start.isoformat(),
                window.end.isoformat(),
                run.attempt,
                error_code,
                retry_at.isoformat(),
            )
            return WindowRunResult(0, 1, 0, 0)
        logger.info(
            "pipeline run succeeded pipeline=%s run_id=%s window_start=%s window_end=%s "
            "attempt=%s raws=%d signals=%d",
            PIPELINE_NAME,
            run.id,
            window.start.isoformat(),
            window.end.isoformat(),
            run.attempt,
            len(raws),
            len(signals),
        )
        return WindowRunResult(1, 0, len(raws), len(signals))

    @staticmethod
    def _lower_cursor(run: PipelineRun) -> AcquisitionCursor | None:
        if run.lower_cursor_acquired_at is None:
            if run.lower_cursor_raw_id is not None:
                raise WindowAnalysisError("WINDOW_RUN_CURSOR_INVALID")
            return None
        if run.lower_cursor_raw_id is None:
            raise WindowAnalysisError("WINDOW_RUN_CURSOR_INVALID")
        return AcquisitionCursor(run.lower_cursor_acquired_at, run.lower_cursor_raw_id)

    async def _load_raws(
        self,
        *,
        window: LogicalWindow,
        lower_cursor: AcquisitionCursor | None,
    ) -> list[RawInformation]:
        raws: list[RawInformation] = []
        after = lower_cursor
        while True:
            page = await self.acquisition.list_raw_window(
                window=window,
                after=after,
                limit=self.raw_page_size,
            )
            if not page:
                break
            raws.extend(page)
            after = cursor_for(page[-1])
            if len(page) < self.raw_page_size:
                break
        return raws

    async def _analysis_signals(self, raws: list[RawInformation]) -> list[AnalysisSignal]:
        values: list[AnalysisSignal] = []
        for raw in raws:
            if raw.normalization_status != NormalizationStatus.SUCCEEDED.value:
                raise WindowAnalysisError("WINDOW_RAW_NOT_NORMALIZED")
            signals = await self.acquisition.list_signals_for_raw(raw.id)
            if not signals:
                raise WindowAnalysisError("WINDOW_SIGNAL_MISSING")
            for signal in signals:
                if signal.duplicate_of_signal_id is not None:
                    continue
                if (
                    signal.evidence_visibility
                    == EvidenceVisibility.PRIVATE_SANITIZED.value
                    and signal.public_provenance is not None
                ):
                    raise WindowAnalysisError("WINDOW_PRIVATE_PROVENANCE_INVALID")
                values.append(
                    AnalysisSignal(
                        signal_id=signal.id,
                        title=signal.title,
                        text=signal.normalized_text,
                        published_at=signal.published_at,
                        source_type=signal.source_type,
                        evidence_visibility=signal.evidence_visibility,
                        public_provenance=signal.public_provenance,
                    )
                )
        return values

    def _partition_signals(
        self, signals: list[AnalysisSignal]
    ) -> list[list[AnalysisSignal]]:
        if not signals:
            return [[]]
        batches: list[list[AnalysisSignal]] = []
        current: list[AnalysisSignal] = []
        current_chars = 0
        for signal in signals:
            signal_chars = self._signal_chars(signal)
            if signal_chars > self.max_input_chars:
                raise WindowAnalysisError("WINDOW_SIGNAL_INPUT_LIMIT_EXCEEDED")
            if current and (
                len(current) >= self.max_signals
                or current_chars + signal_chars > self.max_input_chars
            ):
                batches.append(current)
                current = []
                current_chars = 0
            current.append(signal)
            current_chars += signal_chars
        if current:
            batches.append(current)
        if len(batches) > self.max_batches:
            raise WindowAnalysisError("WINDOW_BATCH_LIMIT_EXCEEDED")
        return batches

    @staticmethod
    def _signal_chars(signal: AnalysisSignal) -> int:
        return (
            len(signal.title or "")
            + len(signal.text)
            + len(json.dumps(signal.public_provenance, ensure_ascii=False))
        )

    async def _analyze(
        self,
        *,
        window: LogicalWindow,
        signals: list[AnalysisSignal],
    ) -> AnalysisResponse:
        if signals:
            return await self.client.analyze(window=window, signals=signals)
        return AnalysisResponse(
            payload=WindowAnalysisPayload(
                signal_analyses=[],
                clusters=[],
                unassigned_signal_ids=[],
            ),
            provider="internal",
            model="none",
            token_usage=TokenUsage(),
        )

    async def _analyze_resilient(
        self,
        *,
        window: LogicalWindow,
        signals: list[AnalysisSignal],
    ) -> AnalysisResponse:
        try:
            return await self._analyze(window=window, signals=signals)
        except AnalysisError as error:
            split_errors = {
                "ANALYSIS_REQUEST_FAILED",
                "ANALYSIS_REQUEST_REJECTED",
                "ANALYSIS_UPSTREAM_UNAVAILABLE",
                "ANALYSIS_SCHEMA_INVALID",
                "ANALYSIS_SIGNAL_COVERAGE_INVALID",
                "ANALYSIS_TRUNCATED",
            }
            if len(signals) <= 10 or error.error_code not in split_errors:
                raise
            split_at = len(signals) // 2
            parts = (signals[:split_at], signals[split_at:])
            logger.warning(
                "pipeline batch request splitting pipeline=%s window_start=%s window_end=%s "
                "signals=%d parts=%s error_code=%s",
                PIPELINE_NAME,
                window.start.isoformat(),
                window.end.isoformat(),
                len(signals),
                [len(part) for part in parts],
                error.error_code,
            )
            responses = [
                await self._analyze_resilient(window=window, signals=part)
                for part in parts
            ]
            providers = {response.provider for response in responses}
            models = {response.model for response in responses}
            if len(providers) != 1 or len(models) != 1:
                raise WindowAnalysisError("ANALYSIS_MODEL_CHANGED") from error
            return AnalysisResponse(
                payload=WindowAnalysisPayload(
                    signal_analyses=[
                        item
                        for response in responses
                        for item in response.payload.signal_analyses
                    ],
                    clusters=[
                        cluster.model_copy(
                            update={"cluster_key": f"split-{part_index}-{cluster.cluster_key}"}
                        )
                        for part_index, response in enumerate(responses)
                        for cluster in response.payload.clusters
                    ],
                    unassigned_signal_ids=[
                        signal_id
                        for response in responses
                        for signal_id in response.payload.unassigned_signal_ids
                    ],
                ),
                provider=responses[0].provider,
                model=responses[0].model,
                token_usage=TokenUsage(
                    prompt_tokens=sum(
                        response.token_usage.prompt_tokens for response in responses
                    ),
                    completion_tokens=sum(
                        response.token_usage.completion_tokens for response in responses
                    ),
                    total_tokens=sum(
                        response.token_usage.total_tokens for response in responses
                    ),
                ),
            )

    async def _analyze_batches(
        self,
        *,
        window: LogicalWindow,
        batches: list[list[AnalysisSignal]],
        batch_input_hashes: list[str],
        window_input_hash: str,
    ) -> list[AnalysisResponse]:
        if len(batch_input_hashes) != len(batches):
            raise WindowAnalysisError("WINDOW_BATCH_HASH_COUNT_INVALID")
        responses: list[AnalysisResponse | None] = [None] * len(batches)
        cached = await self.pipeline.cached_window_batches(batch_input_hashes)
        for index, input_hash in enumerate(batch_input_hashes):
            item = cached.get(input_hash)
            if item is None:
                continue
            try:
                if item.schema_version != BATCH_SCHEMA_VERSION:
                    raise ValueError("cache schema version mismatch")
                payload = WindowAnalysisBatchArtifact.model_validate(item.payload)
                if (
                    payload.batch_index != index
                    or payload.batch_count != len(batches)
                    or payload.window_input_hash != window_input_hash
                ):
                    raise ValueError("cache batch identity mismatch")
                self._validate_coverage(payload.model_output, batches[index])
                responses[index] = AnalysisResponse(
                    payload=payload.model_output,
                    provider=item.provider,
                    model=item.model,
                    token_usage=TokenUsage.model_validate(item.token_usage),
                )
            except ValueError as error:
                raise WindowAnalysisError("WINDOW_BATCH_CACHE_INVALID") from error
            logger.info(
                "pipeline batch reused pipeline=%s window_start=%s window_end=%s "
                "batch_index=%d batch_count=%d signals=%d",
                PIPELINE_NAME,
                window.start.isoformat(),
                window.end.isoformat(),
                index,
                len(batches),
                len(batches[index]),
            )

        async def analyze_one(index: int, batch: list[AnalysisSignal]) -> AnalysisResponse:
            logger.info(
                "pipeline batch started pipeline=%s window_start=%s window_end=%s "
                "batch_index=%d batch_count=%d signals=%d",
                PIPELINE_NAME,
                window.start.isoformat(),
                window.end.isoformat(),
                index,
                len(batches),
                len(batch),
            )
            response = await self._analyze_resilient(window=window, signals=batch)
            self._validate_coverage(response.payload, batch)
            logger.info(
                "pipeline batch completed pipeline=%s window_start=%s window_end=%s "
                "batch_index=%d batch_count=%d signals=%d",
                PIPELINE_NAME,
                window.start.isoformat(),
                window.end.isoformat(),
                index,
                len(batches),
                len(batch),
            )
            return response

        missing = [index for index, response in enumerate(responses) if response is None]

        async def cache_completed(
            indexes: list[int], completed: list[AnalysisResponse]
        ) -> None:
            cache_writes: list[BatchCacheWrite] = []
            for index, response in zip(indexes, completed, strict=True):
                responses[index] = response
                cache_payload = WindowAnalysisBatchArtifact(
                    batch_index=index,
                    batch_count=len(batches),
                    window_input_hash=window_input_hash,
                    model_output=response.payload,
                )
                cache_writes.append(
                    BatchCacheWrite(
                        input_hash=batch_input_hashes[index],
                        schema_version=BATCH_SCHEMA_VERSION,
                        payload=cache_payload.model_dump(mode="json"),
                        provider=response.provider,
                        model=response.model,
                        token_usage=response.token_usage.model_dump(mode="json"),
                    )
                )
            await self.pipeline.persist_window_batch_cache(cache_writes)

        missing_iterator = iter(missing)
        cache_lock = asyncio.Lock()
        batch_failures: list[Exception] = []
        fatal_failures: list[Exception] = []

        async def analyze_worker() -> None:
            while not fatal_failures:
                try:
                    index = next(missing_iterator)
                except StopIteration:
                    return
                try:
                    response = await analyze_one(index, batches[index])
                except asyncio.CancelledError:
                    raise
                except (AnalysisError, WindowAnalysisError) as error:
                    batch_failures.append(error)
                    logger.warning(
                        "pipeline batch failed pipeline=%s window_start=%s window_end=%s "
                        "batch_index=%d batch_count=%d error_code=%s",
                        PIPELINE_NAME,
                        window.start.isoformat(),
                        window.end.isoformat(),
                        index,
                        len(batches),
                        error.error_code,
                    )
                    continue
                try:
                    # AsyncSession cannot be used concurrently. Serialize each completed cache
                    # write while allowing the remaining model requests to stay in flight.
                    async with cache_lock:
                        await cache_completed([index], [response])
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    fatal_failures.append(error)
                    return

        workers = [
            asyncio.create_task(analyze_worker())
            for _ in range(min(self.batch_concurrency, len(missing)))
        ]
        try:
            await asyncio.gather(*workers)
        except BaseException:
            for worker in workers:
                if not worker.done():
                    worker.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            raise
        if fatal_failures:
            raise fatal_failures[0]
        if batch_failures:
            raise batch_failures[0]
        if any(response is None for response in responses):
            raise WindowAnalysisError("WINDOW_BATCH_RESPONSE_MISSING")
        return [response for response in responses if response is not None]

    @staticmethod
    def _validate_coverage(
        payload: WindowAnalysisPayload,
        signals: list[AnalysisSignal],
    ) -> None:
        expected = {signal.signal_id for signal in signals}
        analyzed = {item.signal_id for item in payload.signal_analyses}
        assigned = {value for cluster in payload.clusters for value in cluster.signal_ids}
        covered = assigned | set(payload.unassigned_signal_ids)
        relationship_ids = {
            value
            for cluster in payload.clusters
            for relationship in cluster.relationships
            for value in relationship.signal_ids
        }
        if analyzed != expected or covered != expected or not relationship_ids <= expected:
            raise WindowAnalysisError("ANALYSIS_SIGNAL_COVERAGE_INVALID")
        for cluster in payload.clusters:
            cluster_ids = set(cluster.signal_ids)
            if any(
                not set(relationship.signal_ids) <= cluster_ids
                for relationship in cluster.relationships
            ):
                raise WindowAnalysisError("ANALYSIS_RELATIONSHIP_SCOPE_INVALID")

    @staticmethod
    def _input_hash(*, window: LogicalWindow, signals: list[AnalysisSignal]) -> str:
        document = {
            "window": {"start": window.start.isoformat(), "end": window.end.isoformat()},
            "signals": [signal.model_dump(mode="json") for signal in signals],
        }
        canonical = json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _batch_input_hash(
        *,
        window: LogicalWindow,
        signals: list[AnalysisSignal],
        batch_index: int,
        batch_count: int,
        window_input_hash: str,
    ) -> str:
        document = {
            "window": {"start": window.start.isoformat(), "end": window.end.isoformat()},
            "batch_index": batch_index,
            "batch_count": batch_count,
            "window_input_hash": window_input_hash,
            "signals": [signal.model_dump(mode="json") for signal in signals],
        }
        canonical = json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _combined_usage(responses: list[AnalysisResponse]) -> TokenUsage:
        return TokenUsage(
            prompt_tokens=sum(item.token_usage.prompt_tokens for item in responses),
            completion_tokens=sum(item.token_usage.completion_tokens for item in responses),
            total_tokens=sum(item.token_usage.total_tokens for item in responses),
        )
