import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from infoscope.analysis.client import AnalysisError
from infoscope.analysis.schemas import (
    AnalysisResponse,
    AnalysisSignal,
    SignalAnalysis,
    TokenUsage,
    WindowAnalysisPayload,
)
from infoscope.models import (
    EvidenceVisibility,
    NormalizationStatus,
    PipelineRun,
    PipelineRunStatus,
    RawInformation,
    Signal,
    SourceVisibility,
)
from infoscope.services.window_analysis import WindowAnalysisRunner


def _raw(*, status: NormalizationStatus = NormalizationStatus.SUCCEEDED) -> RawInformation:
    return RawInformation(
        id=uuid4(),
        source_type="telegram",
        source_key="key",
        source_visibility=SourceVisibility.PUBLIC.value,
        acquired_at=datetime(2026, 8, 16, 9, 15, tzinfo=UTC),
        published_at=datetime(2026, 8, 16, 9, tzinfo=UTC),
        content_text="Evidence",
        payload={},
        provenance={},
        collector_metadata={},
        content_hash="a" * 64,
        normalization_status=status.value,
        normalization_attempts=1,
    )


def _signal(
    raw: RawInformation,
    *,
    visibility: EvidenceVisibility = EvidenceVisibility.PUBLIC,
    public_provenance: dict | None = None,
) -> Signal:
    return Signal(
        id=uuid4(),
        raw_information_id=raw.id,
        signal_index=0,
        normalized_text="Evidence",
        source_type="telegram",
        evidence_visibility=visibility.value,
        public_provenance=(
            {"platform": "Telegram"}
            if visibility is EvidenceVisibility.PUBLIC and public_provenance is None
            else public_provenance
        ),
        content_hash="b" * 64,
        created_at=datetime(2026, 8, 16, 9, 16, tzinfo=UTC),
    )


class FakeAcquisition:
    def __init__(self, raw: RawInformation, signal: Signal | list[Signal]) -> None:
        self.raw = raw
        self.signals = signal if isinstance(signal, list) else [signal]

    async def earliest_raw_acquired_at(self):
        return datetime(2026, 8, 16, 9, tzinfo=UTC)

    async def list_raw_window(self, *, window, after, limit):
        return [self.raw] if after is None else []

    async def list_signals_for_raw(self, raw_id):
        return self.signals


class FakePipeline:
    def __init__(self, previous: PipelineRun | None = None) -> None:
        self.events: list[str] = []
        self.failed_code: str | None = None
        self.previous = previous
        self.batch_count: int | None = None
        self.batch_cache: dict[str, object] = {}

    async def latest_successful_window_end(self, pipeline_name):
        return None

    async def checkpoint_cursor(self, pipeline_name):
        return None

    async def get_run(self, run_id):
        if self.previous is not None and self.previous.id == run_id:
            return self.previous
        return None

    async def latest_window_run(self, *, pipeline_name, window):
        return self.previous

    async def start_run(self, *, pipeline_name, window, started_at, lower_cursor):
        self.events.append("start")
        return PipelineRun(
            id=uuid4(),
            pipeline_name=pipeline_name,
            status=PipelineRunStatus.RUNNING.value,
            window_start=window.start,
            window_end=window.end,
            started_at=started_at,
        )

    async def retry_run(self, failed_run, *, started_at):
        self.events.append("retry")
        return self._repeat(failed_run, started_at)

    async def replay_run(self, terminal_run, *, started_at):
        self.events.append("replay")
        return self._repeat(terminal_run, started_at)

    @staticmethod
    def _repeat(previous, started_at):
        return PipelineRun(
            id=uuid4(),
            pipeline_name=previous.pipeline_name,
            status=PipelineRunStatus.RUNNING.value,
            window_start=previous.window_start,
            window_end=previous.window_end,
            lower_cursor_acquired_at=previous.lower_cursor_acquired_at,
            lower_cursor_raw_id=previous.lower_cursor_raw_id,
            attempt=previous.attempt + 1,
            started_at=started_at,
        )

    async def persist_artifact(self, **kwargs):
        self.events.append("artifact")

    async def persist_window_bundle(
        self, *, run, batches, manifest, finished_at, upper_cursor
    ):
        self.batch_count = len(batches)
        self.events.extend(["artifact", "complete"])

    async def cached_window_batches(self, input_hashes):
        return {
            input_hash: self.batch_cache[input_hash]
            for input_hash in input_hashes
            if input_hash in self.batch_cache
        }

    async def persist_window_batch_cache(self, writes):
        for item in writes:
            self.batch_cache[item.input_hash] = SimpleNamespace(
                input_hash=item.input_hash,
                schema_version=item.schema_version,
                payload=item.payload,
                provider=item.provider,
                model=item.model,
                token_usage=item.token_usage,
            )

    async def rollback(self):
        return None

    async def complete_run(self, run, *, finished_at, upper_cursor):
        self.events.append("complete")

    async def fail_run(self, run, *, finished_at, next_retry_at, error_code):
        self.events.append("fail")
        self.failed_code = error_code


