from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from infoscope.analysis.ask_schemas import (
    AskBaseAnalysisInput,
    AskEventInput,
    AskReconciliationSignal,
)
from infoscope.analysis.backwrite_schemas import (
    BackwriteEventUpdate,
    BackwriteReconciliationInput,
    BackwriteReconciliationPayload,
    BackwriteSnapshotPayload,
    BackwriteSnapshotSpec,
    backwrite_reconciliation_input_hash,
    backwrite_snapshot_hash,
)
from infoscope.models import (
    BackwriteCycle,
    BackwriteItem,
    BackwriteReconciliationRun,
    EventSignal,
)
from infoscope.services.backwrite import (
    BackwriteRepository,
    BackwriteRunner,
    PreparedBackwriteItem,
    frozen_queue_indices,
)


def _event(event_id):
    return AskEventInput(
        event_id=event_id,
        title="Event",
        overview="Current facts",
        state="developing",
        display_time=datetime(2026, 8, 16, tzinfo=UTC),
        claims=[],
        timeline=[],
        conflicts=[],
        evidence_signals=[],
        base_analysis=AskBaseAnalysisInput(
            base_analysis_id=uuid4(),
            summary="Analysis",
            event_type="news",
            importance="medium",
            topics=[],
            entities=[],
        ),
    )


def _input(*, signals: list[AskReconciliationSignal] | None = None):
    item_id = uuid4()
    event_id = uuid4()
    return BackwriteReconciliationInput(
        item_id=item_id,
        event_id=event_id,
        event=_event(event_id),
        canonical_signals=signals or [],
    )


def test_frozen_queue_alternates_edges_without_duplicates() -> None:
    assert frozen_queue_indices(0) == []
    assert frozen_queue_indices(1) == [0]
    assert frozen_queue_indices(7) == [0, 6, 1, 5, 2, 4, 3]
    assert frozen_queue_indices(6) == [0, 5, 1, 4, 2, 3]
    assert sorted(frozen_queue_indices(11)) == list(range(11))


def test_snapshot_hash_preserves_backend_order_and_rejects_duplicates() -> None:
    user_id = uuid4()
    event_ids = [uuid4(), uuid4()]
    forward = BackwriteSnapshotPayload(user_id=user_id, ordered_event_ids=event_ids)
    reverse = BackwriteSnapshotPayload(user_id=user_id, ordered_event_ids=list(reversed(event_ids)))
    assert backwrite_snapshot_hash(forward) != backwrite_snapshot_hash(reverse)
    with pytest.raises(ValidationError):
        BackwriteSnapshotSpec(
            user_id=user_id,
            idempotency_key=uuid4(),
            ordered_event_ids=[event_ids[0], event_ids[0]],
        )


def test_reconciliation_input_hash_covers_event_facts_and_signal_order() -> None:
    first = AskReconciliationSignal(
        canonical_signal_id=uuid4(),
        observation_signal_ids=[uuid4()],
        title="First",
        sanitized_text="First evidence",
        published_at=None,
        evidence_visibility="public",
        public_safe_provenance={
            "kind": "research",
            "source_kind": "web_page",
            "canonical_url": "https://example.com/first",
        },
    )
    second = AskReconciliationSignal(
        canonical_signal_id=uuid4(),
        observation_signal_ids=[uuid4()],
        title="Second",
        sanitized_text="Second evidence",
        published_at=datetime(2026, 8, 16, tzinfo=UTC),
        evidence_visibility="private_sanitized",
        public_safe_provenance=None,
    )
    value = _input(signals=[first, second])
    reversed_value = value.model_copy(update={"canonical_signals": [second, first]})
    changed_event = value.model_copy(
        update={"event": value.event.model_copy(update={"overview": "Changed facts"})}
    )
    assert backwrite_reconciliation_input_hash(value) != backwrite_reconciliation_input_hash(
        reversed_value
    )
    assert backwrite_reconciliation_input_hash(value) != backwrite_reconciliation_input_hash(
        changed_event
    )


def test_private_reconciliation_signal_rejects_provenance() -> None:
    with pytest.raises(ValidationError):
        AskReconciliationSignal(
            canonical_signal_id=uuid4(),
            observation_signal_ids=[uuid4()],
            title=None,
            sanitized_text="Sanitized private evidence",
            published_at=None,
            evidence_visibility="private_sanitized",
            public_safe_provenance={
                "kind": "telegram_public",
                "platform": "telegram",
                "chat_title": "Private group",
            },
        )


