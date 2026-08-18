from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from infoscope.analysis.ask_schemas import (
    AskBaseAnalysisInput,
    AskComparisonInput,
    AskComparisonPayload,
    AskComparisonResponse,
    AskEventInput,
    AskRequestSpec,
    ask_input_hash,
)
from infoscope.analysis.client import AnalysisError
from infoscope.integrations.research.client import ResearchRuntimeError
from infoscope.models import (
    AskComparisonArtifact,
    AskRequest,
    AskRequestEvent,
    AskRun,
    BaseAnalysis,
    User,
)
from infoscope.services.claims_timeline import IntelligenceError
from infoscope.services.research import ResearchError, ResearchRepository


class AskComparisonError(RuntimeError):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


class AskComparisonClient(Protocol):
    async def compare_ask(self, value: AskComparisonInput) -> AskComparisonResponse: ...


class AskComparisonRepository:
    def __init__(self, database: AsyncSession) -> None:
        self.database = database

    async def input_snapshot(
        self,
        *,
        ask_id: UUID,
        question: str,
        selected_event_ids: list[UUID],
        grok_enabled: bool = False,
    ) -> AskComparisonInput:
        try:
            snapshot = await ResearchRepository(self.database).fact_snapshot(
                set(selected_event_ids)
            )
        except (ResearchError, IntelligenceError) as error:
            error_map = {
                "BASE_ANALYSIS_EVENT_MISSING": "ASK_EVENT_NOT_FOUND",
                "RESEARCH_PRIVATE_PROVENANCE_INVALID": "ASK_PRIVATE_PROVENANCE_INVALID",
                "INTELLIGENCE_PRIVATE_PROVENANCE_INVALID": "ASK_PRIVATE_PROVENANCE_INVALID",
            }
            raise AskComparisonError(
                error_map.get(error.error_code, "ASK_EVENT_FACTS_INVALID")
            ) from error
        events_by_id = {item.event_id: item for item in snapshot.events}
        if set(events_by_id) != set(selected_event_ids):
            raise AskComparisonError("ASK_EVENT_NOT_FOUND")
        analyses = list(
            (
                await self.database.execute(
                    select(BaseAnalysis)
                    .where(BaseAnalysis.event_id.in_(selected_event_ids))
                    .order_by(BaseAnalysis.event_id)
                )
            ).scalars()
        )
        analysis_by_event = {item.event_id: item for item in analyses}
        if set(analysis_by_event) != set(selected_event_ids):
            raise AskComparisonError("ASK_EVENT_BASE_ANALYSIS_MISSING")
        return AskComparisonInput(
            ask_id=ask_id,
            question=question,
            selected_event_ids=selected_event_ids,
            grok_enabled=grok_enabled,
            events=[
                AskEventInput(
                    **events_by_id[event_id].model_dump(),
                    base_analysis=AskBaseAnalysisInput(
                        base_analysis_id=analysis_by_event[event_id].id,
                        summary=analysis_by_event[event_id].summary,
                        event_type=analysis_by_event[event_id].event_type,
                        importance=analysis_by_event[event_id].importance,
                        topics=analysis_by_event[event_id].topics,
                        entities=analysis_by_event[event_id].entities,
                    ),
                )
                for event_id in selected_event_ids
            ],
        )

    async def create_request(
        self,
        spec: AskRequestSpec,
        *,
        ask_id: UUID,
        input_hash: str,
        max_attempts: int,
    ) -> AskRequest:
        if await self.database.get(User, spec.user_id) is None:
            raise AskComparisonError("ASK_USER_NOT_FOUND")
        request = AskRequest(
            id=ask_id,
            user_id=spec.user_id,
            question=spec.question,
            status="pending",
            grok_enabled=spec.grok_enabled,
            stage="comparing",
            input_hash=input_hash,
            max_attempts=max_attempts,
        )
        self.database.add(request)
        for position, event_id in enumerate(spec.selected_event_ids):
            self.database.add(
                AskRequestEvent(
                    ask_request_id=ask_id,
                    event_id=event_id,
                    position=position,
                )
            )
        await self.database.commit()
        return request

    async def selected_event_ids(self, ask_id: UUID) -> list[UUID]:
        return list(
            (
                await self.database.execute(
                    select(AskRequestEvent.event_id)
                    .where(AskRequestEvent.ask_request_id == ask_id)
                    .order_by(AskRequestEvent.position)
                )
            ).scalars()
        )

    async def prepare_run(self, ask_id: UUID) -> tuple[AskRequest, AskRun | None]:
        request = (
            await self.database.execute(
                select(AskRequest).where(AskRequest.id == ask_id).with_for_update()
            )
        ).scalar_one_or_none()
        if request is None:
            raise AskComparisonError("ASK_REQUEST_NOT_FOUND")
        if request.status == "completed" or (
            request.status == "pending" and request.stage == "awaiting_research"
        ):
            await self.database.commit()
            return request, None
        if request.status == "running":
            await self.database.commit()
            return request, None
        if request.status not in {"pending", "failed"} or request.stage != "comparing":
            raise AskComparisonError("ASK_REQUEST_NOT_RETRYABLE")
        if request.status == "failed" and request.attempt_count >= request.max_attempts:
            raise AskComparisonError("ASK_ATTEMPTS_EXHAUSTED")
        request.attempt_count += 1
        request.status = "running"
        request.error_code = None
        request.started_at = datetime.now(UTC)
        request.finished_at = None
        run = AskRun(
            ask_request_id=request.id,
            attempt=request.attempt_count,
            status="running",
            started_at=request.started_at,
        )
        self.database.add(run)
        await self.database.commit()
        return request, run

    async def persist_success(
        self,
        *,
        request_id: UUID,
        run_id: UUID,
        input_snapshot: AskComparisonInput,
        response: AskComparisonResponse,
        research_available: bool = True,
    ) -> AskRequest:
        request = await self.database.get(AskRequest, request_id)
        run = await self.database.get(AskRun, run_id)
        if request is None or run is None:
            raise AskComparisonError("ASK_RUN_STATE_MISSING")
        artifact = AskComparisonArtifact(
            ask_request_id=request.id,
            created_by_run_id=run.id,
            schema_version="ask_database_comparison.v1",
            input_hash=request.input_hash,
            input_snapshot=input_snapshot.model_dump(mode="json"),
            output=response.payload.model_dump(mode="json"),
            provider=response.provider,
            model=response.model,
            token_usage=response.token_usage.model_dump(mode="json"),
        )
        self.database.add(artifact)
        finished = datetime.now(UTC)
        run.status = "completed"
        run.finished_at = finished
        run.error_code = None
        request.error_code = None
        if response.payload.decision == "research_required":
            request.status = "pending" if research_available else "failed"
            request.stage = "awaiting_research"
            request.error_code = (
                None if research_available else "ASK_RESEARCH_CAPABILITY_UNAVAILABLE"
            )
            request.finished_at = None if research_available else finished
        else:
            request.status = "pending"
            request.stage = "finalizing"
            request.finished_at = None
        await self.database.commit()
        return request

    async def persist_failure(self, request_id: UUID, run_id: UUID, error_code: str) -> None:
        await self.database.rollback()
        request = await self.database.get(AskRequest, request_id)
        run = await self.database.get(AskRun, run_id)
        if request is None or run is None:
            raise AskComparisonError("ASK_RUN_STATE_MISSING")
        finished = datetime.now(UTC)
        request.status = "failed"
        request.stage = "comparing"
        request.error_code = error_code
        request.finished_at = finished
        run.status = "failed"
        run.error_code = error_code
        run.finished_at = finished
        await self.database.commit()


