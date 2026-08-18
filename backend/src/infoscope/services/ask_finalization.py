from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Protocol
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import inspect, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from infoscope.analysis.ask_schemas import (
    AskComparisonInput,
    AskComparisonPayload,
    AskEventReconciliationArtifactPayload,
    AskFinalAnswerPayload,
    AskFinalizationInput,
    AskFinalizationModelPayload,
    AskFinalizationResponse,
    ask_finalization_input_hash,
    public_answer_references_internal_uuid,
)
from infoscope.analysis.client import AnalysisError
from infoscope.models import (
    AskComparisonArtifact,
    AskEventReconciliationArtifact,
    AskFinalArtifact,
    AskFinalization,
    AskFinalizationRun,
    AskRequest,
    AskRequestEvent,
    BaseAnalysis,
    Claim,
    ClaimSignal,
    Conflict,
    ConflictClaim,
    ConflictSignal,
    Event,
    EventSignal,
    Signal,
    TimelineClaim,
    TimelineEntry,
)
from infoscope.services.ask_comparison import (
    AskComparisonError,
    AskComparisonRepository,
    AskComparisonRunner,
)


class AskFinalizationError(RuntimeError):
    def __init__(self, error_code: str, *, retryable: bool = False) -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.retryable = retryable


class AskFinalizationClient(Protocol):
    async def finalize_ask(self, value: AskFinalizationInput) -> AskFinalizationResponse: ...


@dataclass(slots=True)
class PreparedFinalization:
    request: AskRequest
    comparison: AskComparisonArtifact
    reconciliation: AskEventReconciliationArtifact | None
    finalization: AskFinalization
    run: AskFinalizationRun | None


