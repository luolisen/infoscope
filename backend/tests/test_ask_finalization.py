from types import SimpleNamespace
from uuid import uuid4

import pytest

from infoscope.analysis.ask_schemas import (
    AskFinalizationInput,
    AskFinalizationModelPayload,
    AskFinalizationResponse,
    ask_finalization_input_hash,
)
from infoscope.analysis.schemas import TokenUsage
from infoscope.models import AskFinalArtifact
from infoscope.services.ask_finalization import (
    AskFinalizationError,
    AskFinalizationRepository,
    AskFinalizationRunner,
)


def _input() -> AskFinalizationInput:
    event_id = uuid4()
    return AskFinalizationInput.model_validate(
        {
            "ask_id": uuid4(),
            "source_comparison_artifact_id": uuid4(),
            "source_reconciliation_artifact_id": uuid4(),
            "source_comparison_hash": "1" * 64,
            "source_reconciliation_hash": "2" * 64,
            "question": "What changed?",
            "selected_event_ids": [event_id],
            "updated_event_ids": [event_id],
            "events": [
                {
                    "event_id": event_id,
                    "title": "Event",
                    "overview": "Updated persisted facts",
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
            ],
        }
    )


def _response(value: AskFinalizationInput) -> AskFinalizationResponse:
    return AskFinalizationResponse(
        payload=AskFinalizationModelPayload(
            ask_id=value.ask_id,
            answer="The persisted Event now contains the researched update.",
            event_ids=value.selected_event_ids,
            claim_ids=[],
            timeline_entry_ids=[],
            conflict_ids=[],
            evidence_signal_ids=[],
        ),
        provider="test",
        model="test-model",
        token_usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )


def test_finalization_hash_changes_with_current_facts() -> None:
    value = _input()
    changed = value.model_copy(deep=True)
    changed.events[0].overview = "A newer persisted fact"
    assert ask_finalization_input_hash(value) != ask_finalization_input_hash(changed)


def test_direct_reuse_token_usage_binds_python_none_as_sql_null() -> None:
    token_usage_type = AskFinalArtifact.__table__.c.token_usage.type
    assert token_usage_type.none_as_null is True


def test_finalization_rejects_unknown_references_and_changed_event_order() -> None:
    value = _input()
    response = _response(value)
    changed = response.payload.model_copy(update={"claim_ids": [uuid4()]})
    with pytest.raises(AskFinalizationError, match="ASK_FINALIZATION_REFERENCE_INVALID"):
        AskFinalizationRepository.validate_model_output(changed, value)

    changed = response.payload.model_copy(update={"event_ids": [uuid4()]})
    with pytest.raises(AskFinalizationError, match="ASK_FINALIZATION_OUTPUT_INVALID"):
        AskFinalizationRepository.validate_model_output(changed, value)

    changed = response.payload.model_copy(
        update={
            "answer": (
                "The answer references "
                f"{value.source_comparison_artifact_id.hex[:8]}."
            )
        }
    )
    with pytest.raises(AskFinalizationError, match="ASK_FINALIZATION_PUBLIC_ANSWER_INVALID"):
        AskFinalizationRepository.validate_model_output(changed, value)


class _Client:
    def __init__(self, value: AskFinalizationInput) -> None:
        self.value = value
        self.calls = 0

    async def finalize_ask(self, value: AskFinalizationInput) -> AskFinalizationResponse:
        self.calls += 1
        return _response(value)


class _Repository:
    def __init__(self, value: AskFinalizationInput, kind: str) -> None:
        self.value = value
        self.request = SimpleNamespace(id=value.ask_id, status="pending", stage="finalizing")
        self.prepared = SimpleNamespace(
            request=self.request,
            finalization=SimpleNamespace(id=uuid4(), finalization_kind=kind),
            run=SimpleNamespace(id=uuid4()),
        )
        self.direct = 0
        self.researched = 0

    async def prepare(self, ask_id, *, max_attempts):
        assert ask_id == self.value.ask_id
        assert max_attempts == 3
        return self.prepared

    async def input_snapshot(self, prepared):
        return self.value

    async def store_input_hash(self, finalization_id, value):
        assert finalization_id == self.prepared.finalization.id

    @staticmethod
    def validate_model_output(payload, value):
        AskFinalizationRepository.validate_model_output(payload, value)

    async def persist_direct(self, prepared):
        self.direct += 1
        self.request.status = "completed"
        return self.request

    async def persist_researched(self, prepared, *, original_input, response):
        self.researched += 1
        self.request.status = "completed"
        return self.request

    async def persist_failure(self, prepared, *, error_code, retryable):
        self.request.status = "failed"


async def test_direct_reuse_never_calls_the_model() -> None:
    value = _input()
    repository = _Repository(value, "direct_reuse")
    client = _Client(value)
    result = await AskFinalizationRunner(repository=repository, client=client, max_attempts=3).run(
        value.ask_id
    )
    assert result.status == "completed"
    assert repository.direct == 1
    assert client.calls == 0


async def test_researched_path_calls_model_and_persists_once() -> None:
    value = _input()
    repository = _Repository(value, "researched_model")
    client = _Client(value)
    result = await AskFinalizationRunner(repository=repository, client=client, max_attempts=3).run(
        value.ask_id
    )
    assert result.status == "completed"
    assert repository.researched == 1
    assert client.calls == 1