def test_output_requires_complete_signal_coverage() -> None:
    signal = AskReconciliationSignal(
        canonical_signal_id=uuid4(),
        observation_signal_ids=[uuid4()],
        title=None,
        sanitized_text="New evidence",
        published_at=None,
        evidence_visibility="public",
        public_safe_provenance=None,
    )
    value = _input(signals=[signal])
    output = BackwriteReconciliationPayload(
        item_id=value.item_id,
        event_id=value.event_id,
        decision="no_change",
        event_update=None,
        unassigned_signal_ids=[],
        rationale="No change",
    )
    with pytest.raises(RuntimeError, match="BACKWRITE_OUTPUT_INVALID"):
        BackwriteRepository.validate_output(output, value)
    update = output.model_copy(
        update={
            "decision": "update",
            "event_update": BackwriteEventUpdate(
                title="Updated",
                overview="Updated facts",
                display_time=datetime(2026, 8, 16, 1, tzinfo=UTC),
                signal_ids=[signal.canonical_signal_id],
            ),
        }
    )
    BackwriteRepository.validate_output(update, value)


class _NoModelClient:
    async def reconcile_backwrite_event(self, _value):
        raise AssertionError("zero canonical Signals must not call the model")


class _ResearchRunner:
    async def create_and_run(self, _spec):
        return SimpleNamespace(id=uuid4(), status="succeeded")


class _ZeroSignalRepository:
    def __init__(self, value):
        self.value = value
        self.no_change = False
        self.failure = None

    async def attach_research_request(self, _item_id, _request_id):
        return None

    async def successful_sources(self, _request_id):
        return [SimpleNamespace(raw_information_id=uuid4())]

    async def input_snapshot(self, _item_id):
        return self.value

    async def persist_research_artifact(self, _prepared, *, request, results):
        return SimpleNamespace(id=uuid4(), research_request_id=request.id, results=results)

    async def deduplicate_research_results(self, _results):
        return None

    async def store_input_hash(self, _item_id, _value):
        return backwrite_reconciliation_input_hash(self.value)

    async def persist_no_change(self, _prepared, _value):
        self.no_change = True

    async def persist_failure(self, _prepared, *, error_code, retryable):
        self.failure = (error_code, retryable)


class _ZeroSignalRunner(BackwriteRunner):
    async def _normalize_sources(self, _sources):
        return [], 0


class _NormalizationFailureRunner(BackwriteRunner):
    async def _normalize_sources(self, sources):
        return [], len(sources)


@pytest.mark.asyncio
async def test_zero_canonical_signals_persist_no_change_without_model() -> None:
    value = _input()
    repository = _ZeroSignalRepository(value)
    runner = _ZeroSignalRunner(
        repository=repository,
        research_repository=SimpleNamespace(),
        research_runner=_ResearchRunner(),
        acquisition=SimpleNamespace(),
        client=_NoModelClient(),
        max_attempts=3,
    )
    item = BackwriteItem(
        id=value.item_id,
        cycle_id=uuid4(),
        event_id=value.event_id,
        snapshot_position=0,
        queue_position=0,
        max_attempts=3,
    )
    prepared = PreparedBackwriteItem(
        BackwriteCycle(
            id=uuid4(),
            user_id=uuid4(),
            idempotency_key=uuid4(),
            input_hash="0" * 64,
            schema_version="backwrite_snapshot.v1",
            status="running",
            snapshot_payload={},
            item_count=1,
        ),
        item,
        BackwriteReconciliationRun(
            id=uuid4(),
            item_id=item.id,
            attempt=1,
            status="running",
            started_at=datetime.now(UTC),
        ),
    )
    await runner._run_item(prepared)
    assert repository.no_change
    assert repository.failure is None


@pytest.mark.asyncio
async def test_all_normalization_failures_do_not_forge_no_change() -> None:
    value = _input()
    repository = _ZeroSignalRepository(value)
    runner = _NormalizationFailureRunner(
        repository=repository,
        research_repository=SimpleNamespace(),
        research_runner=_ResearchRunner(),
        acquisition=SimpleNamespace(),
        client=_NoModelClient(),
        max_attempts=3,
    )
    item = BackwriteItem(
        id=value.item_id,
        cycle_id=uuid4(),
        event_id=value.event_id,
        snapshot_position=0,
        queue_position=0,
        max_attempts=3,
    )
    prepared = PreparedBackwriteItem(
        BackwriteCycle(
            id=uuid4(),
            user_id=uuid4(),
            idempotency_key=uuid4(),
            input_hash="0" * 64,
            schema_version="backwrite_snapshot.v1",
            status="running",
            snapshot_payload={},
            item_count=1,
        ),
        item,
        BackwriteReconciliationRun(
            id=uuid4(),
            item_id=item.id,
            attempt=1,
            status="running",
            started_at=datetime.now(UTC),
        ),
    )
    await runner._run_item(prepared)
    assert not repository.no_change
    assert repository.failure == ("BACKWRITE_RESEARCH_NORMALIZATION_FAILED", True)


def test_event_signal_requires_exactly_one_auditable_source() -> None:
    check = next(
        item
        for item in EventSignal.__table__.constraints
        if item.name == "ck_event_signals_exactly_one_source"
    )
    expression = str(check.sqltext)
    assert "attached_by_pipeline_run_id" in expression
    assert "attached_by_ask_reconciliation_run_id" in expression
    assert "attached_by_backwrite_reconciliation_run_id" in expression
    assert expression.endswith("= 1")
