from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from infoscope.analysis.ask_schemas import AskComparisonInput, AskComparisonPayload
from infoscope.models import NormalizationStatus, RawInformation, ResearchStatus
from infoscope.services.ask_research_bridge import (
    AskResearchBridgeError,
    AskResearchBridgeRunner,
    PreparedBridge,
)


def _prepared() -> PreparedBridge:
    ask_id = uuid4()
    event_ids = [uuid4(), uuid4(), uuid4()]
    comparison_input = AskComparisonInput.model_validate(
        {
            "ask_id": ask_id,
            "question": "What changed?",
            "selected_event_ids": event_ids,
            "events": [
                {
                    "event_id": event_id,
                    "title": "Event",
                    "overview": "Known facts",
                    "state": "developing",
                    "display_time": "2026-08-16T00:00:00Z",
                    "claims": [],
                    "timeline": [],
                    "conflicts": [],
                    "evidence_signals": [],
                    "base_analysis": {
                        "base_analysis_id": uuid4(),
                        "summary": "Current analysis",
                        "event_type": "technology",
                        "importance": "medium",
                        "topics": [],
                        "entities": [],
                    },
                }
                for event_id in event_ids
            ],
        }
    )
    comparison_output = AskComparisonPayload.model_validate(
        {
            "ask_id": ask_id,
            "decision": "research_required",
            "answer": None,
            "event_ids": event_ids,
            "claim_ids": [],
            "timeline_entry_ids": [],
            "conflict_ids": [],
            "evidence_signal_ids": [],
            "missing_facts": [
                {
                    "event_ids": [event_ids[2], event_ids[0]],
                    "question": "Question one?",
                    "reason": "r" * 1000,
                },
                {
                    "event_ids": [event_ids[1]],
                    "question": "Question two?",
                    "reason": "Internal audit reason",
                },
            ],
            "rationale": "Internal only",
        }
    )
    return PreparedBridge(
        request=SimpleNamespace(
            id=ask_id,
            status="running",
            stage="awaiting_research",
            attempt_count=1,
            error_code=None,
        ),
        bridge=SimpleNamespace(
            id=uuid4(),
            idempotency_key=uuid4(),
            research_request_id=None,
            attempt_count=1,
            max_attempts=3,
        ),
        comparison_artifact=SimpleNamespace(id=uuid4()),
        comparison_input=comparison_input,
        comparison_output=comparison_output,
        should_run=True,
    )


def test_research_spec_preserves_questions_and_selected_event_order() -> None:
    prepared = _prepared()
    spec, source_event_ids = AskResearchBridgeRunner._research_spec(prepared)

    assert source_event_ids == prepared.comparison_input.selected_event_ids
    assert spec.source_event_ids == source_event_ids
    assert spec.research_questions == ["Question one?", "Question two?"]
    assert spec.missing_fact_descriptions == []
    assert [item.value for item in spec.allowed_source_kinds] == [
        "web_page",
        "github_document",
    ]


class _Database:
    def __init__(self, raw=None) -> None:
        self.raw = raw

    async def get(self, model, identifier):
        if self.raw is not None and identifier == self.raw.id:
            return self.raw
        return None


class _BridgeRepository:
    def __init__(self, prepared, *, sources=None, raw=None) -> None:
        self.prepared = prepared
        self.sources = sources or []
        self.database = _Database(raw)
        self.attached = []
        self.artifact = None
        self.failure = None

    async def prepare(self, ask_id, *, max_attempts):
        assert ask_id == self.prepared.request.id
        assert max_attempts == 3
        return self.prepared

    async def attach_research_request(self, bridge_id, research_request_id):
        self.attached.append((bridge_id, research_request_id))

    async def linked_research_request(self, bridge):
        return None

    async def successful_sources(self, research_request_id):
        return self.sources

    async def persist_success(self, prepared, payload):
        self.artifact = payload
        prepared.request.status = "pending"
        prepared.request.stage = "awaiting_reconciliation"
        return prepared.request

    async def persist_failure(self, prepared, *, error_code, retryable):
        self.failure = (error_code, retryable)
        terminal = not retryable or prepared.bridge.attempt_count >= prepared.bridge.max_attempts
        prepared.request.status = "failed" if terminal else "pending"
        prepared.request.stage = "awaiting_research"
        prepared.request.error_code = error_code if terminal else None
        return prepared.request


class _ResearchRepository:
    def __init__(self, request) -> None:
        self.request = request
        self.spec = None

    async def create_or_reuse(self, spec, *, max_attempts):
        self.spec = spec
        return self.request, SimpleNamespace(), True


class _ResearchRunner:
    def __init__(self, request) -> None:
        self.request = request
        self.calls = 0

    async def run(self, request_id, *, payload):
        self.calls += 1
        return self.request


class _Acquisition:
    def __init__(self) -> None:
        self.signals = []

    async def mark_normalization_started(self, raw):
        raw.normalization_status = NormalizationStatus.PROCESSING.value

    async def mark_normalization_failed(self, raw, *, error_code):
        raw.normalization_status = NormalizationStatus.FAILED.value

    async def persist_signal(self, *, raw, value, normalized_at):
        raw.normalization_status = NormalizationStatus.SUCCEEDED.value
        self.signals = [SimpleNamespace(id=uuid4())]
        return self.signals[0]

    async def list_signals_for_raw(self, raw_id):
        return self.signals


