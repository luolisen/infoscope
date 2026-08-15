from datetime import UTC, datetime
from uuid import uuid4

from infoscope.analysis.schemas import (
    AnalysisResponse,
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
    def __init__(self, raw: RawInformation, signal: Signal) -> None:
        self.raw = raw
        self.signal = signal

    async def earliest_raw_acquired_at(self):
        return datetime(2026, 8, 16, 9, tzinfo=UTC)

    async def list_raw_window(self, *, window, after, limit):
        return [self.raw] if after is None else []

    async def list_signals_for_raw(self, raw_id):
        return [self.signal]


class FakePipeline:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.failed_code: str | None = None

    async def latest_successful_window_end(self, pipeline_name):
        return None

    async def checkpoint_cursor(self, pipeline_name):
        return None

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

    async def persist_artifact(self, **kwargs):
        self.events.append("artifact")

    async def complete_run(self, run, *, finished_at, upper_cursor):
        self.events.append("complete")

    async def fail_run(self, run, *, finished_at, next_retry_at, error_code):
        self.events.append("fail")
        self.failed_code = error_code


class FakeClient:
    async def analyze(self, *, window, signals):
        signal_id = signals[0].signal_id
        return AnalysisResponse(
            payload=WindowAnalysisPayload(
                signal_analyses=[
                    SignalAnalysis(
                        signal_id=signal_id,
                        categories=["technology"],
                        fact_claims=["Evidence"],
                    )
                ],
                clusters=[],
                unassigned_signal_ids=[signal_id],
            ),
            provider="deepseek",
            model="deepseek-v4-pro",
            token_usage=TokenUsage(total_tokens=10),
        )


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


async def test_oversized_window_is_rejected_before_api() -> None:
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
    assert pipeline.failed_code == "WINDOW_INPUT_LIMIT_EXCEEDED"
