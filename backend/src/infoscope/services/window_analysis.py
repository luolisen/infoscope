from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from infoscope.analysis.client import AnalysisError
from infoscope.analysis.schemas import (
    SCHEMA_VERSION,
    AnalysisResponse,
    AnalysisSignal,
    TokenUsage,
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
from infoscope.services.pipeline import PipelineRepository

PIPELINE_NAME = "window_analysis"
ARTIFACT_TYPE = "window_analysis"
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
        max_signals: int = 200,
        max_input_chars: int = 100_000,
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
        self.raw_page_size = raw_page_size
        self.max_signals = max_signals
        self.max_input_chars = max_input_chars

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
            self._validate_input_size(signals)
            response = await self._analyze(window=window, signals=signals)
            self._validate_coverage(response.payload, signals)
            input_hash = self._input_hash(window=window, signals=signals)
            await self.pipeline.persist_artifact(
                run=run,
                artifact_type=ARTIFACT_TYPE,
                schema_version=SCHEMA_VERSION,
                input_hash=input_hash,
                payload=response.payload.model_dump(mode="json"),
                provider=response.provider,
                model=response.model,
                token_usage=response.token_usage.model_dump(mode="json"),
            )
            await self.pipeline.complete_run(
                run,
                finished_at=self.clock(),
                upper_cursor=cursor_for(raws[-1]) if raws else None,
            )
        except (AnalysisError, WindowAnalysisError) as error:
            retry_at = self.clock() + timedelta(minutes=5)
            await self.pipeline.fail_run(
                run,
                finished_at=self.clock(),
                next_retry_at=retry_at,
                error_code=error.error_code,
            )
            logger.warning(
                "pipeline run failed pipeline=%s run_id=%s window_start=%s window_end=%s "
                "attempt=%s error_code=%s next_retry_at=%s",
                PIPELINE_NAME,
                run.id,
                window.start.isoformat(),
                window.end.isoformat(),
                run.attempt,
                error.error_code,
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

    def _validate_input_size(self, signals: list[AnalysisSignal]) -> None:
        if len(signals) > self.max_signals:
            raise WindowAnalysisError("WINDOW_SIGNAL_LIMIT_EXCEEDED")
        input_chars = sum(
            len(signal.title or "")
            + len(signal.text)
            + len(json.dumps(signal.public_provenance, ensure_ascii=False))
            for signal in signals
        )
        if input_chars > self.max_input_chars:
            raise WindowAnalysisError("WINDOW_INPUT_LIMIT_EXCEEDED")

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
