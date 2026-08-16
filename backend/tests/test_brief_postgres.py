from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete

from infoscope.analysis.brief_schemas import BriefDecision, BriefPayload, BriefResponse
from infoscope.analysis.schemas import TokenUsage
from infoscope.db import session_factory
from infoscope.models import (
    BaseAnalysis,
    BriefArtifact,
    BriefItem,
    BriefRun,
    Event,
    PersonalizationArtifact,
    PersonalizationRun,
    PersonalizedEvent,
    PipelineArtifact,
    PipelineRun,
    User,
)
from infoscope.services.brief import BriefRepository, BriefRunner

pytestmark = pytest.mark.skipif(
    os.environ.get("INFOSCOPE_POSTGRES_INTEGRATION") != "1",
    reason="requires the local PostgreSQL integration database",
)


@pytest.mark.asyncio
async def test_brief_selection_persistence_and_latest_source_fail_closed() -> None:
    user_id = uuid4()
    pipeline_run_id = uuid4()
    source_artifact_id = uuid4()
    base_artifact_id = uuid4()
    now = datetime.now(UTC)
    event_ids: list = []

    class Model:
        async def generate_brief(self, value):
            return BriefResponse(
                payload=BriefPayload(
                    items=[
                        BriefDecision(
                            event_id=item.event_id,
                            summary=f"Brief {index}",
                            rationale="Grounded compression.",
                        )
                        for index, item in enumerate(value.events)
                    ]
                ),
                provider="integration",
                model="fake-brief-v1",
                token_usage=TokenUsage(
                    prompt_tokens=1,
                    completion_tokens=1,
                    total_tokens=2,
                ),
            )

    try:
        async with session_factory() as database:
            user = User(
                id=user_id,
                username=f"brief-{user_id}",
                username_normalized=f"brief-{user_id}",
                password_hash="unused",
                onboarding_completed=True,
                scope_ids=["ai"],
                investment_market_ids=[],
                focus_ids=["deep_context"],
            )
            pipeline_run = PipelineRun(
                id=pipeline_run_id,
                pipeline_name=f"brief-integration-{user_id}",
                status="succeeded",
                window_start=now.replace(minute=0, second=0, microsecond=0),
                window_end=now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1),
                attempt=1,
                started_at=now,
                finished_at=now,
            )
            source_artifact = PipelineArtifact(
                id=source_artifact_id,
                pipeline_run_id=pipeline_run.id,
                artifact_type="brief_test_source",
                schema_version="brief_test_source.v1",
                input_hash="1" * 64,
                payload={},
                provider="test",
                model="test",
                token_usage={},
            )
            base_artifact = PipelineArtifact(
                id=base_artifact_id,
                pipeline_run_id=pipeline_run.id,
                source_artifact_id=source_artifact.id,
                artifact_type="base_analysis",
                schema_version="base_analysis.v1",
                input_hash="2" * 64,
                payload={},
                provider="test",
                model="test",
                token_usage={},
            )
            database.add_all([user, pipeline_run])
            await database.flush()
            database.add(source_artifact)
            await database.flush()
            database.add(base_artifact)
            await database.flush()
            events: list[Event] = []
            analyses: list[BaseAnalysis] = []
            for index in range(9):
                event = Event(
                    id=uuid4(),
                    title=f"Current title {index}",
                    overview=f"Overview {index}",
                    state="developing",
                    display_time=now - timedelta(hours=index),
                )
                events.append(event)
                event_ids.append(event.id)
                analyses.append(
                    BaseAnalysis(
                        event_id=event.id,
                        source_artifact_id=base_artifact.id,
                        summary=f"Analysis {index}",
                        event_type="technology.release",
                        importance="high",
                        topics=["AI"],
                        entities=[{"name": "Example", "entity_type": "company"}],
                    )
                )
            database.add_all([*events, *analyses])
            await database.flush()
            personalization_run = PersonalizationRun(
                user_id=user.id,
                idempotency_key=uuid4(),
                schema_version="personalization_input.v1",
                input_hash="3" * 64,
                profile_hash="4" * 64,
                status="pending",
                active_slot=1,
                attempt_count=1,
                max_attempts=3,
                finished_at=now,
            )
            database.add(personalization_run)
            await database.flush()
            personalization_run.status = "completed"
            personalization_run.active_slot = None
            await database.flush()
            personalization = PersonalizationArtifact(
                user_id=user.id,
                created_by_run_id=personalization_run.id,
                artifact_kind="model",
                schema_version="personalization.v1",
                input_hash=personalization_run.input_hash,
                input_payload={},
                output_payload={},
                provider="test",
                model="test",
                token_usage={},
                window_started_at=now - timedelta(hours=1),
                window_ended_at=now,
                raw_information_count=9,
                event_count=9,
                relevant_event_count=9,
                created_at=now,
            )
            database.add(personalization)
            await database.flush()
            priorities = [
                "low",
                "critical",
                "normal",
                "high",
                "critical",
                "high",
                "normal",
                "low",
                "critical",
            ]
            database.add_all(
                [
                    PersonalizedEvent(
                        artifact_id=personalization.id,
                        user_id=user.id,
                        event_id=event.id,
                        source_base_analysis_id=analysis.id,
                        snapshot_position=index,
                        relevant=True,
                        priority=priorities[index],
                        snapshot_title=f"Frozen title {index}",
                        snapshot_overview=event.overview,
                        snapshot_state=event.state,
                        snapshot_display_time=event.display_time,
                        snapshot_event_updated_at=event.updated_at,
                        snapshot_topics=["AI"],
                        snapshot_new_claim_count=0,
                        snapshot_conflict_count=0,
                        why_it_matters=f"Why {index}",
                        personalized_angle=f"Angle {index}",
                        matched_scope_ids=["ai"],
                        matched_focus_ids=["deep_context"],
                    )
                    for index, (event, analysis) in enumerate(zip(events, analyses, strict=True))
                ]
            )
            await database.commit()

            repository = BriefRepository(database)
            run = await BriefRunner(repository, Model(), max_attempts=3).run_user(user.id)
            assert run.status == "completed"
            artifact, items = await repository.latest_items(user.id)
            assert artifact is not None
            assert len(items) == 8
            assert [item.snapshot_title for item in items[:3]] == [
                "Frozen title 1",
                "Frozen title 4",
                "Frozen title 8",
            ]
            assert [item.position for item in items] == list(range(8))

            events[1].title = "A later mutable title"
            await database.commit()
            _, items = await repository.latest_items(user.id)
            assert items[0].snapshot_title == "Frozen title 1"

            newer_run = PersonalizationRun(
                user_id=user.id,
                idempotency_key=uuid4(),
                schema_version="personalization_input.v1",
                input_hash="5" * 64,
                profile_hash="4" * 64,
                status="pending",
                active_slot=1,
                attempt_count=1,
                max_attempts=3,
                finished_at=now + timedelta(minutes=1),
            )
            database.add(newer_run)
            await database.flush()
            newer_run.status = "completed"
            newer_run.active_slot = None
            await database.flush()
            database.add(
                PersonalizationArtifact(
                    user_id=user.id,
                    created_by_run_id=newer_run.id,
                    artifact_kind="deterministic_empty",
                    schema_version="personalization.v1",
                    input_hash=newer_run.input_hash,
                    input_payload={},
                    output_payload={},
                    provider=None,
                    model=None,
                    token_usage=None,
                    window_started_at=now,
                    window_ended_at=now + timedelta(hours=1),
                    raw_information_count=0,
                    event_count=0,
                    relevant_event_count=0,
                    created_at=now + timedelta(minutes=1),
                )
            )
            await database.commit()
            assert await repository.latest_items(user.id) == (None, [])
            empty_run = await BriefRunner(repository, Model(), max_attempts=3).run_user(user.id)
            assert empty_run.status == "completed"
            empty_artifact, empty_items = await repository.latest_items(user.id)
            assert empty_artifact is not None
            assert empty_artifact.artifact_kind == "deterministic_empty"
            assert empty_items == []
    finally:
        async with session_factory() as database:
            await database.execute(delete(BriefItem).where(BriefItem.user_id == user_id))
            await database.execute(delete(BriefArtifact).where(BriefArtifact.user_id == user_id))
            await database.execute(delete(BriefRun).where(BriefRun.user_id == user_id))
            await database.execute(
                delete(PersonalizedEvent).where(PersonalizedEvent.user_id == user_id)
            )
            await database.execute(
                delete(PersonalizationArtifact).where(PersonalizationArtifact.user_id == user_id)
            )
            await database.execute(
                delete(PersonalizationRun).where(PersonalizationRun.user_id == user_id)
            )
            if event_ids:
                await database.execute(
                    delete(BaseAnalysis).where(BaseAnalysis.event_id.in_(event_ids))
                )
                await database.execute(delete(Event).where(Event.id.in_(event_ids)))
            await database.execute(
                delete(PipelineArtifact).where(
                    PipelineArtifact.id.in_([base_artifact_id, source_artifact_id])
                )
            )
            await database.execute(delete(PipelineRun).where(PipelineRun.id == pipeline_run_id))
            await database.execute(delete(User).where(User.id == user_id))
            await database.commit()