class FakeClient:
    def __init__(self) -> None:
        self.batch_sizes: list[int] = []

    async def analyze(self, *, window, signals):
        self.batch_sizes.append(len(signals))
        return AnalysisResponse(
            payload=WindowAnalysisPayload(
                signal_analyses=[
                    SignalAnalysis(
                        signal_id=signal.signal_id,
                        categories=["technology"],
                        fact_claims=["Evidence"],
                    )
                    for signal in signals
                ],
                clusters=[],
                unassigned_signal_ids=[signal.signal_id for signal in signals],
            ),
            provider="deepseek",
            model="deepseek-v4-flash",
            token_usage=TokenUsage(total_tokens=10),
        )


class SelectiveFailClient(FakeClient):
    def __init__(self, fail_signal_id) -> None:
        super().__init__()
        self.fail_signal_id = fail_signal_id

    async def analyze(self, *, window, signals):
        await asyncio.sleep(0)
        if signals[0].signal_id == self.fail_signal_id:
            raise AnalysisError("ANALYSIS_SCHEMA_INVALID")
        return await super().analyze(window=window, signals=signals)


class OversizedFailClient(FakeClient):
    async def analyze(self, *, window, signals):
        self.batch_sizes.append(len(signals))
        if len(signals) > 10:
            raise AnalysisError("ANALYSIS_REQUEST_FAILED")
        response = await super().analyze(window=window, signals=signals)
        self.batch_sizes.pop()
        return response


async def test_window_artifact_is_persisted_before_checkpoint_completion() -> None:
    raw = _raw()
    pipeline = FakePipeline()
    runner = WindowAnalysisRunner(
        acquisition=FakeAcquisition(raw, _signal(raw)),  # type: ignore[arg-type]
        pipeline=pipeline,  # type: ignore[arg-type]
        client=FakeClient(),
        clock=lambda: datetime(2026, 8, 16, 10, tzinfo=UTC),
    )

    result = await runner.run_available(
        watermark=datetime(2026, 8, 16, 10, tzinfo=UTC)
    )

    assert result.windows_succeeded == 1
    assert result.windows_failed == 0
    assert result.raws_scanned == 1
    assert result.signals_analyzed == 1
    assert pipeline.events == ["start", "artifact", "complete"]


async def test_pending_raw_fails_window_without_artifact_or_checkpoint() -> None:
    raw = _raw(status=NormalizationStatus.PENDING)
    pipeline = FakePipeline()
    runner = WindowAnalysisRunner(
        acquisition=FakeAcquisition(raw, _signal(raw)),  # type: ignore[arg-type]
        pipeline=pipeline,  # type: ignore[arg-type]
        client=FakeClient(),
        clock=lambda: datetime(2026, 8, 16, 10, tzinfo=UTC),
    )

    result = await runner.run_available(
        watermark=datetime(2026, 8, 16, 10, tzinfo=UTC)
    )

    assert result.windows_succeeded == 0
    assert result.windows_failed == 1
    assert pipeline.events == ["start", "fail"]
    assert pipeline.failed_code == "WINDOW_RAW_NOT_NORMALIZED"


async def test_private_signal_with_public_provenance_is_rejected_before_api() -> None:
    raw = _raw()
    pipeline = FakePipeline()
    signal = _signal(
        raw,
        visibility=EvidenceVisibility.PRIVATE_SANITIZED,
        public_provenance={"username": "must-not-leak"},
    )
    runner = WindowAnalysisRunner(
        acquisition=FakeAcquisition(raw, signal),  # type: ignore[arg-type]
        pipeline=pipeline,  # type: ignore[arg-type]
        client=FakeClient(),
        clock=lambda: datetime(2026, 8, 16, 10, tzinfo=UTC),
    )

    result = await runner.run_available(
        watermark=datetime(2026, 8, 16, 10, tzinfo=UTC)
    )

    assert result.windows_failed == 1
    assert pipeline.events == ["start", "fail"]
    assert pipeline.failed_code == "WINDOW_PRIVATE_PROVENANCE_INVALID"


async def test_single_signal_over_input_limit_is_rejected_before_api() -> None:
    raw = _raw()
    pipeline = FakePipeline()
    runner = WindowAnalysisRunner(
        acquisition=FakeAcquisition(raw, _signal(raw)),  # type: ignore[arg-type]
        pipeline=pipeline,  # type: ignore[arg-type]
        client=FakeClient(),
        clock=lambda: datetime(2026, 8, 16, 10, tzinfo=UTC),
        max_input_chars=1,
    )

    result = await runner.run_available(
        watermark=datetime(2026, 8, 16, 10, tzinfo=UTC)
    )

    assert result.windows_failed == 1
    assert pipeline.events == ["start", "fail"]
    assert pipeline.failed_code == "WINDOW_SIGNAL_INPUT_LIMIT_EXCEEDED"


