from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from infoscope.analysis.ask_schemas import (
    AskBaseAnalysisInput,
    AskComparisonPayload,
    AskEventInput,
    AskEventReconciliationArtifactPayload,
    AskEventReconciliationAssignment,
    AskEventReconciliationInput,
    AskEventReconciliationPayload,
    AskEventReconciliationResponse,
    AskReconciliationMissingFact,
    AskReconciliationSignal,
    AskResearchArtifactPayload,
    ask_reconciliation_input_hash,
)
from infoscope.analysis.client import AnalysisError
from infoscope.models import (
    AskComparisonArtifact,
    AskEventReconciliation,
    AskEventReconciliationArtifact,
    AskEventReconciliationRun,
    AskRequest,
    AskResearchArtifact,
    BaseAnalysis,
    Claim,
    ClaimSignal,
    Conflict,
    ConflictClaim,
    ConflictSignal,
    Event,
    EventSignal,
    ResearchSource,
    Signal,
    TimelineClaim,
    TimelineEntry,
)
from infoscope.services.ask_comparison import AskComparisonError
from infoscope.services.research import ResearchError, ResearchRepository

TERMINAL_RECONCILIATION_ERRORS = {
    "ASK_RECONCILIATION_INPUT_CHANGED",
    "ASK_RECONCILIATION_NO_RELEVANT_SIGNALS",
    "ASK_RECONCILIATION_SOURCE_INVALID",
    "ASK_RECONCILIATION_PRIVATE_PROVENANCE_INVALID",
    "ASK_RECONCILIATION_OUTPUT_INVALID",
}


class AskEventReconciliationError(RuntimeError):
    def __init__(self, error_code: str, *, retryable: bool = False) -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.retryable = retryable


class AskEventReconciliationClient(Protocol):
    async def reconcile_ask_events(
        self, value: AskEventReconciliationInput
    ) -> AskEventReconciliationResponse: ...


@dataclass(frozen=True, slots=True)
class PreparedReconciliation:
    request: AskRequest
    reconciliation: AskEventReconciliation
    run: AskEventReconciliationRun | None
    source_artifact: AskResearchArtifact
    bridge_payload: AskResearchArtifactPayload
    comparison_payload: AskComparisonPayload


