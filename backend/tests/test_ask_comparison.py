from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from infoscope.analysis.ask_schemas import (
    AskComparisonInput,
    AskComparisonPayload,
    AskComparisonResponse,
    AskRequestSpec,
    ask_input_hash,
)
from infoscope.analysis.schemas import TokenUsage
from infoscope.integrations.research.client import ResearchRuntimeError
from infoscope.services.ask_comparison import AskComparisonError, AskComparisonRunner


def _input(*, ask_id: UUID | None = None, event_ids: list[UUID] | None = None):
    selected = event_ids or [uuid4(), uuid4()]
    return AskComparisonInput.model_validate(
        {
            "ask_id": ask_id or uuid4(),
            "question": "How do these events differ?",
            "selected_event_ids": selected,
            "events": [
                {
                    "event_id": event_id,
                    "title": f"Event {position}",
                    "overview": "Known facts only",
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
                for position, event_id in enumerate(selected)
            ],
        }
    )


def _response(value: AskComparisonInput, decision: str = "answerable"):
    missing_facts = []
    answer = "The persisted facts show a difference."
    if decision == "research_required":
        answer = None
        missing_facts = [
            {
                "event_ids": value.selected_event_ids,
                "question": "What was the verified outcome?",
                "reason": "The current facts do not contain the outcome.",
            }
        ]
    return AskComparisonResponse(
        payload=AskComparisonPayload(
            ask_id=value.ask_id,
            decision=decision,
            answer=answer,
            event_ids=value.selected_event_ids,
            claim_ids=[],
            timeline_entry_ids=[],
            conflict_ids=[],
            evidence_signal_ids=[],
            missing_facts=missing_facts,
            rationale="Compared only the supplied facts.",
        ),
        provider="test",
        model="test",
        token_usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )


def test_request_and_output_schemas_enforce_order_uniqueness_and_limits() -> None:
    event_id = uuid4()
    with pytest.raises(ValidationError, match="selected_event_ids must be unique"):
        AskRequestSpec(
            user_id=uuid4(),
            question=" question ",
            selected_event_ids=[event_id, event_id],
        )

    value = _input(event_ids=[event_id])
    document = _response(value, "research_required").payload.model_dump()
    document["missing_facts"] = document["missing_facts"] * 9
    with pytest.raises(ValidationError):
        AskComparisonPayload.model_validate(document)

    document = _response(value).payload.model_dump()
    document["answer"] = "The fact changed (claim c44d430d)."
    with pytest.raises(
        ValidationError,
        match="public answer must not contain internal identifiers",
    ):
        AskComparisonPayload.model_validate(document)


def test_input_hash_excludes_ask_id_but_preserves_selection_order() -> None:
    event_ids = [uuid4(), uuid4()]
    first = _input(ask_id=uuid4(), event_ids=event_ids)
    second_document = first.model_dump()
    second_document["ask_id"] = uuid4()
    second = AskComparisonInput.model_validate(second_document)
    assert ask_input_hash(first) == ask_input_hash(second)

    reversed_document = first.model_dump()
    reversed_document["selected_event_ids"] = list(reversed(event_ids))
    reversed_document["events"] = list(reversed(reversed_document["events"]))
    assert ask_input_hash(first) != ask_input_hash(
        AskComparisonInput.model_validate(reversed_document)
    )


def test_output_validation_rejects_changed_event_order_and_unknown_ids() -> None:
    value = _input()
    payload = _response(value).payload
    changed = payload.model_copy(update={"event_ids": list(reversed(payload.event_ids))})
    with pytest.raises(AskComparisonError, match="ASK_OUTPUT_EVENT_ORDER_INVALID"):
        AskComparisonRunner._validate_output(changed, value)

    changed = payload.model_copy(update={"claim_ids": [uuid4()]})
    with pytest.raises(AskComparisonError, match="ASK_OUTPUT_REFERENCE_INVALID"):
        AskComparisonRunner._validate_output(changed, value)

    changed = payload.model_copy(
        update={"answer": f"The answer references {value.ask_id.hex[:8]}."}
    )
    with pytest.raises(AskComparisonError, match="ASK_OUTPUT_PUBLIC_ANSWER_INVALID"):
        AskComparisonRunner._validate_output(changed, value)


class _Client:
    def __init__(self, decision: str) -> None:
        self.decision = decision
        self.calls = 0

    async def compare_ask(self, value):
        self.calls += 1
        return _response(value, self.decision)


class _Repository:
    def __init__(self, value: AskComparisonInput) -> None:
        self.value = value
        self.request = SimpleNamespace(
            id=value.ask_id,
            question=value.question,
            input_hash=ask_input_hash(value),
            status="pending",
            stage="comparing",
            attempt_count=0,
            error_code=None,
        )
        self.run = SimpleNamespace(id=uuid4())
        self.artifacts = []

    async def prepare_run(self, ask_id):
        assert ask_id == self.request.id
        if self.request.status == "completed" or self.request.stage == "awaiting_research":
            return self.request, None
        self.request.status = "running"
        self.request.attempt_count += 1
        return self.request, self.run

    async def selected_event_ids(self, ask_id):
        return self.value.selected_event_ids

    async def input_snapshot(self, **kwargs):
        return self.value

    async def persist_success(self, *, input_snapshot, response, **kwargs):
        self.artifacts.append((deepcopy(input_snapshot), deepcopy(response.payload)))
        if response.payload.decision == "research_required":
            available = kwargs.get("research_available", True)
            self.request.status = "pending" if available else "failed"
            self.request.stage = "awaiting_research"
            if not available:
                self.request.error_code = "ASK_RESEARCH_CAPABILITY_UNAVAILABLE"
        else:
            self.request.status = "pending"
            self.request.stage = "finalizing"
        return self.request

    async def persist_failure(self, request_id, run_id, error_code):
        self.request.status = "failed"
        self.request.error_code = error_code


async def test_research_required_waits_without_a_second_model_call() -> None:
    value = _input()
    repository = _Repository(value)
    client = _Client("research_required")
    runner = AskComparisonRunner(repository=repository, client=client, max_attempts=3)

    request = await runner.run(value.ask_id, input_snapshot=value)
    assert (request.status, request.stage) == ("pending", "awaiting_research")
    assert len(repository.artifacts) == 1

    repeated = await runner.run(value.ask_id)
    assert repeated is request
    assert client.calls == 1


async def test_research_required_fails_before_bridge_when_capability_is_unavailable() -> None:
    value = _input()
    repository = _Repository(value)

    async def unavailable() -> None:
        raise ResearchRuntimeError("RESEARCH_CAPABILITY_UNAVAILABLE")

    runner = AskComparisonRunner(
        repository=repository,
        client=_Client("research_required"),
        max_attempts=3,
        research_capability_check=unavailable,
    )

    request = await runner.run(value.ask_id, input_snapshot=value)

    assert (request.status, request.stage) == ("failed", "awaiting_research")
    assert request.error_code == "ASK_RESEARCH_CAPABILITY_UNAVAILABLE"
    assert len(repository.artifacts) == 1


async def test_changed_snapshot_fails_before_model_and_creates_no_artifact() -> None:
    value = _input()
    repository = _Repository(value)
    repository.request.input_hash = "0" * 64
    client = _Client("answerable")
    runner = AskComparisonRunner(repository=repository, client=client, max_attempts=3)

    with pytest.raises(AskComparisonError, match="ASK_INPUT_CHANGED"):
        await runner.run(value.ask_id, input_snapshot=value)
    assert client.calls == 0
    assert repository.artifacts == []
    assert repository.request.error_code == "ASK_INPUT_CHANGED"
