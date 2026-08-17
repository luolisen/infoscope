from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from infoscope.analysis.localization_schemas import (
    EventLocalizationDecision,
    EventLocalizationInput,
    EventLocalizationPayload,
    validate_localization_output,
)
from infoscope.models import Event, EventLocalization
from infoscope.services.event_localization import (
    current_event_localizations,
    event_localization_hash,
    event_localization_item,
)

NOW = datetime(2026, 8, 18, 2, tzinfo=UTC)


def _event(*, event_id=None, updated_at=NOW) -> Event:
    return Event(
        id=event_id or uuid4(),
        title="NVIDIA invests $10 billion in Example AI",
        overview="The agreement starts on 2026-08-18. See https://example.com/a.",
        state="developing",
        display_time=NOW,
        created_at=NOW,
        updated_at=updated_at,
    )


def test_localization_output_preserves_exact_ids_urls_and_numbers() -> None:
    events = sorted([_event(), _event()], key=lambda item: item.id)
    value = EventLocalizationInput(events=[event_localization_item(item) for item in events])
    payload = EventLocalizationPayload(
        decisions=[
            EventLocalizationDecision(
                event_id=item.id,
                title="NVIDIA 向 Example AI 投资 $10 billion",
                overview="该协议于 2026-08-18 开始。详见 https://example.com/a.",
            )
            for item in events
        ]
    )

    validate_localization_output(value, payload)


def test_localization_output_rejects_reordered_or_changed_facts() -> None:
    events = sorted([_event(), _event()], key=lambda item: item.id)
    value = EventLocalizationInput(events=[event_localization_item(item) for item in events])
    reordered = EventLocalizationPayload(
        decisions=[
            EventLocalizationDecision(
                event_id=item.id,
                title="NVIDIA 向 Example AI 投资 $10 billion",
                overview="该协议于 2026-08-18 开始。详见 https://example.com/a.",
            )
            for item in reversed(events)
        ]
    )
    changed_number = EventLocalizationPayload(
        decisions=[
            EventLocalizationDecision(
                event_id=item.id,
                title="NVIDIA 向 Example AI 投资 $11 billion",
                overview="该协议于 2026-08-18 开始。详见 https://example.com/a.",
            )
            for item in events
        ]
    )

    with pytest.raises(ValueError, match="coverage and order"):
        validate_localization_output(value, reordered)
    with pytest.raises(ValueError, match="numeric tokens"):
        validate_localization_output(value, changed_number)


async def test_projection_is_used_only_for_current_event_input_hash() -> None:
    event = _event()
    current = EventLocalization(
        event_id=event.id,
        locale="zh-CN",
        source_artifact_id=uuid4(),
        event_input_hash=event_localization_hash(event),
        title="NVIDIA 投资 Example AI",
        overview="协议现已公布。",
    )

    class Scalars:
        def __init__(self, values):
            self.values = values

        def scalars(self):
            return self.values

    class Database:
        async def execute(self, _query):
            return Scalars([current])

    database = Database()
    assert await current_event_localizations(database, [event]) == {  # type: ignore[arg-type]
        event.id: (current.title, current.overview)
    }

    event.updated_at = NOW + timedelta(seconds=1)
    assert await current_event_localizations(database, [event]) == {}  # type: ignore[arg-type]
