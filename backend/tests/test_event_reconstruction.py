from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError

from infoscope.analysis.reconstruction_schemas import (
    EventReconstructionArtifact,
    EventReconstructionPayload,
    EventReconstructionResponse,
    NewEventDecision,
)
from infoscope.analysis.schemas import SignalAnalysis, TokenUsage, WindowAnalysisPayload
from infoscope.models import (
    EvidenceVisibility,
    PipelineArtifact,
    PipelineRun,
    PipelineRunStatus,
    Signal,
)
from infoscope.services.event_reconstruction import (
    EventReconstructionError,
    EventReconstructionRunner,
    EventRepository,
)


def _source() -> tuple[PipelineArtifact, PipelineRun, Signal]:
    signal_id = uuid4()
    run = PipelineRun(
        id=uuid4(),
        pipeline_name="window_analysis",
        status=PipelineRunStatus.SUCCEEDED.value,
        window_start=datetime(2026, 8, 16, 9, tzinfo=UTC),
        window_end=datetime(2026, 8, 16, 10, tzinfo=UTC),
        attempt=1,
        started_at=datetime(2026, 8, 16, 9, tzinfo=UTC),
        finished_at=datetime(2026, 8, 16, 9, 30, tzinfo=UTC),
    )
    payload = WindowAnalysisPayload(
        signal_analyses=[
            SignalAnalysis(
                signal_id=signal_id,
                categories=["technology"],
                fact_claims=["A release occurred."],
            )
        ],
        clusters=[],
        unassigned_signal_ids=[signal_id],
    )
    artifact = PipelineArtifact(
        id=uuid4(),
        pipeline_run_id=run.id,
        artifact_type="window_analysis",
        schema_version="window_analysis.v1",
        input_hash="a" * 64,
        payload=payload.model_dump(mode="json"),
        provider="deepseek",
        model="deepseek-v4-flash",
        token_usage={},
    )
    signal = Signal(
        id=signal_id,
        raw_information_id=uuid4(),
        signal_index=0,
        title="Release",
        normalized_text="A release occurred.",
        source_type="web",
        evidence_visibility=EvidenceVisibility.PUBLIC.value,
        public_provenance={"platform": "web"},
        content_hash="b" * 64,
    )
    return artifact, run, signal


class FakeEvents:
    def __init__(
        self,
        artifact,
        source_run,
        signal,
        *,
        prior=None,
        candidates=None,
        persist_error=False,
    ):
        self.artifact = artifact
        self.source_run = source_run
        self.signal = signal
        self.prior = prior
        self.candidate_values = candidates or []
        self.persisted = False
        self.rolled_back = False
        self.locked = False
        self.persist_error = persist_error

    async def rollback(self):
        self.rolled_back = True

    async def source_artifact(self, artifact_id):
        return (self.artifact, self.source_run) if artifact_id == self.artifact.id else None

    async def lock_source_artifact(self, source_artifact_id):
        assert source_artifact_id == self.artifact.id
        self.locked = True

    async def signals(self, signal_ids):
        return [self.signal]

    async def candidates(self, *, limit):
        return self.candidate_values

    async def prior_source_artifact(self, source_artifact_id):
        assert self.locked is True
        return self.prior

    async def persist_reconstruction(self, **kwargs):
        if self.persist_error:
            raise SQLAlchemyError("synthetic persistence failure")
        self.persisted = True
        return PipelineArtifact(), 1, 0, 1, False


class FakePipeline:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.failed_code: str | None = None
        self.run: PipelineRun | None = None

    async def start_run(self, *, pipeline_name, window, started_at, lower_cursor):
        self.events.append("start")
        self.run = PipelineRun(
            id=uuid4(),
            pipeline_name=pipeline_name,
            status=PipelineRunStatus.RUNNING.value,
            window_start=window.start,
            window_end=window.end,
            attempt=1,
            started_at=started_at,
        )
        return self.run

    async def get_run(self, run_id):
        return self.run if self.run is not None and self.run.id == run_id else None

    async def persist_artifact(self, **kwargs):
        self.events.append("artifact")

    async def complete_run(self, run, *, finished_at, upper_cursor):
        self.events.append("complete")

    async def fail_run(self, run, *, finished_at, next_retry_at, error_code):
        self.events.append("fail")
        self.failed_code = error_code


class FakeClient:
    def __init__(self, signal_id, *, existing_event_id=None) -> None:
        self.signal_id = signal_id
        self.existing_event_id = existing_event_id
        self.calls = 0

    async def reconstruct(self, *, window_analysis, signals, candidates):
        self.calls += 1
        if self.existing_event_id is None:
            payload = EventReconstructionPayload(
                new_events=[
                    NewEventDecision(
                        decision_key="release",
                        signal_ids=[self.signal_id],
                        title="Release",
                        overview="A release occurred.",
                        state="developing",
                        display_time=datetime(2026, 8, 16, 9, tzinfo=UTC),
                        rationale="One event",
                    )
                ],
                existing_event_updates=[],
                unassigned_signal_ids=[],
            )
        else:
            payload = EventReconstructionPayload.model_validate(
                {
                    "new_events": [],
                    "existing_event_updates": [
                        {
                            "decision_key": "update",
                            "existing_event_id": self.existing_event_id,
                            "signal_ids": [self.signal_id],
                            "title": "Updated",
                            "overview": "Updated",
                            "state": "developing",
                            "display_time": "2026-08-16T09:00:00Z",
                            "rationale": "Match",
                        }
                    ],
                    "unassigned_signal_ids": [],
                }
            )
        return EventReconstructionResponse(
            payload=payload,
            provider="deepseek",
            model="deepseek-v4-flash",
            token_usage=TokenUsage(total_tokens=10),
        )