def _raw() -> RawInformation:
    return RawInformation(
        id=uuid4(),
        source_type="research",
        source_key="research:test",
        source_visibility="public",
        acquired_at=datetime.now(UTC),
        content_text="Verified public source text",
        payload={"title": "Report"},
        provenance={
            "source_kind": "web_page",
            "canonical_url": "https://example.com/report",
        },
        collector_metadata={},
        content_hash="a" * 64,
        normalization_status=NormalizationStatus.PENDING.value,
        normalization_attempts=0,
    )


def _runner(prepared, bridge_repository, research_request, acquisition):
    research_repository = _ResearchRepository(research_request)
    research_runner = _ResearchRunner(research_request)
    return (
        AskResearchBridgeRunner(
            repository=bridge_repository,
            research_repository=research_repository,
            research_runner=research_runner,
            acquisition=acquisition,
            max_attempts=3,
            research_max_attempts=3,
        ),
        research_repository,
        research_runner,
    )


async def test_bridge_normalizes_only_linked_raw_and_creates_sanitized_artifact() -> None:
    prepared = _prepared()
    raw = _raw()
    source = SimpleNamespace(
        id=uuid4(),
        candidate_index=2,
        raw_information_id=raw.id,
        canonical_url="https://example.com/report",
    )
    repository = _BridgeRepository(prepared, sources=[source], raw=raw)
    research = SimpleNamespace(
        id=uuid4(),
        status=ResearchStatus.PENDING.value,
        attempt_count=0,
        max_attempts=3,
        error_code=None,
    )
    acquisition = _Acquisition()
    runner, _, research_runner = _runner(
        prepared, repository, research, acquisition
    )
    research.status = ResearchStatus.SUCCEEDED.value

    request = await runner.run(prepared.request.id)

    assert research_runner.calls == 0
    assert (request.status, request.stage) == ("pending", "awaiting_reconciliation")
    assert repository.artifact.results[0].raw_information_id == raw.id
    serialized = repository.artifact.model_dump_json()
    assert "example.com" not in serialized
    assert "Internal audit" not in serialized
    assert "Verified public" not in serialized


async def test_retryable_research_failure_keeps_ask_pending_without_error() -> None:
    prepared = _prepared()
    repository = _BridgeRepository(prepared)
    research = SimpleNamespace(
        id=uuid4(),
        status=ResearchStatus.FAILED.value,
        attempt_count=1,
        max_attempts=3,
        error_code="RESEARCH_ALL_SOURCES_FAILED",
    )
    runner, _, research_runner = _runner(
        prepared, repository, research, _Acquisition()
    )

    with pytest.raises(AskResearchBridgeError, match="ASK_RESEARCH_RETRYABLE_FAILURE"):
        await runner.run(prepared.request.id)

    assert research_runner.calls == 1
    assert repository.failure == ("ASK_RESEARCH_RETRYABLE_FAILURE", True)
    assert prepared.request.status == "pending"
    assert prepared.request.error_code is None
    assert prepared.request.attempt_count == 1


async def test_succeeded_research_without_signals_is_terminal() -> None:
    prepared = _prepared()
    repository = _BridgeRepository(prepared)
    research = SimpleNamespace(
        id=uuid4(),
        status=ResearchStatus.SUCCEEDED.value,
        attempt_count=1,
        max_attempts=3,
        error_code=None,
    )
    runner, _, _ = _runner(prepared, repository, research, _Acquisition())

    with pytest.raises(AskResearchBridgeError, match="ASK_RESEARCH_NO_USABLE_SIGNALS"):
        await runner.run(prepared.request.id)

    assert repository.artifact is None
    assert repository.failure == ("ASK_RESEARCH_NO_USABLE_SIGNALS", False)
    assert prepared.request.status == "failed"
    assert prepared.request.stage == "awaiting_research"


async def test_normalization_failure_is_bridge_retryable_without_ask_attempt_change() -> None:
    prepared = _prepared()
    raw = _raw()
    raw.content_text = None
    source = SimpleNamespace(
        id=uuid4(),
        candidate_index=0,
        raw_information_id=raw.id,
    )
    repository = _BridgeRepository(prepared, sources=[source], raw=raw)
    research = SimpleNamespace(
        id=uuid4(),
        status=ResearchStatus.SUCCEEDED.value,
        attempt_count=1,
        max_attempts=3,
        error_code=None,
    )
    runner, _, _ = _runner(prepared, repository, research, _Acquisition())

    with pytest.raises(AskResearchBridgeError, match="ASK_RESEARCH_NORMALIZATION_FAILED"):
        await runner.run(prepared.request.id)

    assert repository.failure == ("ASK_RESEARCH_NORMALIZATION_FAILED", True)
    assert prepared.request.status == "pending"
    assert prepared.request.error_code is None
    assert prepared.request.attempt_count == 1
