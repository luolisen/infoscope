import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete

from infoscope.analysis.localization_schemas import OUTPUT_SCHEMA_VERSION
from infoscope.db import session_factory
from infoscope.models import Event, EventLocalization, EventLocalizationArtifact
from infoscope.services.event_localization import (
    current_event_localizations,
    event_localization_hash,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("INFOSCOPE_POSTGRES_INTEGRATION") != "1",
    reason="requires the local PostgreSQL integration database",
)


@pytest.mark.asyncio
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
