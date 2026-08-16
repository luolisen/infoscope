from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from infoscope.db import session_factory
from infoscope.models import (
    BaseAnalysis,
    Claim,
    Event,
    EventSave,
    PersonalizationArtifact,
    PersonalizationRun,
    PersonalizedEvent,
    PipelineArtifact,
    PipelineRun,
    User,
)
from infoscope.services.archive_search import ArchiveSearchService
from infoscope.services.event_detail import EventDetailService
from infoscope.services.event_save import EventSaveService
from infoscope.services.now import NowService

pytestmark = pytest.mark.skipif(
    os.environ.get("INFOSCOPE_POSTGRES_INTEGRATION") != "1",
    reason="requires the local PostgreSQL integration database",
)


@pytest.mark.asyncio
async def test_save_archive_search_and_cursor_snapshot_contract() -> None:
    user_id = uuid4()
    pipeline_run_id = uuid4()
    source_pipeline_artifact_id = uuid4()
    base_artifact_id = uuid4()
    event_ids = [uuid4(), uuid4(), uuid4()]
    now = datetime.now(UTC).replace(microsecond=0)

    async def completed_personalization(
        database,
        *,
        input_hash: str,
        created_at: datetime,
        snapshots: list[tuple[int, str, datetime]],
    ) -> PersonalizationArtifact:
        run = PersonalizationRun(
            user_id=user_id,
            idempotency_key=uuid4(),
            schema_version="personalization_input.v1",
            input_hash=input_hash,
            profile_hash="f" * 64,
            status="pending",
            active_slot=1,
            attempt_count=1,
            max_attempts=3,
            finished_at=created_at,
        )
        database.add(run)
        await database.flush()
        run.status = "completed"
        run.active_slot = None
        await database.flush()
        artifact = PersonalizationArtifact(
            user_id=user_id,
            created_by_run_id=run.id,
            artifact_kind="model",
            schema_version="personalization.v1",
            input_hash=input_hash,
            input_payload={},
            output_payload={},
            provider="test",
            model="test",
            token_usage={},
            window_started_at=created_at - timedelta(hours=1),
            window_ended_at=created_at,
            raw_information_count=len(snapshots),
            event_count=len(snapshots),
            relevant_event_count=len(snapshots),
            created_at=created_at,
        )
        database.add(artifact)
        await database.flush()
        database.add_all(
            [
                PersonalizedEvent(
                    artifact_id=artifact.id,
                    user_id=user_id,
                    event_id=event_ids[index],
                    source_base_analysis_id=base_analyses[index].id,
                    snapshot_position=position,
                    relevant=True,
                    priority="normal",
                    snapshot_title=title,
                    snapshot_overview=f"Snapshot overview {index}",
                    snapshot_state="developing",
                    snapshot_display_time=display_time,
                    snapshot_event_updated_at=created_at,
                    snapshot_topics=["AI"],
                    snapshot_new_claim_count=index,
                    snapshot_conflict_count=0,
                    why_it_matters=f"Why {index}",
                    personalized_angle=f"Angle {index}",
                    matched_scope_ids=["ai"],
                    matched_focus_ids=["deep_context"],
                )
                for position, (index, title, display_time) in enumerate(snapshots)
            ]
        )
        await database.commit()
        return artifact

    try:
        async with session_factory() as database:
            user = User(
                id=user_id,
                username=f"archive-{user_id}",
                username_normalized=f"archive-{user_id}",
                password_hash="unused",
                onboarding_completed=True,
                scope_ids=["ai"],
                investment_market_ids=[],
                focus_ids=["deep_context"],
            )
            pipeline_run = PipelineRun(
                id=pipeline_run_id,
                pipeline_name=f"archive-integration-{user_id}",
                status="succeeded",
                window_start=now.replace(minute=0, second=0),
                window_end=now.replace(minute=0, second=0) + timedelta(hours=1),
                attempt=1,
                started_at=now,
                finished_at=now,
            )
            database.add_all([user, pipeline_run])
            await database.flush()
            source_pipeline = PipelineArtifact(
                id=source_pipeline_artifact_id,
                pipeline_run_id=pipeline_run.id,
                artifact_type="archive_test_source",
                schema_version="archive_test_source.v1",
                input_hash="a" * 64,
                payload={},
                provider="test",
                model="test",
                token_usage={},
            )
            database.add(source_pipeline)
            await database.flush()
            base_artifact = PipelineArtifact(
                id=base_artifact_id,
                pipeline_run_id=pipeline_run.id,
                source_artifact_id=source_pipeline.id,
                artifact_type="base_analysis",
                schema_version="base_analysis.v1",
                input_hash="b" * 64,
                payload={},
                provider="test",
                model="test",
                token_usage={},
            )
            database.add(base_artifact)
            await database.flush()
            events = [
                Event(
                    id=event_ids[index],
                    title=f"Needle Event {index}",
                    overview=f"Current overview {index}",
                    state="developing",
                    display_time=now - timedelta(hours=index),
                )
                for index in range(3)
            ]
            database.add_all(events)
            await database.flush()
            base_analyses = [
                BaseAnalysis(
                    event_id=event.id,
                    source_artifact_id=base_artifact.id,
                    summary=f"Current analysis {index}",
                    event_type="technology.release",
                    importance="high",
                    topics=["AI"],
                    entities=[{"name": "Example", "entity_type": "company"}],
                )
                for index, event in enumerate(events)
            ]
            database.add_all(base_analyses)
            await database.flush()
            database.add(
                Claim(
                    event_id=event_ids[1],
                    text="A unique claim search phrase",
                    state="confirmed",
                )
            )
            await database.commit()

            await completed_personalization(
                database,
                input_hash="1" * 64,
                created_at=now,
                snapshots=[
                    (0, "A Current", now + timedelta(hours=1)),
                    (1, "A Exited", now),
                    (2, "A Saved", now + timedelta(hours=2)),
                ],
            )
            source = await completed_personalization(
                database,
                input_hash="2" * 64,
                created_at=now + timedelta(minutes=1),
                snapshots=[
                    (0, "B Current", now + timedelta(hours=1)),
                    (2, "B Saved", now + timedelta(hours=2)),
                ],
            )

            save_service = EventSaveService(database)
            assert (await save_service.set_saved(user, event_ids[2], saved=True)).saved
            assert (await save_service.set_saved(user, event_ids[2], saved=True)).saved
            assert await database.scalar(
                select(EventSave.id).where(
                    EventSave.user_id == user_id,
                    EventSave.event_id == event_ids[2],
                )
            )

            now_response = await NowService(database).get_now(user, limit=20, cursor=None)
            assert next(item for item in now_response.items if item.id == event_ids[2]).saved
            detail = await EventDetailService(database).get(user, event_ids[2])
            assert detail.saved

            service = ArchiveSearchService(database)
            archive_first = await service.archive(user, limit=1, cursor=None)
            assert [item.title for item in archive_first.items] == ["B Saved"]
            assert archive_first.next_cursor is not None
            search_first = await service.search(
                user,
                query_text="Needle",
                limit=1,
                cursor=None,
            )
            assert [item.title for item in search_first.items] == ["B Saved"]
            assert search_first.next_cursor is not None

            newer = await completed_personalization(
                database,
                input_hash="3" * 64,
                created_at=now + timedelta(minutes=2),
                snapshots=[
                    (0, "C Current", now + timedelta(hours=5)),
                    (1, "C Returned", now + timedelta(hours=4)),
                    (2, "C Saved", now + timedelta(hours=6)),
                ],
            )
            assert newer.id != source.id

            archive_second = await service.archive(
                user,
                limit=1,
                cursor=archive_first.next_cursor,
            )
            assert [item.title for item in archive_second.items] == ["A Exited"]
            search_second = await service.search(
                user,
                query_text="  Needle  ",
                limit=1,
                cursor=search_first.next_cursor,
            )
            assert [item.title for item in search_second.items] == ["B Current"]
            with pytest.raises(Exception, match="cursor is invalid"):
                await service.search(
                    user,
                    query_text="different",
                    limit=1,
                    cursor=search_first.next_cursor,
                )

            claim_search = await service.search(
                user,
                query_text="unique claim",
                limit=20,
                cursor=None,
            )
            assert [item.id for item in claim_search.items] == [event_ids[1]]

            assert not (await save_service.set_saved(user, event_ids[2], saved=False)).saved
            assert not (await save_service.set_saved(user, event_ids[2], saved=False)).saved
    finally:
        async with session_factory() as database:
            await database.execute(delete(EventSave).where(EventSave.user_id == user_id))
            await database.execute(
                delete(PersonalizedEvent).where(PersonalizedEvent.user_id == user_id)
            )
            await database.execute(
                delete(PersonalizationArtifact).where(PersonalizationArtifact.user_id == user_id)
            )
            await database.execute(
                delete(PersonalizationRun).where(PersonalizationRun.user_id == user_id)
            )
            await database.execute(delete(Claim).where(Claim.event_id.in_(event_ids)))
            await database.execute(delete(BaseAnalysis).where(BaseAnalysis.event_id.in_(event_ids)))
            await database.execute(delete(Event).where(Event.id.in_(event_ids)))
            await database.execute(
                delete(PipelineArtifact).where(
                    PipelineArtifact.id.in_([base_artifact_id, source_pipeline_artifact_id])
                )
            )
            await database.execute(delete(PipelineRun).where(PipelineRun.id == pipeline_run_id))
            await database.execute(delete(User).where(User.id == user_id))
            await database.commit()
