from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid5

from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from infoscope.analysis.client import AnalysisError
from infoscope.analysis.personalization_schemas import (
    INPUT_SCHEMA_VERSION,
    MAX_CANONICAL_BYTES,
    MAX_EVENTS,
    OUTPUT_SCHEMA_VERSION,
    PersonalizationBaseAnalysis,
    PersonalizationDecision,
    PersonalizationEventInput,
    PersonalizationInput,
    PersonalizationPayload,
    PersonalizationProfile,
    PersonalizationResponse,
    canonical_bytes,
    canonical_hash,
)
from infoscope.models import (
    BaseAnalysis,
    Claim,
    Conflict,
    Event,
    PersonalizationArtifact,
    PersonalizationRun,
    PersonalizedEvent,
    PipelineRun,
    RawInformation,
    User,
)
from infoscope.schemas.onboarding import FocusId, InvestmentMarketId, ScopeId

PERSONALIZATION_NAMESPACE = UUID("493b027d-8306-4a7e-a636-93bbf6cad936")

SCOPE_TERMS: dict[ScopeId, tuple[str, ...]] = {
    ScopeId.AI: (
        "ai",
        "artificial intelligence",
        "machine learning",
        "llm",
        "neural",
        "model",
        "agent",
        "人工智能",
        "大模型",
        "机器学习",
        "神经网络",
        "智能体",
    ),
    ScopeId.OPEN_SOURCE: (
        "open source",
        "github",
        "gitlab",
        "repository",
        "maintainer",
        "license",
        "fork",
        "开源",
        "代码仓库",
        "维护者",
        "许可证",
    ),
    ScopeId.TECHNOLOGY: (
        "software",
        "hardware",
        "cloud",
        "chip",
        "semiconductor",
        "security",
        "database",
        "developer",
        "api",
        "软件",
        "硬件",
        "云计算",
        "芯片",
        "半导体",
        "安全",
        "数据库",
        "开发者",
    ),
    ScopeId.SCIENCE: (
        "research",
        "study",
        "paper",
        "experiment",
        "clinical",
        "physics",
        "chemistry",
        "biology",
        "space",
        "科学",
        "研究",
        "论文",
        "实验",
        "临床",
        "物理",
        "化学",
        "生物",
        "航天",
    ),
    ScopeId.INVESTMENT: (
        "market",
        "stock",
        "equity",
        "bond",
        "fund",
        "earnings",
        "valuation",
        "financing",
        "acquisition",
        "ipo",
        "市场",
        "股票",
        "证券",
        "债券",
        "基金",
        "财报",
        "估值",
        "融资",
        "收购",
        "上市",
    ),
}
MARKET_TERMS: dict[InvestmentMarketId, tuple[str, ...]] = {
    InvestmentMarketId.CHINA_MARKET: (
        "china",
        "chinese",
        "a-share",
        "sse",
        "szse",
        "hkex",
        "中国",
        "a股",
        "港股",
        "上交所",
        "深交所",
        "港交所",
    ),
    InvestmentMarketId.US_STOCK: (
        "united states",
        "u.s.",
        "nasdaq",
        "nyse",
        "sec",
        "wall street",
        "美国",
        "美股",
        "纳斯达克",
        "纽交所",
        "华尔街",
    ),
    InvestmentMarketId.CRYPTO_MARKET: (
        "crypto",
        "cryptocurrency",
        "bitcoin",
        "ethereum",
        "blockchain",
        "token",
        "defi",
        "加密",
        "比特币",
        "以太坊",
        "区块链",
        "代币",
    ),
}


class PersonalizationError(RuntimeError):
    def __init__(self, error_code: str, *, retryable: bool = False) -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.retryable = retryable


class PersonalizationClient(Protocol):
    async def personalize(self, value: PersonalizationInput) -> PersonalizationResponse: ...


def _normalized_text(event: PersonalizationEventInput) -> str:
    values = [
        event.title,
        event.overview,
        event.base_analysis.summary,
        event.base_analysis.event_type,
        *event.base_analysis.topics,
        *(item.name for item in event.base_analysis.entities),
        *(item.entity_type for item in event.base_analysis.entities),
    ]
    return " ".join(unicodedata.normalize("NFKC", value).casefold() for value in values)


