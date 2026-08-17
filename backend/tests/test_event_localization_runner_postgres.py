import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from infoscope.analysis.localization_schemas import (
    EventLocalizationDecision,
    EventLocalizationPayload,
    EventLocalizationResponse,
)
from infoscope.analysis.schemas import TokenUsage
from infoscope.db import session_factory
from infoscope.models import (
    Event,
    EventLocalization,
    EventLocalizationBatch,
    EventLocalizationRun,
    User,
)
from infoscope.services.event_localization_worker import EventLocalizationRunner

pytestmark = pytest.mark.skipif(
    os.environ.get("INFOSCOPE_POSTGRES_INTEGRATION") != "1",
    reason="requires an isolated PostgreSQL integration database",
)


class FakeLocalizationClient:
    def __init__(self) -> None:
        self.calls = 0
        self.active = 0
        self.max_active = 0
        self.lock = asyncio.Lock()

    async def localize(self, value):
        async with self.lock:
            self.calls += 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.1)
        try:
            return EventLocalizationResponse(
                payload=EventLocalizationPayload(
                    decisions=[
                        EventLocalizationDecision(
                            event_id=item.event_id,
                            title=f"中文：{item.title}",
                            overview=f"中文：{item.overview}",
                        )
                        for item in value.events
                    ]
                ),
                provider="ai_ping",
                model="DeepSeek-V4-Flash-0731",
                token_usage=TokenUsage(
                    prompt_tokens=1,
                    completion_tokens=1,
                    total_tokens=2,
                ),
            )
        finally:
            async with self.lock:
                self.active -= 1


@pytest.mark.asyncio
async def test_runner_batches_concurrently_reuses_artifacts_and_requests_refresh() -> None:
    now = datetime.now(UTC)
    user_id = uuid4()
    event_ids = [uuid4() for _ in range(12)]
    async with session_factory() as database:
        database.add(
            User(
                id=user_id,
                username=f"localization-{user_id}",
                username_normalized=f"localization-{user_id}",
                password_hash="unused",
                onboarding_completed=True,
                scope_ids=["ai"],
                investment_market_ids=[],
                focus_ids=["deep_context"],
            )
        )
        database.add_all(
            [
                Event(
                    id=event_id,
                    title=f"Example AI release {index}",
                    overview=f"Version {index} launched on 2026-08-18.",
                    state="confirmed",
                    display_time=now - timedelta(minutes=index),
                )
                for index, event_id in enumerate(event_ids)
            ]
        )
        await database.commit()

    client = FakeLocalizationClient()
    runner = EventLocalizationRunner(
        session_factory,
        client,
        provider="ai_ping",
        model="DeepSeek-V4-Flash-0731",
        batch_size=10,
        batch_concurrency=2,
        max_attempts=3,
    )
    first = await runner.run()

    assert first.status == "completed"
    assert first.batch_count == 2
    assert client.calls == 2
    assert client.max_active == 2
    async with session_factory() as database:
        assert (
            await database.scalar(
                select(func.count(EventLocalization.id)).where(
                    EventLocalization.event_id.in_(event_ids)
                )
            )
            == 12
        )
        user = await database.get(User, user_id)
        assert user is not None and user.personalization_update_requested_at is not None
        changed = await database.get(Event, sorted(event_ids)[0])
        assert changed is not None
        changed.overview = f"{changed.overview} Availability expanded to 20 regions."
        await database.commit()

    second = await runner.run()

    assert second.status == "completed"
    assert second.id != first.id
    assert client.calls == 3
    assert second.token_usage == {
        "prompt_tokens": 1,
        "completion_tokens": 1,
        "total_tokens": 2,
    }
    async with session_factory() as database:
        reused = await database.scalar(
            select(func.count(EventLocalizationBatch.id)).where(
                EventLocalizationBatch.run_id == second.id,
                EventLocalizationBatch.artifact_reused.is_(True),
            )
        )
        assert reused == 1
        assert await database.scalar(select(func.count(EventLocalizationRun.id))) == 2