async def test_oversized_window_is_partitioned_without_losing_signal_order() -> None:
    raw = _raw()
    pipeline = FakePipeline()
    client = FakeClient()
    signals = [_signal(raw) for _ in range(3)]
    runner = WindowAnalysisRunner(
        acquisition=FakeAcquisition(raw, signals),  # type: ignore[arg-type]
        pipeline=pipeline,  # type: ignore[arg-type]
        client=client,
        clock=lambda: datetime(2026, 8, 16, 10, tzinfo=UTC),
        max_signals=2,
    )

    result = await runner.run_available(
        watermark=datetime(2026, 8, 16, 10, tzinfo=UTC)
    )

    assert result.windows_succeeded == 1
    assert result.signals_analyzed == 3
    assert client.batch_sizes == [2, 1]
    assert pipeline.batch_count == 2
    assert pipeline.events == ["start", "artifact", "complete"]


async def test_successful_batches_are_cached_when_a_later_batch_fails() -> None:
    raw = _raw()
    stored_signals = [_signal(raw) for _ in range(4)]
    signals = [
        AnalysisSignal(
            signal_id=signal.id,
            title=signal.title,
            text=signal.normalized_text,
            published_at=signal.published_at,
            source_type=signal.source_type,
            evidence_visibility=signal.evidence_visibility,
            public_provenance=signal.public_provenance,
        )
        for signal in stored_signals
    ]
    batches = [[signal] for signal in signals]
    hashes = [f"{index:x}" * 64 for index in range(4)]
    pipeline = FakePipeline()
    failing = SelectiveFailClient(signals[1].signal_id)
    runner = WindowAnalysisRunner(
        acquisition=FakeAcquisition(raw, stored_signals),  # type: ignore[arg-type]
        pipeline=pipeline,  # type: ignore[arg-type]
        client=failing,
        batch_concurrency=2,
    )
    window = type("Window", (), {
        "start": datetime(2026, 8, 16, 9, tzinfo=UTC),
        "end": datetime(2026, 8, 16, 10, tzinfo=UTC),
    })()

    with pytest.raises(AnalysisError):
        await runner._analyze_batches(  # noqa: SLF001
            window=window,
            batches=batches,
            batch_input_hashes=hashes,
            window_input_hash="f" * 64,
        )

    assert set(pipeline.batch_cache) == {hashes[0], hashes[2], hashes[3]}

    retry_client = FakeClient()
    retry_runner = WindowAnalysisRunner(
        acquisition=FakeAcquisition(raw, stored_signals),  # type: ignore[arg-type]
        pipeline=pipeline,  # type: ignore[arg-type]
        client=retry_client,
        batch_concurrency=2,
    )
    responses = await retry_runner._analyze_batches(  # noqa: SLF001
        window=window,
        batches=batches,
        batch_input_hashes=hashes,
        window_input_hash="f" * 64,
    )

    assert len(responses) == 4
    assert retry_client.batch_sizes == [1]


async def test_batch_worker_refills_capacity_before_slowest_request_finishes() -> None:
    raw = _raw()
    stored_signals = [_signal(raw) for _ in range(3)]
    signals = [
        AnalysisSignal(
            signal_id=signal.id,
            title=signal.title,
            text=signal.normalized_text,
            published_at=signal.published_at,
            source_type=signal.source_type,
            evidence_visibility=signal.evidence_visibility,
            public_provenance=signal.public_provenance,
        )
        for signal in stored_signals
    ]
    slow_started = asyncio.Event()
    release_slow = asyncio.Event()
    third_started = asyncio.Event()

    class StreamingClient(FakeClient):
        async def analyze(self, *, window, signals):
            if signals[0].signal_id == stored_signals[0].id:
                slow_started.set()
                await release_slow.wait()
            if signals[0].signal_id == stored_signals[2].id:
                third_started.set()
            return await super().analyze(window=window, signals=signals)

    runner = WindowAnalysisRunner(
        acquisition=FakeAcquisition(raw, stored_signals),  # type: ignore[arg-type]
        pipeline=FakePipeline(),  # type: ignore[arg-type]
        client=StreamingClient(),
        batch_concurrency=2,
    )
    window = type("Window", (), {
        "start": datetime(2026, 8, 16, 9, tzinfo=UTC),
        "end": datetime(2026, 8, 16, 10, tzinfo=UTC),
    })()
    task = asyncio.create_task(
        runner._analyze_batches(  # noqa: SLF001
            window=window,
            batches=[[signal] for signal in signals],
            batch_input_hashes=[f"{index:x}" * 64 for index in range(3)],
            window_input_hash="f" * 64,
        )
    )

    await slow_started.wait()
    await asyncio.wait_for(third_started.wait(), timeout=1)
    release_slow.set()

    assert len(await task) == 3


