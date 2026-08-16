from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from infoscope.analysis.ask_reconciliation_prompt import (
    ASK_EVENT_RECONCILIATION_SYSTEM_PROMPT,
    build_ask_event_reconciliation_prompt,
)
from infoscope.analysis.ask_schemas import (
    AskEventReconciliationInput,
    AskEventReconciliationPayload,
    AskEventReconciliationResponse,
    ask_reconciliation_input_hash,
)
from infoscope.analysis.schemas import TokenUsage
from infoscope.models import EventSignal
from infoscope.services.ask_event_reconciliation import (
    AskEventReconciliationError,
    AskEventReconciliationRepository,
    AskEventReconciliationRunner,
)


def _input(
    *,
    ask_id: UUID | None = None,
    event_ids: list[UUID] | None = None,
    observation_ids: list[UUID] | None = None,
) -> AskEventReconciliationInput:
    ask_id = ask_id or uuid4()
    event_ids = event_ids or [uuid4(), uuid4()]
    observation_ids = observation_ids or [uuid4(), uuid4()]
    canonical_id = observation_ids[0]
    comparison_id = uuid4()
    research_id = uuid4()
    return AskEventReconciliationInput.model_validate(
        {
            "ask_id": ask_id,
            "source_bridge_artifact_id": uuid4(),
            "source_bridge_payload": {
                "ask_id": ask_id,
                "comparison_artifact_id": comparison_id,
                "research_request_id": research_id,
                "source_event_ids": event_ids,
                "research_status": "succeeded",
                "results": [
                    {
                        "candidate_index": 0,
                        "research_source_id": uuid4(),
                        "raw_information_id": uuid4(),
                        "signal_ids": observation_ids,
                    }
                ],
            },
            "question": "What changed?",
            "missing_facts": [
                {"event_ids": event_ids, "question": "What was the verified result?"}
            ],
            "source_event_ids": event_ids,
            "events": [
                {
                    "event_id": event_id,
                    "title": f"Event {position}",
                    "overview": "Current persisted facts",
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
                        "topics": ["AI"],
                        "entities": [],
                    },
                }
                for position, event_id in enumerate(event_ids)
            ],
            "canonical_signals": [
                {
                    "canonical_signal_id": canonical_id,
                    "observation_signal_ids": observation_ids,
                    "title": "Verified update",
                    "sanitized_text": "The verified result is available.",
                    "published_at": "2026-08-16T01:00:00Z",
                    "evidence_visibility": "public",
                    "public_safe_provenance": {
                        "kind": "research",
                        "source_kind": "web_page",
                        "canonical_url": "https://example.com/result",
                    },
                }
            ],
        }
    )


def _response(value: AskEventReconciliationInput) -> AskEventReconciliationResponse:
    canonical_id = value.canonical_signals[0].canonical_signal_id
    return AskEventReconciliationResponse(
        payload=AskEventReconciliationPayload.model_validate(
            {
                "ask_id": value.ask_id,
                "event_updates": [
                    {
                        "event_id": event_id,
                        "signal_ids": [canonical_id],
                        "title": f"Updated {position}",
                        "overview": "Updated only from supplied evidence.",
                        "display_time": "2026-08-16T01:00:00Z",
                        "rationale": "The canonical Signal supports this update.",
                    }
                    for position, event_id in enumerate(value.source_event_ids)
                ],
                "unassigned_signal_ids": [],
            }
        ),
        provider="test",
        model="test",
        token_usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )


def test_schema_requires_evidence_for_every_event_update() -> None:
    value = _input()
    document = _response(value).payload.model_dump(mode="json")
    document["event_updates"][0]["signal_ids"] = []
    with pytest.raises(ValidationError):
        AskEventReconciliationPayload.model_validate(document)


def test_output_allows_one_signal_for_multiple_events_and_requires_full_coverage() -> None:
    value = _input()
    response = _response(value)
    AskEventReconciliationRepository.validate_output(response.payload, value)

    invalid = response.payload.model_copy(update={"unassigned_signal_ids": [uuid4()]})
    with pytest.raises(AskEventReconciliationError, match="ASK_RECONCILIATION_OUTPUT_INVALID"):
        AskEventReconciliationRepository.validate_output(invalid, value)