def _matches(text: str, term: str) -> bool:
    normalized = unicodedata.normalize("NFKC", term).casefold()
    if any("\u4e00" <= char <= "\u9fff" for char in normalized):
        return normalized in text
    return re.search(rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])", text) is not None


def cheap_prefilter(profile: PersonalizationProfile, event: PersonalizationEventInput) -> bool:
    text = _normalized_text(event)
    selected = set(profile.scope_ids)
    if any(
        scope != ScopeId.INVESTMENT
        and scope in selected
        and any(_matches(text, term) for term in terms)
        for scope, terms in SCOPE_TERMS.items()
    ):
        return True
    if ScopeId.INVESTMENT not in selected or not any(
        _matches(text, term) for term in SCOPE_TERMS[ScopeId.INVESTMENT]
    ):
        return False
    marked = {
        market
        for market, terms in MARKET_TERMS.items()
        if any(_matches(text, term) for term in terms)
    }
    return not marked or bool(marked & set(profile.investment_market_ids))


class PersonalizationRepository:
    def __init__(
        self,
        database: AsyncSession,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.database = database
        self.clock = clock

    async def input_snapshot(self, user_id: UUID, *, lock: bool = False) -> PersonalizationInput:
        user_query = select(User).where(User.id == user_id)
        if lock:
            user_query = user_query.with_for_update()
        user = (await self.database.execute(user_query)).scalar_one_or_none()
        if user is None or not user.onboarding_completed:
            raise PersonalizationError("PERSONALIZATION_USER_NOT_READY")
        try:
            profile = PersonalizationProfile(
                scope_ids=[ScopeId(value) for value in user.scope_ids],
                investment_market_ids=[
                    InvestmentMarketId(value) for value in user.investment_market_ids
                ],
                focus_ids=[FocusId(value) for value in user.focus_ids],
            )
        except (ValueError, TypeError) as error:
            raise PersonalizationError("PERSONALIZATION_PROFILE_INVALID") from error
        query = (
            select(Event, BaseAnalysis)
            .join(BaseAnalysis, BaseAnalysis.event_id == Event.id)
            .order_by(Event.display_time.desc(), Event.id)
        )
        if lock:
            query = query.with_for_update(of=(Event, BaseAnalysis))
        rows = (await self.database.execute(query)).all()
        candidates: list[PersonalizationEventInput] = []
        for event, analysis in rows:
            try:
                item = PersonalizationEventInput(
                    event_id=event.id,
                    title=event.title,
                    overview=event.overview,
                    state=event.state,
                    display_time=event.display_time,
                    updated_at=event.updated_at,
                    base_analysis=PersonalizationBaseAnalysis(
                        base_analysis_id=analysis.id,
                        summary=analysis.summary,
                        event_type=analysis.event_type,
                        importance=analysis.importance,
                        topics=analysis.topics,
                        entities=analysis.entities,
                    ),
                )
            except (ValueError, TypeError) as error:
                raise PersonalizationError("PERSONALIZATION_INPUT_SCHEMA_INVALID") from error
            if cheap_prefilter(profile, item):
                candidates.append(item)
                if len(candidates) == MAX_EVENTS:
                    break
        value = PersonalizationInput(user_id=user.id, profile=profile, events=candidates)
        return value

    async def create_or_reuse(
        self, value: PersonalizationInput, *, max_attempts: int
    ) -> PersonalizationRun:
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        user = (
            await self.database.execute(
                select(User).where(User.id == value.user_id).with_for_update()
            )
        ).scalar_one_or_none()
        if user is None:
            raise PersonalizationError("PERSONALIZATION_USER_NOT_READY")
        input_hash = canonical_hash(value)
        prior = (
            await self.database.execute(
                select(PersonalizationRun).where(
                    PersonalizationRun.user_id == user.id,
                    PersonalizationRun.input_hash == input_hash,
                )
            )
        ).scalar_one_or_none()
        if prior is not None:
            await self.database.commit()
            return prior
        active = (
            await self.database.execute(
                select(PersonalizationRun).where(
                    PersonalizationRun.user_id == user.id,
                    PersonalizationRun.active_slot == 1,
                )
            )
        ).scalar_one_or_none()
        if active is not None:
            raise PersonalizationError("PERSONALIZATION_ALREADY_RUNNING", retryable=True)
        profile_hash = canonical_hash(value.profile)
        run = PersonalizationRun(
            user_id=user.id,
            idempotency_key=uuid5(PERSONALIZATION_NAMESPACE, f"{user.id}:{input_hash}"),
            schema_version=INPUT_SCHEMA_VERSION,
            input_hash=input_hash,
            profile_hash=profile_hash,
            captured_update_requested_at=user.personalization_update_requested_at,
            status="pending",
            active_slot=1,
            max_attempts=max_attempts,
        )
        self.database.add(run)
        await self.database.commit()
        return run

    async def start_attempt(self, run_id: UUID) -> PersonalizationRun:
        run = await self._locked_run(run_id)
        if run.status == "completed":
            return run
        if run.status == "running":
            raise PersonalizationError("PERSONALIZATION_ALREADY_RUNNING", retryable=True)
        if run.status == "failed" or run.attempt_count >= run.max_attempts:
            raise PersonalizationError("PERSONALIZATION_MAX_ATTEMPTS_REACHED")
        if run.status != "pending":
            raise PersonalizationError("PERSONALIZATION_RUN_STATE_INVALID")
        run.status = "running"
        run.attempt_count += 1
        run.started_at = run.started_at or self.clock()
        run.error_code = None
        await self.database.commit()
        return run

    async def persist_success(
        self,
        run_id: UUID,
        original: PersonalizationInput,
        response: PersonalizationResponse | None,
    ) -> PersonalizationRun:
        await self.database.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
        run = await self._locked_run(run_id)
        if run.status != "running":
            raise PersonalizationError("PERSONALIZATION_RUN_STATE_INVALID")
        current = await self.input_snapshot(run.user_id, lock=True)
        if canonical_hash(current) != run.input_hash or current != original:
            raise PersonalizationError("PERSONALIZATION_INPUT_CHANGED")
        payload = response.payload if response is not None else PersonalizationPayload(decisions=[])
        self.validate_output(payload, current)
        window_start, window_end, raw_count = await self.window_stats()
        artifact = PersonalizationArtifact(
            user_id=run.user_id,
            created_by_run_id=run.id,
            artifact_kind="model" if response is not None else "deterministic_empty",
            schema_version=OUTPUT_SCHEMA_VERSION,
            input_hash=run.input_hash,
            input_payload=current.model_dump(mode="json"),
            output_payload=payload.model_dump(mode="json"),
            provider=response.provider if response else None,
            model=response.model if response else None,
            token_usage=response.token_usage.model_dump(mode="json") if response else None,
            window_started_at=window_start,
            window_ended_at=window_end,
            raw_information_count=raw_count,
            event_count=len(current.events),
            relevant_event_count=sum(item.relevant for item in payload.decisions),
        )
        self.database.add(artifact)
        await self.database.flush()
        decisions = {item.event_id: item for item in payload.decisions}
        event_ids = [item.event_id for item in current.events]
        claim_counts = await self._event_counts(
            Claim.event_id,
            event_ids,
            Claim.state == "unresolved",
        )
        conflict_counts = await self._event_counts(Conflict.event_id, event_ids)
        self.database.add_all(
            [
                self._personalized_event(
                    artifact_id=artifact.id,
                    user_id=run.user_id,
                    position=position,
                    event=event,
                    decision=decisions[event.event_id],
                    new_claim_count=claim_counts.get(event.event_id, 0),
                    conflict_count=conflict_counts.get(event.event_id, 0),
                )
                for position, event in enumerate(current.events)
            ]
        )
        user = await self.database.get(User, run.user_id)
        if user is None:
            raise PersonalizationError("PERSONALIZATION_USER_NOT_READY")
        if user.personalization_update_requested_at == run.captured_update_requested_at:
            user.personalization_update_requested_at = None
        run.status = "completed"
        run.active_slot = None
        run.error_code = None
        run.finished_at = self.clock()
        await self.database.commit()
        return run

    async def persist_failure(
        self, run_id: UUID, error_code: str, *, retryable: bool
    ) -> PersonalizationRun:
        await self.database.rollback()
        run = await self._locked_run(run_id)
        if run.status != "running":
            raise PersonalizationError("PERSONALIZATION_RUN_STATE_INVALID")
        terminal = not retryable or run.attempt_count >= run.max_attempts
        run.status = "failed" if terminal else "pending"
        run.active_slot = None if terminal else 1
        run.error_code = error_code[:128]
        run.finished_at = self.clock() if terminal else None
        await self.database.commit()
        return run

    async def acknowledge_reused(self, run: PersonalizationRun) -> None:
        if run.status != "completed":
            return
        user = await self.database.get(User, run.user_id)
        if user is None:
            return
        current = await self.input_snapshot(run.user_id)
        if canonical_hash(current) == run.input_hash:
            user.personalization_update_requested_at = None
            await self.database.commit()

    async def window_stats(self) -> tuple[datetime, datetime, int]:
        window = (
            await self.database.execute(
                select(PipelineRun)
                .where(
                    PipelineRun.pipeline_name == "window_analysis",
                    PipelineRun.status == "succeeded",
                )
                .order_by(PipelineRun.window_end.desc(), PipelineRun.attempt.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if window is None:
            start = self.clock().replace(minute=0, second=0, microsecond=0)
            end = start + timedelta(hours=1)
        else:
            start, end = window.window_start, window.window_end
        count = (
            await self.database.execute(
                select(func.count(RawInformation.id)).where(
                    RawInformation.acquired_at >= start,
                    RawInformation.acquired_at < end,
                )
            )
        ).scalar_one()
        return start, end, count

    async def _event_counts(self, column, event_ids: list[UUID], *conditions) -> dict[UUID, int]:
        if not event_ids:
            return {}
        rows = (
            await self.database.execute(
                select(column, func.count())
                .where(column.in_(event_ids), *conditions)
                .group_by(column)
            )
        ).all()
        return dict(rows)

    async def latest_artifact(self, user_id: UUID) -> PersonalizationArtifact | None:
        return (
            await self.database.execute(
                select(PersonalizationArtifact)
                .join(
                    PersonalizationRun,
                    PersonalizationRun.id == PersonalizationArtifact.created_by_run_id,
                )
                .where(
                    PersonalizationArtifact.user_id == user_id,
                    PersonalizationRun.status == "completed",
                )
                .order_by(
                    PersonalizationArtifact.created_at.desc(), PersonalizationArtifact.id.desc()
                )
                .limit(1)
            )
        ).scalar_one_or_none()

    async def ordered_visible_event_ids(self, user_id: UUID) -> list[UUID]:
        artifact = await self.latest_artifact(user_id)
        if artifact is None:
            raise PersonalizationError("PERSONALIZATION_SNAPSHOT_UNAVAILABLE")
        return list(
            (
                await self.database.execute(
                    select(PersonalizedEvent.event_id)
                    .where(
                        PersonalizedEvent.artifact_id == artifact.id,
                        PersonalizedEvent.relevant.is_(True),
                    )
                    .order_by(
                        PersonalizedEvent.snapshot_display_time.desc(), PersonalizedEvent.event_id
                    )
                )
            ).scalars()
        )

    async def is_currently_visible(self, user_id: UUID, event_id: UUID) -> bool:
        artifact = await self.latest_artifact(user_id)
        if artifact is None:
            raise PersonalizationError("PERSONALIZATION_SNAPSHOT_UNAVAILABLE")
        return bool(
            await self.database.scalar(
                select(PersonalizedEvent.id).where(
                    PersonalizedEvent.artifact_id == artifact.id,
                    PersonalizedEvent.event_id == event_id,
                    PersonalizedEvent.relevant.is_(True),
                )
            )
        )

    async def was_ever_relevant(self, user_id: UUID, event_id: UUID) -> bool:
        result = await self.database.execute(
            select(PersonalizedEvent.id)
            .join(
                PersonalizationArtifact,
                PersonalizationArtifact.id == PersonalizedEvent.artifact_id,
            )
            .join(
                PersonalizationRun,
                PersonalizationRun.id == PersonalizationArtifact.created_by_run_id,
            )
            .where(
                PersonalizedEvent.user_id == user_id,
                PersonalizedEvent.event_id == event_id,
                PersonalizedEvent.relevant.is_(True),
                PersonalizationRun.status == "completed",
            )
            .limit(1)
        )
        return bool(list(result.scalars()))

    @staticmethod
    def validate_output(payload: PersonalizationPayload, value: PersonalizationInput) -> None:
        if [item.event_id for item in payload.decisions] != [
            item.event_id for item in value.events
        ]:
            raise PersonalizationError("PERSONALIZATION_SCHEMA_INVALID", retryable=True)
        scope_order = list(value.profile.scope_ids)
        focus_order = list(value.profile.focus_ids)
        for decision in payload.decisions:
            expected_scope = [item for item in scope_order if item in decision.matched_scope_ids]
            expected_focus = [item for item in focus_order if item in decision.matched_focus_ids]
            if (
                decision.matched_scope_ids != expected_scope
                or decision.matched_focus_ids != expected_focus
            ):
                raise PersonalizationError("PERSONALIZATION_SCHEMA_INVALID", retryable=True)

    @staticmethod
    def _personalized_event(
        *,
        artifact_id: UUID,
        user_id: UUID,
        position: int,
        event: PersonalizationEventInput,
        decision: PersonalizationDecision,
        new_claim_count: int,
        conflict_count: int,
    ) -> PersonalizedEvent:
        return PersonalizedEvent(
            artifact_id=artifact_id,
            user_id=user_id,
            event_id=event.event_id,
            source_base_analysis_id=event.base_analysis.base_analysis_id,
            snapshot_position=position,
            relevant=decision.relevant,
            priority=decision.priority,
            snapshot_title=event.title,
            snapshot_overview=event.overview,
            snapshot_state=event.state,
            snapshot_display_time=event.display_time,
            snapshot_event_updated_at=event.updated_at,
            snapshot_topics=event.base_analysis.topics,
            snapshot_new_claim_count=new_claim_count,
            snapshot_conflict_count=conflict_count,
            why_it_matters=decision.why_it_matters,
            personalized_angle=decision.personalized_angle,
            matched_scope_ids=[item.value for item in decision.matched_scope_ids],
            matched_focus_ids=[item.value for item in decision.matched_focus_ids],
        )

    async def _locked_run(self, run_id: UUID) -> PersonalizationRun:
        run = (
            await self.database.execute(
                select(PersonalizationRun).where(PersonalizationRun.id == run_id).with_for_update()
            )
        ).scalar_one_or_none()
        if run is None:
            raise PersonalizationError("PERSONALIZATION_RUN_NOT_FOUND")
        return run


class PersonalizationRunner:
    def __init__(
        self,
        repository: PersonalizationRepository,
        client: PersonalizationClient,
        *,
        max_attempts: int,
    ) -> None:
        self.repository = repository
        self.client = client
        self.max_attempts = max_attempts

    async def run_user(self, user_id: UUID) -> PersonalizationRun:
        value = await self.repository.input_snapshot(user_id)
        run = await self.repository.create_or_reuse(value, max_attempts=self.max_attempts)
        if run.status == "completed":
            await self.repository.acknowledge_reused(run)
            return run
        run = await self.repository.start_attempt(run.id)
        run_id = run.id
        try:
            if len(canonical_bytes(value)) > MAX_CANONICAL_BYTES:
                raise PersonalizationError("PERSONALIZATION_INPUT_LIMIT_EXCEEDED")
            response = None if not value.events else await self.client.personalize(value)
            return await self.repository.persist_success(run_id, value, response)
        except (AnalysisError, PersonalizationError, SQLAlchemyError) as error:
            retryable = getattr(
                error,
                "retryable",
                isinstance(error, (AnalysisError, SQLAlchemyError)),
            )
            return await self.repository.persist_failure(
                run_id,
                getattr(error, "error_code", "PERSONALIZATION_FAILED"),
                retryable=retryable,
            )


class PersonalizationVisibleEventSnapshotProvider:
    def __init__(self, database: AsyncSession) -> None:
        self.repository = PersonalizationRepository(database)

    async def ordered_event_ids(self, user_id: UUID) -> list[UUID]:
        return await self.repository.ordered_visible_event_ids(user_id)

    async def is_visible(self, user_id: UUID, event_id: UUID) -> bool:
        return await self.repository.is_currently_visible(user_id, event_id)