async def test_failed_large_model_request_is_split_and_merged_under_same_batch() -> None:
    raw = _raw()
    stored_signals = [_signal(raw) for _ in range(20)]
    client = OversizedFailClient()
    runner = WindowAnalysisRunner(
        acquisition=FakeAcquisition(raw, stored_signals),  # type: ignore[arg-type]
        pipeline=FakePipeline(),  # type: ignore[arg-type]
        client=client,
    )
    window = type("Window", (), {
        "start": datetime(2026, 8, 16, 9, tzinfo=UTC),
        "end": datetime(2026, 8, 16, 10, tzinfo=UTC),
    })()
    signals = [
        AnalysisSignal(
            signal_id=signal.id,
            title=signal.title,
            text=signal.normalized_text,
            published_at=signal.published_at,
            source_type=signal.source_type,
            evidence_visibility=signal.evidence_visibility,
            public_provenance=signal.public_provenance,
        )
        for signal in stored_signals
    ]

    response = await runner._analyze_resilient(window=window, signals=signals)  # noqa: SLF001

    assert client.batch_sizes == [20, 10, 10]
    assert [item.signal_id for item in response.payload.signal_analyses] == [
        signal.id for signal in stored_signals
    ]
    assert response.payload.unassigned_signal_ids == [signal.id for signal in stored_signals]


def _terminal_run(
    *,
    status: PipelineRunStatus,
    next_retry_at: datetime | None = None,
) -> PipelineRun:
    return PipelineRun(
        id=uuid4(),
        pipeline_name="window_analysis",
        status=status.value,
        window_start=datetime(2026, 8, 16, 9, tzinfo=UTC),
        window_end=datetime(2026, 8, 16, 10, tzinfo=UTC),
        attempt=1,
        started_at=datetime(2026, 8, 16, 9, tzinfo=UTC),
        finished_at=datetime(2026, 8, 16, 9, 30, tzinfo=UTC),
        next_retry_at=next_retry_at,
    )


async def test_due_failed_window_is_retried_with_incremented_attempt() -> None:
    raw = _raw()
    previous = _terminal_run(
        status=PipelineRunStatus.FAILED,
        next_retry_at=datetime(2026, 8, 16, 9, 59, tzinfo=UTC),
    )
    pipeline = FakePipeline(previous)
    runner = WindowAnalysisRunner(
        acquisition=FakeAcquisition(raw, _signal(raw)),  # type: ignore[arg-type]
        pipeline=pipeline,  # type: ignore[arg-type]
        client=FakeClient(),
        clock=lambda: datetime(2026, 8, 16, 10, tzinfo=UTC),
    )

    result = await runner.run_available(
        watermark=datetime(2026, 8, 16, 10, tzinfo=UTC)
    )

    assert result.windows_succeeded == 1
    assert pipeline.events == ["retry", "artifact", "complete"]


async def test_failed_window_is_deferred_until_retry_time() -> None:
    raw = _raw()
    previous = _terminal_run(
        status=PipelineRunStatus.FAILED,
        next_retry_at=datetime(2026, 8, 16, 10, 1, tzinfo=UTC),
    )
    pipeline = FakePipeline(previous)
    runner = WindowAnalysisRunner(
        acquisition=FakeAcquisition(raw, _signal(raw)),  # type: ignore[arg-type]
        pipeline=pipeline,  # type: ignore[arg-type]
        client=FakeClient(),
        clock=lambda: datetime(2026, 8, 16, 10, tzinfo=UTC),
    )

    result = await runner.run_available(
        watermark=datetime(2026, 8, 16, 10, tzinfo=UTC)
    )

    assert result == type(result)(0, 0, 0, 0)
    assert pipeline.events == []


async def test_terminal_window_can_be_replayed_by_run_id() -> None:
    raw = _raw()
    previous = _terminal_run(status=PipelineRunStatus.SUCCEEDED)
    pipeline = FakePipeline(previous)
    runner = WindowAnalysisRunner(
        acquisition=FakeAcquisition(raw, _signal(raw)),  # type: ignore[arg-type]
        pipeline=pipeline,  # type: ignore[arg-type]
        client=FakeClient(),
        clock=lambda: datetime(2026, 8, 16, 10, tzinfo=UTC),
    )

    result = await runner.replay_run(previous.id)

    assert result.windows_succeeded == 1
    assert pipeline.events == ["replay", "artifact", "complete"]