def test_all_unassigned_is_terminal_and_cannot_modify_an_event() -> None:
    value = _input()
    canonical_id = value.canonical_signals[0].canonical_signal_id
    payload = AskEventReconciliationPayload(
        ask_id=value.ask_id,
        event_updates=[],
        unassigned_signal_ids=[canonical_id],
    )
    with pytest.raises(
        AskEventReconciliationError,
        match="ASK_RECONCILIATION_NO_RELEVANT_SIGNALS",
    ):
        AskEventReconciliationRepository.validate_output(payload, value)


def test_input_hash_covers_fact_content_relationships_and_canonical_mapping() -> None:
    value = _input()
    baseline = ask_reconciliation_input_hash(value)
    changed_document = deepcopy(value.model_dump(mode="json"))
    changed_document["events"][0]["overview"] = "Concurrent update"
    changed = AskEventReconciliationInput.model_validate(changed_document)
    assert ask_reconciliation_input_hash(changed) != baseline

    changed_document = deepcopy(value.model_dump(mode="json"))
    changed_document["canonical_signals"][0]["sanitized_text"] = "Changed Signal"
    changed = AskEventReconciliationInput.model_validate(changed_document)
    assert ask_reconciliation_input_hash(changed) != baseline


def test_prompt_treats_all_supplied_text_as_untrusted_and_emits_strict_json() -> None:
    value = _input()
    assert "untrusted data" in ASK_EVENT_RECONCILIATION_SYSTEM_PROMPT
    assert "never output Event state" in ASK_EVENT_RECONCILIATION_SYSTEM_PROMPT
    prompt = build_ask_event_reconciliation_prompt(value)
    assert "ask_event_reconciliation_input.v1" in prompt
    assert str(value.source_bridge_artifact_id) in prompt


def test_event_signal_requires_exactly_one_attachment_source() -> None:
    columns = EventSignal.__table__.c
    assert columns.attached_by_pipeline_run_id.nullable
    assert columns.attached_by_ask_reconciliation_run_id.nullable
    checks = {constraint.name for constraint in EventSignal.__table__.constraints}
    assert "ck_event_signals_exactly_one_source" in checks


class _Repository:
    def __init__(self, value: AskEventReconciliationInput) -> None:
        self.value = value
        self.calls: list[str] = []
        self.request = SimpleNamespace(
            id=value.ask_id,
            status="pending",
            stage="awaiting_reconciliation",
        )
        self.prepared = SimpleNamespace(
            request=self.request,
            reconciliation=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
            bridge_payload=value.source_bridge_payload,
        )

    async def prepare(self, ask_id, *, max_attempts):
        self.calls.append("prepare")
        return self.prepared

    async def targeted_deduplicate(self, payload):
        self.calls.append("deduplicate")

    async def input_snapshot(self, prepared):
        self.calls.append("snapshot")
        return self.value

    async def store_input_hash(self, reconciliation_id, value):
        self.calls.append("hash")
        return ask_reconciliation_input_hash(value)

    def validate_output(self, payload, value):
        AskEventReconciliationRepository.validate_output(payload, value)

    async def persist_success(self, prepared, *, original_input, response):
        self.calls.append("persist")
        self.request.stage = "finalizing"
        return self.request

    async def persist_failure(self, prepared, *, error_code, retryable):
        self.calls.append("failure")


class _Client:
    def __init__(self, value: AskEventReconciliationInput) -> None:
        self.value = value

    async def reconcile_ask_events(self, value):
        return _response(value)


async def test_runner_commits_targeted_dedupe_before_model_input_and_persistence() -> None:
    value = _input()
    repository = _Repository(value)
    runner = AskEventReconciliationRunner(
        repository=repository,
        client=_Client(value),
        max_attempts=3,
    )
    request = await runner.run(value.ask_id)
    assert request.stage == "finalizing"
    assert repository.calls == ["prepare", "deduplicate", "snapshot", "hash", "persist"]
