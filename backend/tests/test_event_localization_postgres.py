import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from infoscope.analysis.localization_schemas import (
    OUTPUT_SCHEMA_VERSION,
    EventLocalizationDecision,
    EventLocalizationInput,
    EventLocalizationPayload,
    EventLocalizationResponse,
    canonical_hash,
)
from infoscope.analysis.schemas import TokenUsage
from infoscope.db import session_factory
from infoscope.models import (
    Event,
    EventLocalization,
    EventLocalizationArtifact,
    EventLocalizationBatch,
    EventLocalizationRun,
)
from infoscope.services.event_localization import (
    current_event_localizations,
    event_localization_hash,
    event_localization_item,
)
from infoscope.services.event_localization_worker import EventLocalizationRepository

pytestmark = pytest.mark.skipif(
    os.environ.get("INFOSCOPE_POSTGRES_INTEGRATION") != "1",
    reason="requires the local PostgreSQL integration database",
)


@pytest.mark.asyncio(loop_scope="module")
async def test_current_projection_fails_closed_after_event_changes() -> None:
    event_id = uuid4()
    artifact_id = uuid4()
    now = datetime.now(UTC)
    try:
        async with session_factory() as database:
            event = Event(
                id=event_id,
                title="Example launches AI system",
                overview="The system launched on 2026-08-18.",
                state="confirmed",
                display_time=now,
            )
            artifact = EventLocalizationArtifact(
                id=artifact_id,
                locale="zh-CN",
                schema_version=OUTPUT_SCHEMA_VERSION,
                input_hash="a" * 64,
                output_payload={"schema_version": OUTPUT_SCHEMA_VERSION, "decisions": []},
                provider="ai_ping",
                model="DeepSeek-V4-Flash-0731",
                token_usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            )
            database.add_all([event, artifact])
            await database.flush()
            projection = EventLocalization(
                event_id=event.id,
                locale="zh-CN",
                source_artifact_id=artifact.id,
                event_input_hash=event_localization_hash(event),
                title="Example 发布 AI 系统",
                overview="该系统于 2026-08-18 发布。",
            )
            database.add(projection)
            await database.commit()

            assert await current_event_localizations(database, [event]) == {
                event.id: (projection.title, projection.overview)
            }

            event.overview = "The system launched on 2026-08-18 and is now generally available."
            await database.commit()
            await database.refresh(event)

            assert await current_event_localizations(database, [event]) == {}
    finally:
        async with session_factory() as database:
            await database.execute(
                delete(EventLocalization).where(EventLocalization.event_id == event_id)
            )
            await database.execute(
                delete(EventLocalizationArtifact).where(EventLocalizationArtifact.id == artifact_id)
            )
            await database.execute(delete(Event).where(Event.id == event_id))
            await database.commit()


@pytest.mark.asyncio(loop_scope="module")
async def test_batch_persists_immutable_artifact_and_projection_atomically() -> None:
    event_id = uuid4()
    run_id = uuid4()
    batch_id = uuid4()
    artifact_id = None
    now = datetime.now(UTC)
    try:
        async with session_factory() as database:
            event = Event(
                id=event_id,
                title="Example raises $20 million",
                overview="The round closed on 2026-08-18.",
                state="confirmed",
                display_time=now,
            )
            database.add(event)
            await database.flush()
            value = EventLocalizationInput(events=[event_localization_item(event)])
            run = EventLocalizationRun(
                id=run_id,
                locale="zh-CN",
                input_hash="b" * 64,
                status="running",
                active_slot=1,
                provider="ai_ping",
                model="DeepSeek-V4-Flash-0731",
                batch_size=10,
                batch_concurrency=2,
                total_event_count=1,
                batch_count=1,
                completed_batch_count=0,
                failed_batch_count=0,
                started_at=now,
            )
            database.add(run)
            await database.flush()
            batch = EventLocalizationBatch(
                id=batch_id,
                run_id=run.id,
                batch_index=0,
                event_ids=[event.id],
                input_hash=canonical_hash(value),
                status="pending",
                attempt_count=0,
                max_attempts=3,
            )
            database.add(batch)
            await database.commit()

            repository = EventLocalizationRepository(database)
            claimed, original = await repository.claim_batch(batch.id)
            assert claimed.attempt_count == 1
            response = EventLocalizationResponse(
                payload=EventLocalizationPayload(
                    decisions=[
                        EventLocalizationDecision(
                            event_id=event.id,
                            title="Example 融资 $20 million",
                            overview="本轮融资于 2026-08-18 完成。",
                        )
                    ]
                ),
                provider="ai_ping",
                model="DeepSeek-V4-Flash-0731",
                token_usage=TokenUsage(
                    prompt_tokens=10,
                    completion_tokens=5,
                    total_tokens=15,
                ),
            )
            await repository.persist_success(batch.id, original, response)

            await database.refresh(batch)
            artifact_id = batch.artifact_id
            assert batch.status == "completed"
            assert batch.artifact_reused is False
            assert batch.token_usage == {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            }
            assert artifact_id is not None
            projection = (
                await database.execute(
                    select(EventLocalization).where(EventLocalization.event_id == event.id)
                )
            ).scalar_one()
            assert projection.title == "Example 融资 $20 million"
            assert projection.event_input_hash == event_localization_hash(event)
    finally:
        async with session_factory() as database:
            await database.execute(
                delete(EventLocalization).where(EventLocalization.event_id == event_id)
            )
            await database.execute(
                delete(EventLocalizationBatch).where(EventLocalizationBatch.id == batch_id)
            )
            await database.execute(
                delete(EventLocalizationRun).where(EventLocalizationRun.id == run_id)
            )
            if artifact_id is not None:
                await database.execute(
                    delete(EventLocalizationArtifact).where(
                        EventLocalizationArtifact.id == artifact_id
                    )
                )
            await database.execute(delete(Event).where(Event.id == event_id))
            await database.commit()