class AskEventReconciliationRepository:
    def __init__(self, database: AsyncSession) -> None:
        self.database = database

    async def prepare(self, ask_id: UUID, *, max_attempts: int) -> PreparedReconciliation:
        request = (
            await self.database.execute(
                select(AskRequest).where(AskRequest.id == ask_id).with_for_update()
            )
        ).scalar_one_or_none()
        if request is None:
            raise AskEventReconciliationError("ASK_REQUEST_NOT_FOUND")
        source = (
            await self.database.execute(
                select(AskResearchArtifact).where(AskResearchArtifact.ask_request_id == request.id)
            )
        ).scalar_one_or_none()
        if source is None:
            raise AskEventReconciliationError("ASK_RECONCILIATION_SOURCE_MISSING")
        bridge_payload, comparison_payload = await self._source_payloads(request, source)
        reconciliation = (
            await self.database.execute(
                select(AskEventReconciliation).where(
                    AskEventReconciliation.ask_request_id == request.id
                )
            )
        ).scalar_one_or_none()
        if reconciliation is not None and reconciliation.status in {"running", "completed"}:
            await self.database.commit()
            return PreparedReconciliation(
                request,
                reconciliation,
                None,
                source,
                bridge_payload,
                comparison_payload,
            )
        if request.status != "pending" or request.stage != "awaiting_reconciliation":
            raise AskEventReconciliationError("ASK_RECONCILIATION_NOT_RETRYABLE")
        started = datetime.now(UTC)
        if reconciliation is None:
            reconciliation = AskEventReconciliation(
                ask_request_id=request.id,
                source_bridge_artifact_id=source.id,
                status="running",
                attempt_count=1,
                max_attempts=max_attempts,
                started_at=started,
            )
            self.database.add(reconciliation)
            await self.database.flush()
        else:
            if reconciliation.source_bridge_artifact_id != source.id:
                raise AskEventReconciliationError("ASK_RECONCILIATION_SOURCE_INVALID")
            if reconciliation.attempt_count >= reconciliation.max_attempts:
                finished = datetime.now(UTC)
                reconciliation.error_code = "ASK_RECONCILIATION_ATTEMPTS_EXHAUSTED"
                reconciliation.finished_at = finished
                request.status = "failed"
                request.error_code = "ASK_RECONCILIATION_ATTEMPTS_EXHAUSTED"
                request.finished_at = finished
                await self.database.commit()
                raise AskEventReconciliationError("ASK_RECONCILIATION_ATTEMPTS_EXHAUSTED")
            reconciliation.status = "running"
            reconciliation.attempt_count += 1
            reconciliation.error_code = None
            reconciliation.started_at = started
            reconciliation.finished_at = None
        run = AskEventReconciliationRun(
            reconciliation_id=reconciliation.id,
            attempt=reconciliation.attempt_count,
            status="running",
            started_at=started,
        )
        self.database.add(run)
        request.status = "running"
        request.stage = "awaiting_reconciliation"
        request.error_code = None
        request.finished_at = None
        await self.database.commit()
        return PreparedReconciliation(
            request,
            reconciliation,
            run,
            source,
            bridge_payload,
            comparison_payload,
        )

    async def _source_payloads(
        self, request: AskRequest, source: AskResearchArtifact
    ) -> tuple[AskResearchArtifactPayload, AskComparisonPayload]:
        try:
            bridge_payload = AskResearchArtifactPayload.model_validate(source.payload)
        except ValueError as error:
            raise AskEventReconciliationError("ASK_RECONCILIATION_SOURCE_INVALID") from error
        comparison = await self.database.get(
            AskComparisonArtifact, bridge_payload.comparison_artifact_id
        )
        if comparison is None:
            raise AskEventReconciliationError("ASK_RECONCILIATION_SOURCE_INVALID")
        try:
            comparison_payload = AskComparisonPayload.model_validate(comparison.output)
        except ValueError as error:
            raise AskEventReconciliationError("ASK_RECONCILIATION_SOURCE_INVALID") from error
        if (
            source.schema_version != "ask_research_bridge.v1"
            or source.ask_request_id != request.id
            or bridge_payload.ask_id != request.id
            or bridge_payload.comparison_artifact_id != source.comparison_artifact_id
            or bridge_payload.research_request_id != source.research_request_id
            or comparison_payload.ask_id != request.id
            or comparison_payload.decision != "research_required"
            or not comparison_payload.missing_facts
        ):
            raise AskEventReconciliationError("ASK_RECONCILIATION_SOURCE_INVALID")
        missing_event_ids = {
            event_id for item in comparison_payload.missing_facts for event_id in item.event_ids
        }
        expected_source_event_ids = [
            event_id for event_id in comparison_payload.event_ids if event_id in missing_event_ids
        ]
        if bridge_payload.source_event_ids != expected_source_event_ids:
            raise AskEventReconciliationError("ASK_RECONCILIATION_SOURCE_INVALID")
        return bridge_payload, comparison_payload

    async def targeted_deduplicate(self, payload: AskResearchArtifactPayload) -> None:
        observation_ids = [
            signal_id for result in payload.results for signal_id in result.signal_ids
        ]
        if len(observation_ids) != len(set(observation_ids)):
            raise AskEventReconciliationError("ASK_RECONCILIATION_SOURCE_INVALID")
        signals = list(
            (
                await self.database.execute(
                    select(Signal)
                    .where(Signal.id.in_(observation_ids))
                    .order_by(Signal.id)
                    .with_for_update()
                )
            ).scalars()
        )
        signal_map = {item.id: item for item in signals}
        if set(signal_map) != set(observation_ids):
            raise AskEventReconciliationError("ASK_RECONCILIATION_SOURCE_INVALID")
        sources = list(
            (
                await self.database.execute(
                    select(ResearchSource).where(
                        ResearchSource.id.in_([item.research_source_id for item in payload.results])
                    )
                )
            ).scalars()
        )
        source_map = {item.id: item for item in sources}
        for result in payload.results:
            source = source_map.get(result.research_source_id)
            if (
                source is None
                or source.research_request_id != payload.research_request_id
                or source.candidate_index != result.candidate_index
                or source.status != "succeeded"
                or source.raw_information_id != result.raw_information_id
                or any(
                    signal_map[signal_id].raw_information_id != result.raw_information_id
                    for signal_id in result.signal_ids
                )
            ):
                raise AskEventReconciliationError("ASK_RECONCILIATION_SOURCE_INVALID")
        content_hashes = {item.content_hash for item in signals}
        candidates = list(
            (
                await self.database.execute(
                    select(Signal)
                    .where(Signal.content_hash.in_(content_hashes))
                    .order_by(Signal.created_at, Signal.id)
                    .with_for_update()
                )
            ).scalars()
        )
        canonical_by_hash: dict[str, Signal] = {}
        for candidate in candidates:
            if candidate.duplicate_of_signal_id is None:
                canonical_by_hash.setdefault(candidate.content_hash, candidate)
        if set(canonical_by_hash) != content_hashes:
            raise AskEventReconciliationError("ASK_RECONCILIATION_SOURCE_INVALID")
        for signal in signals:
            canonical = canonical_by_hash[signal.content_hash]
            signal.duplicate_of_signal_id = None if signal.id == canonical.id else canonical.id
        await self.database.commit()

    async def input_snapshot(
        self,
        prepared: PreparedReconciliation,
    ) -> AskEventReconciliationInput:
        payload = prepared.bridge_payload
        try:
            comparison_events = await self._current_events(
                event_ids=payload.source_event_ids,
            )
            signals = await self._canonical_signals(payload)
        except (AskComparisonError, ResearchError) as error:
            error_code = getattr(error, "error_code", "ASK_RECONCILIATION_SOURCE_INVALID")
            if "PRIVATE_PROVENANCE" in error_code:
                raise AskEventReconciliationError(
                    "ASK_RECONCILIATION_PRIVATE_PROVENANCE_INVALID"
                ) from error
            raise AskEventReconciliationError("ASK_RECONCILIATION_SOURCE_INVALID") from error
        return AskEventReconciliationInput(
            ask_id=prepared.request.id,
            source_bridge_artifact_id=prepared.source_artifact.id,
            source_bridge_payload=payload,
            question=prepared.request.question,
            missing_facts=[
                AskReconciliationMissingFact(
                    event_ids=item.event_ids,
                    question=item.question,
                )
                for item in prepared.comparison_payload.missing_facts
            ],
            source_event_ids=payload.source_event_ids,
            events=comparison_events,
            canonical_signals=signals,
        )

    async def _current_events(self, *, event_ids: list[UUID]) -> list[AskEventInput]:
        snapshot = await ResearchRepository(self.database).fact_snapshot(set(event_ids))
        events = {item.event_id: item for item in snapshot.events}
        analyses = list(
            (
                await self.database.execute(
                    select(BaseAnalysis)
                    .where(BaseAnalysis.event_id.in_(event_ids))
                    .order_by(BaseAnalysis.event_id)
                )
            ).scalars()
        )
        analysis_map = {item.event_id: item for item in analyses}
        if set(events) != set(event_ids) or set(analysis_map) != set(event_ids):
            raise AskEventReconciliationError("ASK_RECONCILIATION_SOURCE_INVALID")
        return [
            AskEventInput(
                **events[event_id].model_dump(),
                base_analysis=AskBaseAnalysisInput(
                    base_analysis_id=analysis_map[event_id].id,
                    summary=analysis_map[event_id].summary,
                    event_type=analysis_map[event_id].event_type,
                    importance=analysis_map[event_id].importance,
                    topics=analysis_map[event_id].topics,
                    entities=analysis_map[event_id].entities,
                ),
            )
            for event_id in event_ids
        ]

    async def _canonical_signals(
        self, payload: AskResearchArtifactPayload
    ) -> list[AskReconciliationSignal]:
        observation_ids = [
            signal_id for result in payload.results for signal_id in result.signal_ids
        ]
        observations = list(
            (
                await self.database.execute(select(Signal).where(Signal.id.in_(observation_ids)))
            ).scalars()
        )
        observation_map = {item.id: item for item in observations}
        if set(observation_map) != set(observation_ids):
            raise AskEventReconciliationError("ASK_RECONCILIATION_SOURCE_INVALID")
        canonical_ids = {item.duplicate_of_signal_id or item.id for item in observations}
        canonical_rows = list(
            (
                await self.database.execute(select(Signal).where(Signal.id.in_(canonical_ids)))
            ).scalars()
        )
        canonical_map = {item.id: item for item in canonical_rows}
        if set(canonical_map) != canonical_ids:
            raise AskEventReconciliationError("ASK_RECONCILIATION_SOURCE_INVALID")
        grouped: dict[UUID, list[UUID]] = {}
        order: list[UUID] = []
        for observation_id in observation_ids:
            observation = observation_map[observation_id]
            canonical_id = observation.duplicate_of_signal_id or observation.id
            canonical = canonical_map[canonical_id]
            if canonical.duplicate_of_signal_id is not None or (
                canonical.content_hash != observation.content_hash
            ):
                raise AskEventReconciliationError("ASK_RECONCILIATION_SOURCE_INVALID")
            if canonical_id not in grouped:
                order.append(canonical_id)
                grouped[canonical_id] = []
            grouped[canonical_id].append(observation_id)
        values: list[AskReconciliationSignal] = []
        for canonical_id in order:
            signal = canonical_map[canonical_id]
            evidence = ResearchRepository._evidence(signal)
            values.append(
                AskReconciliationSignal(
                    canonical_signal_id=canonical_id,
                    observation_signal_ids=grouped[canonical_id],
                    title=signal.title,
                    sanitized_text=evidence.sanitized_text,
                    published_at=evidence.published_at,
                    evidence_visibility=evidence.evidence_visibility,
                    public_safe_provenance=evidence.public_safe_provenance,
                )
            )
        return values

    async def store_input_hash(
        self, reconciliation_id: UUID, value: AskEventReconciliationInput
    ) -> str:
        input_hash = ask_reconciliation_input_hash(value)
        reconciliation = await self.database.get(AskEventReconciliation, reconciliation_id)
        if reconciliation is None:
            raise AskEventReconciliationError("ASK_RECONCILIATION_STATE_MISSING")
        if reconciliation.input_hash is None:
            reconciliation.input_hash = input_hash
            await self.database.commit()
        elif reconciliation.input_hash != input_hash:
            raise AskEventReconciliationError("ASK_RECONCILIATION_INPUT_CHANGED")
        return input_hash

    async def persist_success(
        self,
        prepared: PreparedReconciliation,
        *,
        original_input: AskEventReconciliationInput,
        response: AskEventReconciliationResponse,
    ) -> AskRequest:
        await self.database.rollback()
        request = (
            await self.database.execute(
                select(AskRequest)
                .where(AskRequest.id == prepared.request.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        source = (
            await self.database.execute(
                select(AskResearchArtifact)
                .where(AskResearchArtifact.id == prepared.source_artifact.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        reconciliation = (
            await self.database.execute(
                select(AskEventReconciliation)
                .where(AskEventReconciliation.id == prepared.reconciliation.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        run = (
            await self.database.execute(
                select(AskEventReconciliationRun)
                .where(AskEventReconciliationRun.id == prepared.run.id)  # type: ignore[union-attr]
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        comparison = (
            await self.database.execute(
                select(AskComparisonArtifact)
                .where(AskComparisonArtifact.id == source.comparison_artifact_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        if comparison.ask_request_id != request.id:
            raise AskEventReconciliationError("ASK_RECONCILIATION_INPUT_CHANGED")
        await self._lock_current_facts(original_input)
        try:
            bridge_payload, comparison_payload = await self._source_payloads(request, source)
            locked_prepared = PreparedReconciliation(
                request,
                reconciliation,
                run,
                source,
                bridge_payload,
                comparison_payload,
            )
            current_input = await self.input_snapshot(locked_prepared)
        except AskEventReconciliationError as error:
            raise AskEventReconciliationError("ASK_RECONCILIATION_INPUT_CHANGED") from error
        current_hash = ask_reconciliation_input_hash(current_input)
        if current_hash != reconciliation.input_hash:
            raise AskEventReconciliationError("ASK_RECONCILIATION_INPUT_CHANGED")
        self.validate_output(response.payload, current_input)
        event_map = {
            item.id: item
            for item in (
                await self.database.execute(
                    select(Event).where(Event.id.in_(current_input.source_event_ids))
                )
            ).scalars()
        }
        existing_links = set(
            (
                await self.database.execute(
                    select(EventSignal.event_id, EventSignal.signal_id).where(
                        EventSignal.event_id.in_(current_input.source_event_ids)
                    )
                )
            ).all()
        )
        assignments: list[AskEventReconciliationAssignment] = []
        update_map = {item.event_id: item for item in response.payload.event_updates}
        for event_id in current_input.source_event_ids:
            update = update_map.get(event_id)
            if update is None:
                continue
            event = event_map[event_id]
            event.title = update.title
            event.overview = update.overview
            event.display_time = update.display_time
            newly_attached = [
                signal_id
                for signal_id in update.signal_ids
                if (event_id, signal_id) not in existing_links
            ]
            if newly_attached:
                await self.database.execute(
                    insert(EventSignal)
                    .values(
                        [
                            {
                                "event_id": event_id,
                                "signal_id": signal_id,
                                "attached_by_pipeline_run_id": None,
                                "attached_by_ask_reconciliation_run_id": run.id,
                            }
                            for signal_id in newly_attached
                        ]
                    )
                    .on_conflict_do_nothing(
                        index_elements=[EventSignal.event_id, EventSignal.signal_id]
                    )
                )
            assignments.append(
                AskEventReconciliationAssignment(
                    event_id=event_id,
                    signal_ids=update.signal_ids,
                    newly_attached_signal_ids=newly_attached,
                )
            )
        updated_event_ids = [item.event_id for item in assignments]
        artifact_payload = AskEventReconciliationArtifactPayload(
            ask_id=request.id,
            source_bridge_artifact_id=source.id,
            output=response.payload,
            assignments=assignments,
            updated_event_ids=updated_event_ids,
        )
        self.database.add(
            AskEventReconciliationArtifact(
                reconciliation_id=reconciliation.id,
                created_by_run_id=run.id,
                ask_request_id=request.id,
                source_bridge_artifact_id=source.id,
                schema_version="ask_event_reconciliation.v1",
                input_hash=current_hash,
                payload=artifact_payload.model_dump(mode="json"),
                provider=response.provider,
                model=response.model,
                token_usage=response.token_usage.model_dump(mode="json"),
            )
        )
        finished = datetime.now(UTC)
        run.status = "completed"
        run.error_code = None
        run.finished_at = finished
        reconciliation.status = "completed"
        reconciliation.error_code = None
        reconciliation.finished_at = finished
        request.status = "pending"
        request.stage = "finalizing"
        request.error_code = None
        request.finished_at = None
        await self.database.commit()
        return request

    async def _lock_current_facts(self, value: AskEventReconciliationInput) -> None:
        event_ids = sorted(value.source_event_ids)
        await self._lock(Event, Event.id.in_(event_ids), Event.id)
        current_event_signal_ids = list(
            (
                await self.database.execute(
                    select(EventSignal.signal_id).where(EventSignal.event_id.in_(event_ids))
                )
            ).scalars()
        )
        observation_ids = {
            signal_id
            for item in value.canonical_signals
            for signal_id in item.observation_signal_ids
        }
        observation_rows = list(
            (
                await self.database.execute(
                    select(Signal).where(Signal.id.in_(sorted(observation_ids)))
                )
            ).scalars()
        )
        signal_ids = sorted(
            {
                signal_id
                for item in value.canonical_signals
                for signal_id in [item.canonical_signal_id, *item.observation_signal_ids]
            }
            | set(current_event_signal_ids)
            | {
                item.duplicate_of_signal_id
                for item in observation_rows
                if item.duplicate_of_signal_id is not None
            }
        )
        locked_signals = await self._lock(Signal, Signal.id.in_(signal_ids), Signal.id)
        locked_signal_map = {item.id: item for item in locked_signals}
        additional_canonical_ids = sorted(
            {
                locked_signal_map[item].duplicate_of_signal_id
                for item in observation_ids
                if item in locked_signal_map
                and locked_signal_map[item].duplicate_of_signal_id is not None
                and locked_signal_map[item].duplicate_of_signal_id not in locked_signal_map
            }
        )
        if additional_canonical_ids:
            await self._lock(
                Signal,
                Signal.id.in_(additional_canonical_ids),
                Signal.id,
            )
        await self._lock(EventSignal, EventSignal.event_id.in_(event_ids), EventSignal.id)
        claims = await self._lock(Claim, Claim.event_id.in_(event_ids), Claim.id)
        claim_ids = [item.id for item in claims]
        await self._lock(ClaimSignal, ClaimSignal.claim_id.in_(claim_ids), ClaimSignal.id)
        timeline = await self._lock(
            TimelineEntry, TimelineEntry.event_id.in_(event_ids), TimelineEntry.id
        )
        await self._lock(
            TimelineClaim,
            TimelineClaim.timeline_entry_id.in_([item.id for item in timeline]),
            TimelineClaim.id,
        )
        conflicts = await self._lock(Conflict, Conflict.event_id.in_(event_ids), Conflict.id)
        conflict_ids = [item.id for item in conflicts]
        await self._lock(
            ConflictClaim, ConflictClaim.conflict_id.in_(conflict_ids), ConflictClaim.id
        )
        await self._lock(
            ConflictSignal, ConflictSignal.conflict_id.in_(conflict_ids), ConflictSignal.id
        )
        await self._lock(BaseAnalysis, BaseAnalysis.event_id.in_(event_ids), BaseAnalysis.id)

    async def _lock(self, model, predicate, order_column):
        return list(
            (
                await self.database.execute(
                    select(model)
                    .where(predicate)
                    .order_by(order_column)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).scalars()
        )

    async def persist_failure(
        self,
        prepared: PreparedReconciliation,
        *,
        error_code: str,
        retryable: bool,
    ) -> AskRequest:
        await self.database.rollback()
        request = await self.database.get(AskRequest, prepared.request.id)
        reconciliation = await self.database.get(AskEventReconciliation, prepared.reconciliation.id)
        run = (
            await self.database.get(AskEventReconciliationRun, prepared.run.id)
            if prepared.run is not None
            else None
        )
        if request is None or reconciliation is None or run is None:
            raise AskEventReconciliationError("ASK_RECONCILIATION_STATE_MISSING")
        terminal = (
            not retryable
            or error_code in TERMINAL_RECONCILIATION_ERRORS
            or reconciliation.attempt_count >= reconciliation.max_attempts
        )
        if retryable and reconciliation.attempt_count >= reconciliation.max_attempts:
            error_code = "ASK_RECONCILIATION_ATTEMPTS_EXHAUSTED"
        finished = datetime.now(UTC)
        run.status = "failed"
        run.error_code = error_code
        run.finished_at = finished
        reconciliation.status = "failed"
        reconciliation.error_code = error_code
        reconciliation.finished_at = finished
        request.status = "failed" if terminal else "pending"
        request.stage = "awaiting_reconciliation"
        request.error_code = error_code if terminal else None
        request.finished_at = finished if terminal else None
        await self.database.commit()
        return request

    @staticmethod
    def validate_output(
        payload: AskEventReconciliationPayload,
        value: AskEventReconciliationInput,
    ) -> None:
        if payload.ask_id != value.ask_id:
            raise AskEventReconciliationError("ASK_RECONCILIATION_OUTPUT_INVALID")
        selected = set(value.source_event_ids)
        canonical = {item.canonical_signal_id for item in value.canonical_signals}
        assigned = {signal_id for item in payload.event_updates for signal_id in item.signal_ids}
        unassigned = set(payload.unassigned_signal_ids)
        if (
            not payload.event_updates
            or any(item.event_id not in selected for item in payload.event_updates)
            or any(not set(item.signal_ids) <= canonical for item in payload.event_updates)
            or assigned | unassigned != canonical
            or assigned & unassigned
        ):
            error_code = (
                "ASK_RECONCILIATION_NO_RELEVANT_SIGNALS"
                if not payload.event_updates and unassigned == canonical
                else "ASK_RECONCILIATION_OUTPUT_INVALID"
            )
            raise AskEventReconciliationError(error_code)


class AskEventReconciliationRunner:
    def __init__(
        self,
        *,
        repository: AskEventReconciliationRepository,
        client: AskEventReconciliationClient,
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
            await self.repository.targeted_deduplicate(prepared.bridge_payload)
            input_snapshot = await self.repository.input_snapshot(prepared)
            await self.repository.store_input_hash(prepared.reconciliation.id, input_snapshot)
            response = await self.client.reconcile_ask_events(input_snapshot)
            self.repository.validate_output(response.payload, input_snapshot)
            return await self.repository.persist_success(
                prepared,
                original_input=input_snapshot,
                response=response,
            )
        except (AnalysisError, AskEventReconciliationError, SQLAlchemyError) as error:
            error_code = getattr(error, "error_code", "ASK_RECONCILIATION_PERSISTENCE_FAILED")
            retryable = getattr(
                error,
                "retryable",
                isinstance(error, (AnalysisError, SQLAlchemyError)),
            )
            await self.repository.persist_failure(
                prepared,
                error_code=error_code,
                retryable=retryable,
            )
            raise