class AskComparisonRunner:
    def __init__(
        self,
        *,
        repository: AskComparisonRepository,
        client: AskComparisonClient,
        max_attempts: int,
        research_capability_check: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.repository = repository
        self.client = client
        self.max_attempts = max_attempts
        self.research_capability_check = research_capability_check

    async def create_and_run(self, spec: AskRequestSpec) -> AskRequest:
        ask_id = uuid4()
        input_snapshot = await self.repository.input_snapshot(
            ask_id=ask_id,
            question=spec.question,
            selected_event_ids=spec.selected_event_ids,
            grok_enabled=spec.grok_enabled,
        )
        request = await self.repository.create_request(
            spec,
            ask_id=ask_id,
            input_hash=ask_input_hash(input_snapshot),
            max_attempts=self.max_attempts,
        )
        return await self.run(request.id, input_snapshot=input_snapshot)

    async def run(
        self,
        ask_id: UUID,
        *,
        input_snapshot: AskComparisonInput | None = None,
    ) -> AskRequest:
        request, run = await self.repository.prepare_run(ask_id)
        if run is None:
            return request
        try:
            if input_snapshot is None:
                selected_event_ids = await self.repository.selected_event_ids(request.id)
                input_snapshot = await self.repository.input_snapshot(
                    ask_id=request.id,
                    question=request.question,
                    selected_event_ids=selected_event_ids,
                    grok_enabled=request.grok_enabled,
                )
            if ask_input_hash(input_snapshot) != request.input_hash:
                raise AskComparisonError("ASK_INPUT_CHANGED")
            response = await self.client.compare_ask(input_snapshot)
            self._validate_output(response.payload, input_snapshot)
            research_available = True
            if (
                response.payload.decision == "research_required"
                and self.research_capability_check is not None
            ):
                try:
                    await self.research_capability_check()
                except ResearchRuntimeError:
                    research_available = False
            return await self.repository.persist_success(
                request_id=request.id,
                run_id=run.id,
                input_snapshot=input_snapshot,
                response=response,
                research_available=research_available,
            )
        except (AnalysisError, AskComparisonError, SQLAlchemyError) as error:
            error_code = getattr(error, "error_code", "ASK_PERSISTENCE_FAILED")
            await self.repository.persist_failure(request.id, run.id, error_code)
            raise

    @staticmethod
    def _validate_output(
        payload: AskComparisonPayload,
        input_snapshot: AskComparisonInput,
    ) -> None:
        if payload.ask_id != input_snapshot.ask_id:
            raise AskComparisonError("ASK_OUTPUT_REQUEST_MISMATCH")
        if payload.event_ids != input_snapshot.selected_event_ids:
            raise AskComparisonError("ASK_OUTPUT_EVENT_ORDER_INVALID")
        claim_events = {
            claim.claim_id: event.event_id
            for event in input_snapshot.events
            for claim in event.claims
        }
        timeline_events = {
            item.timeline_entry_id: event.event_id
            for event in input_snapshot.events
            for item in event.timeline
        }
        conflict_events = {
            item.conflict_id: event.event_id
            for event in input_snapshot.events
            for item in event.conflicts
        }
        evidence_events = {
            item.signal_id: event.event_id
            for event in input_snapshot.events
            for item in event.evidence_signals
        }
        selected = set(input_snapshot.selected_event_ids)
        references = (
            (payload.claim_ids, claim_events),
            (payload.timeline_entry_ids, timeline_events),
            (payload.conflict_ids, conflict_events),
            (payload.evidence_signal_ids, evidence_events),
        )
        if any(
            any(mapping.get(item) not in selected for item in ids) for ids, mapping in references
        ):
            raise AskComparisonError("ASK_OUTPUT_REFERENCE_INVALID")
        for missing in payload.missing_facts:
            if (
                not set(missing.event_ids) <= selected
                or [
                    item
                    for item in input_snapshot.selected_event_ids
                    if item in set(missing.event_ids)
                ]
                != missing.event_ids
            ):
                raise AskComparisonError("ASK_OUTPUT_MISSING_FACT_EVENT_INVALID")