async def test_reconstruction_persists_events_before_completing_run() -> None:
    artifact, source_run, signal = _source()
    events = FakeEvents(artifact, source_run, signal)
    pipeline = FakePipeline()
    client = FakeClient(signal.id)
    runner = EventReconstructionRunner(
        events=events,  # type: ignore[arg-type]
        pipeline=pipeline,  # type: ignore[arg-type]
        client=client,
        clock=lambda: datetime(2026, 8, 16, 10, tzinfo=UTC),
    )

    result = await runner.reconstruct(artifact.id)

    assert events.persisted is True
    assert events.locked is True
    assert pipeline.events == ["start", "complete"]
    assert result.events_created == 1
    assert result.signals_attached == 1
    assert client.calls == 1


async def test_same_input_reuses_prior_artifact_without_model_call() -> None:
    artifact, source_run, signal = _source()
    prior_payload = EventReconstructionArtifact(
        source_artifact_id=artifact.id,
        model_output=EventReconstructionPayload(
            new_events=[],
            existing_event_updates=[],
            unassigned_signal_ids=[signal.id],
        ),
        assignments=[],
    )
    prior = PipelineArtifact(
        id=uuid4(),
        pipeline_run_id=uuid4(),
        artifact_type="event_reconstruction",
        schema_version="event_reconstruction.v1",
        input_hash="c" * 64,
        payload=prior_payload.model_dump(mode="json"),
        provider="deepseek",
        model="deepseek-v4-flash",
        token_usage={},
    )
    events = FakeEvents(artifact, source_run, signal, prior=prior)
    pipeline = FakePipeline()
    client = FakeClient(signal.id)
    runner = EventReconstructionRunner(
        events=events,  # type: ignore[arg-type]
        pipeline=pipeline,  # type: ignore[arg-type]
        client=client,
        clock=lambda: datetime(2026, 8, 16, 10, tzinfo=UTC),
    )

    result = await runner.reconstruct(artifact.id)

    assert result.reused_artifact is True
    assert client.calls == 0
    assert events.locked is True
    assert pipeline.events == ["start", "complete"]


def test_event_state_policy_is_deterministic() -> None:
    assert EventRepository._next_event_state(current_state=None) == "developing"
    for state in ("developing", "confirmed", "conflicting", "cooling"):
        assert EventRepository._next_event_state(current_state=state) == state


def test_event_state_policy_rejects_an_invalid_persisted_state() -> None:
    with pytest.raises(EventReconstructionError) as captured:
        EventRepository._next_event_state(current_state="model-decides")

    assert captured.value.error_code == "RECONSTRUCTION_EVENT_STATE_INVALID"


async def test_private_provenance_fails_before_model_call() -> None:
    artifact, source_run, signal = _source()
    signal.evidence_visibility = EvidenceVisibility.PRIVATE_SANITIZED.value
    signal.public_provenance = {"username": "must-not-leak"}
    events = FakeEvents(artifact, source_run, signal)
    pipeline = FakePipeline()
    client = FakeClient(signal.id)
    runner = EventReconstructionRunner(
        events=events,  # type: ignore[arg-type]
        pipeline=pipeline,  # type: ignore[arg-type]
        client=client,
        clock=lambda: datetime(2026, 8, 16, 10, tzinfo=UTC),
    )

    with pytest.raises(EventReconstructionError) as captured:
        await runner.reconstruct(artifact.id)

    assert captured.value.error_code == "RECONSTRUCTION_PRIVATE_PROVENANCE_INVALID"
    assert client.calls == 0
    assert pipeline.events == ["start", "fail"]
    assert events.rolled_back is True


async def test_update_must_reference_a_supplied_candidate() -> None:
    artifact, source_run, signal = _source()
    outside_event_id = uuid4()
    events = FakeEvents(artifact, source_run, signal)
    pipeline = FakePipeline()
    client = FakeClient(signal.id, existing_event_id=outside_event_id)
    runner = EventReconstructionRunner(
        events=events,  # type: ignore[arg-type]
        pipeline=pipeline,  # type: ignore[arg-type]
        client=client,
        clock=lambda: datetime(2026, 8, 16, 10, tzinfo=UTC),
    )

    with pytest.raises(EventReconstructionError) as captured:
        await runner.reconstruct(artifact.id)

    assert captured.value.error_code == "RECONSTRUCTION_EVENT_OUTSIDE_CANDIDATES"
    assert pipeline.events == ["start", "fail"]


async def test_persistence_failure_rolls_back_before_stable_failure_audit() -> None:
    artifact, source_run, signal = _source()
    events = FakeEvents(artifact, source_run, signal, persist_error=True)
    pipeline = FakePipeline()
    runner = EventReconstructionRunner(
        events=events,  # type: ignore[arg-type]
        pipeline=pipeline,  # type: ignore[arg-type]
        client=FakeClient(signal.id),
        clock=lambda: datetime(2026, 8, 16, 10, tzinfo=UTC),
    )

    with pytest.raises(EventReconstructionError) as captured:
        await runner.reconstruct(artifact.id)

    assert captured.value.error_code == "RECONSTRUCTION_PERSISTENCE_FAILED"
    assert events.rolled_back is True
    assert pipeline.failed_code == "RECONSTRUCTION_PERSISTENCE_FAILED"
    assert pipeline.events == ["start", "fail"]
