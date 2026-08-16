from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from infoscope.api.app import app
from infoscope.api.dependencies import get_ready_user
from infoscope.models import User
from infoscope.schemas.archive_search import (
    ArchiveResponse,
    EventSavedRequest,
    EventSavedResponse,
    EventSearchResponse,
)
from infoscope.schemas.now import EventSummary
from infoscope.services.archive_search import ArchiveSearchService, get_archive_search_service
from infoscope.services.event_save import get_event_save_service


def _ready_user() -> User:
    return User(
        username="alan",
        username_normalized="alan",
        password_hash="unused",
        onboarding_completed=True,
        scope_ids=["ai"],
        investment_market_ids=[],
        focus_ids=["deep_context"],
    )


def _summary(title: str) -> EventSummary:
    return EventSummary(
        id=uuid4(),
        title=title,
        overview="Overview",
        state="developing",
        display_time=datetime(2026, 8, 16, 12, tzinfo=UTC),
        updated_at=datetime(2026, 8, 16, 13, tzinfo=UTC),
        why_it_matters="Relevant",
        new_claim_count=0,
        conflict_count=0,
        topics=["AI"],
        saved=False,
    )


def test_saved_request_requires_a_real_boolean() -> None:
    assert EventSavedRequest(saved=True).saved is True
    with pytest.raises(ValidationError):
        EventSavedRequest(saved="true")  # type: ignore[arg-type]


def test_search_query_normalization_and_literal_escape() -> None:
    assert ArchiveSearchService.normalize_query("  AI\n  model  ") == "AI model"
    assert ArchiveSearchService._escape_like(r"50%_off\today") == r"50\%\_off\\today"
    with pytest.raises(Exception, match="search query is invalid"):
        ArchiveSearchService.normalize_query("   ")


def test_archive_and_search_cursors_are_endpoint_and_query_bound() -> None:
    source = SimpleNamespace(id=uuid4())
    item = SimpleNamespace(
        event_id=uuid4(),
        snapshot_display_time=datetime(2026, 8, 16, 12, tzinfo=UTC),
    )
    archive = ArchiveSearchService._next_cursor(
        source,
        [(item, False)],
        has_more=True,
        kind="archive",
    )
    assert archive is not None
    document = ArchiveSearchService._decode_cursor(
        archive,
        kind="archive",
        error_code="ARCHIVE_CURSOR_INVALID",
    )
    assert document["source_personalization_artifact_id"] == str(source.id)
    with pytest.raises(Exception, match="cursor is invalid"):
        ArchiveSearchService._decode_cursor(
            archive,
            kind="search_events",
            error_code="SEARCH_CURSOR_INVALID",
        )


@pytest.mark.asyncio
async def test_archive_and_search_public_routes_preserve_backend_order() -> None:
    first, second = _summary("First"), _summary("Second")

    class Service:
        async def archive(self, user, *, limit, cursor):
            assert user.username == "alan"
            assert (limit, cursor) == (20, None)
            return ArchiveResponse(items=[second, first], next_cursor="opaque")

        async def search(self, user, *, query_text, limit, cursor):
            assert user.username == "alan"
            assert (query_text, limit, cursor) == ("AI", 20, None)
            return EventSearchResponse(items=[second, first], next_cursor=None)

    app.dependency_overrides[get_ready_user] = _ready_user
    app.dependency_overrides[get_archive_search_service] = Service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            archive = await client.get("/api/v1/archive")
            search = await client.get("/api/v1/search/events?q=AI")
    finally:
        app.dependency_overrides.clear()

    assert archive.status_code == 200
    assert [item["title"] for item in archive.json()["items"]] == ["Second", "First"]
    assert archive.json()["next_cursor"] == "opaque"
    assert search.status_code == 200
    assert [item["title"] for item in search.json()["items"]] == ["Second", "First"]


@pytest.mark.asyncio
async def test_save_route_returns_the_final_idempotent_state() -> None:
    event_id = uuid4()

    class Service:
        async def set_saved(self, user, current_event_id, *, saved):
            assert user.username == "alan"
            assert current_event_id == event_id
            return EventSavedResponse(event_id=event_id, saved=saved)

    app.dependency_overrides[get_ready_user] = _ready_user
    app.dependency_overrides[get_event_save_service] = Service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.put(
                f"/api/v1/events/{event_id}/saved",
                json={"saved": True},
            )
            invalid = await client.put(
                f"/api/v1/events/{event_id}/saved",
                json={"saved": "true"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"event_id": str(event_id), "saved": True}
    assert invalid.status_code == 422