class AskFinalizationRepository:
    def __init__(self, database: AsyncSession) -> None:
        self.database = database

    async def prepare(self, ask_id: UUID, *, max_attempts: int) -> PreparedFinalization:
        request = (
            await self.database.execute(
                select(AskRequest).where(AskRequest.id == ask_id).with_for_update()
            )
        ).scalar_one_or_none()
        if request is None:
            raise AskFinalizationError("ASK_REQUEST_NOT_FOUND")
        comparison = (
            await self.database.execute(
                select(AskComparisonArtifact)
                .where(AskComparisonArtifact.ask_request_id == ask_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if comparison is None:
            raise AskFinalizationError("ASK_FINALIZATION_COMPARISON_MISSING")
        try:
            comparison_payload = AskComparisonPayload.model_validate(comparison.output)
        except ValidationError as error:
            raise AskFinalizationError("ASK_FINALIZATION_SOURCE_INVALID") from error
        if comparison_payload.ask_id != request.id:
            raise AskFinalizationError("ASK_FINALIZATION_SOURCE_INVALID")

        reconciliation = None
        kind = "direct_reuse"
        if comparison_payload.decision == "research_required":
            kind = "researched_model"
            reconciliation = (
                await self.database.execute(
                    select(AskEventReconciliationArtifact)
                    .where(AskEventReconciliationArtifact.ask_request_id == ask_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if reconciliation is None:
                raise AskFinalizationError("ASK_FINALIZATION_RECONCILIATION_MISSING")

        finalization = (
            await self.database.execute(
                select(AskFinalization)
                .where(AskFinalization.ask_request_id == ask_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if finalization is None:
            finalization = AskFinalization(
                ask_request_id=ask_id,
                source_comparison_artifact_id=comparison.id,
                source_reconciliation_artifact_id=(reconciliation.id if reconciliation else None),
                finalization_kind=kind,
                status="pending",
                attempt_count=0,
                max_attempts=max_attempts,
            )
            self.database.add(finalization)
            await self.database.flush()
        elif (
            finalization.source_comparison_artifact_id != comparison.id
            or finalization.source_reconciliation_artifact_id
            != (reconciliation.id if reconciliation else None)
            or finalization.finalization_kind != kind
        ):
            raise AskFinalizationError("ASK_FINALIZATION_SOURCE_MISMATCH")

        if finalization.status == "completed" and request.status == "completed":
            await self.database.commit()
            return PreparedFinalization(request, comparison, reconciliation, finalization, None)
        if request.status == "running" or finalization.status == "running":
            await self.database.commit()
            return PreparedFinalization(request, comparison, reconciliation, finalization, None)
        if request.status != "pending" or request.stage != "finalizing":
            raise AskFinalizationError("ASK_FINALIZATION_NOT_READY")
        if finalization.attempt_count >= finalization.max_attempts:
            raise AskFinalizationError("ASK_FINALIZATION_ATTEMPTS_EXHAUSTED")

        now = datetime.now(UTC)
        finalization.attempt_count += 1
        finalization.status = "running"
        finalization.error_code = None
        finalization.started_at = now
        finalization.finished_at = None
        request.status = "running"
        request.error_code = None
        request.started_at = now
        request.finished_at = None
        run = AskFinalizationRun(
            finalization_id=finalization.id,
            attempt=finalization.attempt_count,
            status="running",
            started_at=now,
        )
        self.database.add(run)
        await self.database.commit()
        return PreparedFinalization(request, comparison, reconciliation, finalization, run)

    async def input_snapshot(self, prepared: PreparedFinalization) -> AskFinalizationInput:
        if prepared.reconciliation is None:
            raise AskFinalizationError("ASK_FINALIZATION_RECONCILIATION_MISSING")
        try:
            reconciliation_payload = AskEventReconciliationArtifactPayload.model_validate(
                prepared.reconciliation.payload
            )
        except ValidationError as error:
            raise AskFinalizationError("ASK_FINALIZATION_SOURCE_INVALID") from error
        if reconciliation_payload.ask_id != prepared.request.id:
            raise AskFinalizationError("ASK_FINALIZATION_SOURCE_INVALID")
        selected = await AskComparisonRepository(self.database).selected_event_ids(
            prepared.request.id
        )
        comparison_snapshot = await AskComparisonRepository(self.database).input_snapshot(
            ask_id=prepared.request.id,
            question=prepared.request.question,
            selected_event_ids=selected,
        )
        return AskFinalizationInput(
            ask_id=prepared.request.id,
            source_comparison_artifact_id=prepared.comparison.id,
            source_reconciliation_artifact_id=prepared.reconciliation.id,
            source_comparison_hash=self._document_hash(prepared.comparison.output),
            source_reconciliation_hash=self._document_hash(prepared.reconciliation.payload),
            question=prepared.request.question,
            selected_event_ids=selected,
            updated_event_ids=reconciliation_payload.updated_event_ids,
            events=comparison_snapshot.events,
        )

    @staticmethod
    def _document_hash(value: dict[str, object]) -> str:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return sha256(encoded).hexdigest()

    async def store_input_hash(self, finalization_id: UUID, value: AskFinalizationInput) -> None:
        finalization = await self.database.get(AskFinalization, finalization_id)
        if finalization is None:
            raise AskFinalizationError("ASK_FINALIZATION_STATE_MISSING")
        digest = ask_finalization_input_hash(value)
        if finalization.input_hash is not None and finalization.input_hash != digest:
            raise AskFinalizationError("ASK_FINALIZATION_INPUT_CHANGED")
        finalization.input_hash = digest
        await self.database.commit()

    async def _lock_facts(self, event_ids: list[UUID]) -> None:
        event_scoped = (Event, BaseAnalysis, Claim, TimelineEntry, Conflict)
        for model in event_scoped:
            await self.database.execute(
                select(model)
                .where(model.event_id.in_(event_ids))
                .order_by(model.id)
                .with_for_update()
            )
        signal_ids = list(
            (
                await self.database.execute(
                    select(EventSignal.signal_id)
                    .where(EventSignal.event_id.in_(event_ids))
                    .order_by(EventSignal.event_id, EventSignal.signal_id)
                    .with_for_update()
                )
            ).scalars()
        )
        if signal_ids:
            await self.database.execute(
                select(Signal)
                .where(Signal.id.in_(signal_ids))
                .order_by(Signal.id)
                .with_for_update()
            )
        relation_queries = (
            select(ClaimSignal)
            .join(Claim, Claim.id == ClaimSignal.claim_id)
            .where(Claim.event_id.in_(event_ids)),
            select(TimelineClaim)
            .join(TimelineEntry, TimelineEntry.id == TimelineClaim.timeline_entry_id)
            .where(TimelineEntry.event_id.in_(event_ids)),
            select(ConflictClaim)
            .join(Conflict, Conflict.id == ConflictClaim.conflict_id)
            .where(Conflict.event_id.in_(event_ids)),
            select(ConflictSignal)
            .join(Conflict, Conflict.id == ConflictSignal.conflict_id)
            .where(Conflict.event_id.in_(event_ids)),
        )
        for query in relation_queries:
            await self.database.execute(query.with_for_update())

    @staticmethod
    def validate_model_output(
        payload: AskFinalizationModelPayload, value: AskFinalizationInput
    ) -> None:
        if payload.ask_id != value.ask_id or payload.event_ids != value.selected_event_ids:
            raise AskFinalizationError("ASK_FINALIZATION_OUTPUT_INVALID")
        if public_answer_references_internal_uuid(payload.answer, value):
            raise AskFinalizationError(
                "ASK_FINALIZATION_PUBLIC_ANSWER_INVALID",
                retryable=True,
            )
        maps = (
            (payload.claim_ids, {x.claim_id for event in value.events for x in event.claims}),
            (
                payload.timeline_entry_ids,
                {x.timeline_entry_id for event in value.events for x in event.timeline},
            ),
            (
                payload.conflict_ids,
                {x.conflict_id for event in value.events for x in event.conflicts},
            ),
            (
                payload.evidence_signal_ids,
                {x.signal_id for event in value.events for x in event.evidence_signals},
            ),
        )
        if any(not set(ids) <= candidates for ids, candidates in maps):
            raise AskFinalizationError("ASK_FINALIZATION_REFERENCE_INVALID")

    async def persist_direct(self, prepared: PreparedFinalization) -> AskRequest:
        try:
            source = AskComparisonPayload.model_validate(prepared.comparison.output)
            source_input = AskComparisonInput.model_validate(prepared.comparison.input_snapshot)
        except ValidationError as error:
            raise AskFinalizationError("ASK_FINALIZATION_SOURCE_INVALID") from error
        if source.decision != "answerable" or source.answer is None:
            raise AskFinalizationError("ASK_FINALIZATION_SOURCE_INVALID")
        if source_input.ask_id != prepared.request.id:
            raise AskFinalizationError("ASK_FINALIZATION_SOURCE_INVALID")
        try:
            AskComparisonRunner._validate_output(source, source_input)
        except AskComparisonError as error:
            raise AskFinalizationError("ASK_FINALIZATION_SOURCE_INVALID") from error
        payload = AskFinalAnswerPayload(
            ask_id=prepared.request.id,
            answer=source.answer,
            event_ids=source.event_ids,
            claim_ids=source.claim_ids,
            timeline_entry_ids=source.timeline_entry_ids,
            conflict_ids=source.conflict_ids,
            evidence_signal_ids=source.evidence_signal_ids,
            updated_event_ids=[],
        )
        return await self._persist_success(prepared, payload=payload, response=None)

    async def persist_researched(
        self,
        prepared: PreparedFinalization,
        *,
        original_input: AskFinalizationInput,
        response: AskFinalizationResponse,
    ) -> AskRequest:
        request_id = prepared.request.id
        comparison_id = prepared.comparison.id
        reconciliation_id = prepared.reconciliation.id
        finalization_id = prepared.finalization.id
        run_id = prepared.run.id
        await self.database.rollback()
        request = (
            await self.database.execute(
                select(AskRequest).where(AskRequest.id == request_id).with_for_update()
            )
        ).scalar_one()
        comparison = (
            await self.database.execute(
                select(AskComparisonArtifact)
                .where(AskComparisonArtifact.id == comparison_id)
                .with_for_update()
            )
        ).scalar_one()
        reconciliation = (
            await self.database.execute(
                select(AskEventReconciliationArtifact)
                .where(AskEventReconciliationArtifact.id == reconciliation_id)
                .with_for_update()
            )
        ).scalar_one()
        finalization = (
            await self.database.execute(
                select(AskFinalization)
                .where(AskFinalization.id == finalization_id)
                .with_for_update()
            )
        ).scalar_one()
        run = (
            await self.database.execute(
                select(AskFinalizationRun)
                .where(AskFinalizationRun.id == run_id)
                .with_for_update()
            )
        ).scalar_one()
        await self.database.execute(
            select(AskRequestEvent)
            .where(AskRequestEvent.ask_request_id == request_id)
            .order_by(AskRequestEvent.position)
            .with_for_update()
        )
        await self._lock_facts(original_input.selected_event_ids)
        prepared.request = request
        prepared.comparison = comparison
        prepared.reconciliation = reconciliation
        prepared.finalization = finalization
        prepared.run = run
        current = await self.input_snapshot(prepared)
        if ask_finalization_input_hash(current) != ask_finalization_input_hash(original_input):
            raise AskFinalizationError("ASK_FINALIZATION_INPUT_CHANGED")
        self.validate_model_output(response.payload, current)
        payload = AskFinalAnswerPayload(
            **response.payload.model_dump(exclude={"schema_version"}),
            updated_event_ids=current.updated_event_ids,
        )
        return await self._persist_success(prepared, payload=payload, response=response)

    async def _persist_success(
        self,
        prepared: PreparedFinalization,
        *,
        payload: AskFinalAnswerPayload,
        response: AskFinalizationResponse | None,
    ) -> AskRequest:
        finalization = await self.database.get(AskFinalization, prepared.finalization.id)
        run = await self.database.get(AskFinalizationRun, prepared.run.id)
        request = await self.database.get(AskRequest, prepared.request.id)
        if finalization is None or run is None or request is None:
            raise AskFinalizationError("ASK_FINALIZATION_STATE_MISSING")
        artifact = AskFinalArtifact(
            finalization_id=finalization.id,
            created_by_run_id=run.id,
            ask_request_id=request.id,
            finalization_kind=finalization.finalization_kind,
            schema_version="ask_final_answer.v1",
            input_hash=finalization.input_hash,
            payload=payload.model_dump(mode="json"),
            provider=response.provider if response else None,
            model=response.model if response else None,
            token_usage=response.token_usage.model_dump(mode="json") if response else None,
        )
        self.database.add(artifact)
        finished = datetime.now(UTC)
        run.status = "completed"
        run.finished_at = finished
        finalization.status = "completed"
        finalization.finished_at = finished
        request.status = "completed"
        request.error_code = None
        request.finished_at = finished
        await self.database.commit()
        return request

    async def persist_failure(
        self, prepared: PreparedFinalization, *, error_code: str, retryable: bool
    ) -> None:
        finalization_identity = inspect(prepared.finalization).identity
        run_identity = inspect(prepared.run).identity if prepared.run is not None else None
        request_identity = inspect(prepared.request).identity
        if (
            finalization_identity is None
            or run_identity is None
            or request_identity is None
        ):
            raise AskFinalizationError("ASK_FINALIZATION_STATE_MISSING")
        finalization_id = finalization_identity[0]
        run_id = run_identity[0]
        request_id = request_identity[0]
        await self.database.rollback()
        finalization = await self.database.get(AskFinalization, finalization_id)
        run = await self.database.get(AskFinalizationRun, run_id)
        request = await self.database.get(AskRequest, request_id)
        if finalization is None or run is None or request is None:
            raise AskFinalizationError("ASK_FINALIZATION_STATE_MISSING")
        finished = datetime.now(UTC)
        terminal = not retryable or finalization.attempt_count >= finalization.max_attempts
        run.status = "failed"
        run.error_code = error_code
        run.finished_at = finished
        finalization.status = "failed"
        finalization.error_code = error_code
        finalization.finished_at = finished
        request.status = "failed" if terminal else "pending"
        request.stage = "finalizing"
        request.error_code = error_code if terminal else None
        request.finished_at = finished if terminal else None
        await self.database.commit()


class AskFinalizationRunner:
    def __init__(
        self,
        *,
        repository: AskFinalizationRepository,
        client: AskFinalizationClient,
        max_attempts: int,
    ) -> None:
        self.repository = repository
        self.client = client
        self.max_attempts = max_attempts

    async def run(self, ask_id: UUID) -> AskRequest:
        prepared = await self.repository.prepare(ask_id, max_attempts=self.max_attempts)
        if prepared.run is None:
            return prepared.request
        try:
            if prepared.finalization.finalization_kind == "direct_reuse":
                return await self.repository.persist_direct(prepared)
            input_snapshot = await self.repository.input_snapshot(prepared)
            await self.repository.store_input_hash(prepared.finalization.id, input_snapshot)
            response = await self.client.finalize_ask(input_snapshot)
            self.repository.validate_model_output(response.payload, input_snapshot)
            return await self.repository.persist_researched(
                prepared,
                original_input=input_snapshot,
                response=response,
            )
        except (AnalysisError, AskFinalizationError, SQLAlchemyError) as error:
            await self.repository.persist_failure(
                prepared,
                error_code=getattr(error, "error_code", "ASK_FINALIZATION_PERSISTENCE_FAILED"),
                retryable=getattr(
                    error, "retryable", isinstance(error, (AnalysisError, SQLAlchemyError))
                ),
            )
            raise
