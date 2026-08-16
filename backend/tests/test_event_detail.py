from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from infoscope.api.app import app
from infoscope.api.dependencies import get_ready_user
from infoscope.errors import ApiError
from infoscope.models import BaseAnalysis, Claim, Conflict, Event, Signal, TimelineEntry, User
from infoscope.schemas.event_detail import EventDetailResponse
from infoscope.services.event_access import EventAccessPolicy
from infoscope.services.event_detail import EventDetailService, get_event_detail_service

NOW = datetime(2026, 8, 16, 6, tzinfo=UTC)


def _user() -> User:
    return User(
        id=uuid4(),
        username="alan",
        username_normalized="alan",
        password_hash="unused",
        onboarding_completed=True,
    )


def _facts(*, private_provenance=None):
    event = Event(
        id=uuid4(),
        title="Event",
        overview="Known facts",
        state="developing",
        display_time=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    analysis = BaseAnalysis(
        id=uuid4(),
        event_id=event.id,
        source_artifact_id=uuid4(),
        summary="Why this matters now",
        event_type="technology",
        importance="high",
        topics=["AI", "Infrastructure"],
        entities=[{"name": "Example", "entity_type": "organization"}],
        created_at=NOW,
        updated_at=NOW,
    )
    first_claim = Claim(
        id=uuid4(),
        event_id=event.id,
        text="First claim",
        state="confirmed",
        created_at=NOW,
        updated_at=NOW,
    )
    second_claim = Claim(
        id=uuid4(),
        event_id=event.id,
        text="Second claim",
        state="unresolved",
        created_at=NOW + timedelta(seconds=1),
        updated_at=NOW,
    )
    timeline = TimelineEntry(
        id=uuid4(),
        event_id=event.id,
        occurred_at=NOW - timedelta(hours=1),
        summary="Earlier update",
        created_at=NOW,
        updated_at=NOW,
    )
    conflict = Conflict(
        id=uuid4(),
        event_id=event.id,
        summary="Claims differ",
        created_at=NOW,
        updated_at=NOW,
    )
    public = Signal(
        id=uuid4(),
        raw_information_id=uuid4(),
        signal_index=0,
        title="Public",
        normalized_text="Public evidence",
        published_at=NOW,
        source_type="trend_radar",
        evidence_visibility="public",
        public_provenance={
            "source_kind": "rss",
            "source_name": "Example Feed",
            "url": "https://example.com/item",
        },
        content_hash="1" * 64,
        created_at=NOW,
    )
    private = Signal(
        id=uuid4(),
        raw_information_id=uuid4(),
        signal_index=0,
        title=None,
        normalized_text="Sanitized private evidence",
        published_at=None,
        source_type="telegram",
        evidence_visibility="private_sanitized",
        public_provenance=private_provenance,
        content_hash="2" * 64,
        created_at=NOW - timedelta(seconds=1),
    )
    return event, analysis, [first_claim, second_claim], [timeline], [conflict], [public, private]


def _response(*, private_provenance=None) -> EventDetailResponse:
    event, analysis, claims, timeline, conflicts, signals = _facts(
        private_provenance=private_provenance
    )
    return EventDetailService._response(
        EventDetailService(database=None),  # type: ignore[arg-type]
        event=event,
        analysis=analysis,
        claims=claims,
        timeline=timeline,
        conflicts=conflicts,
        signals=signals,
        claim_signal_rows=[(claims[0].id, signals[1].id), (claims[0].id, signals[0].id)],
        timeline_claim_rows=[(timeline[0].id, claims[1].id), (timeline[0].id, claims[0].id)],
        conflict_claim_rows=[(conflicts[0].id, claims[1].id), (conflicts[0].id, claims[0].id)],
        conflict_signal_rows=[(conflicts[0].id, signals[1].id)],
    )


def test_event_detail_projects_base_analysis_relations_and_safe_provenance() -> None:
    response = _response()
    assert response.why_it_matters == response.base_analysis.summary
    assert response.topics == ["AI", "Infrastructure"]
    assert response.saved is False
    assert response.claims[0].evidence_ids == [
        response.evidence[0].id,
        response.evidence[1].id,
    ]
    assert response.timeline[0].claim_ids == [
        response.claims[0].id,
        response.claims[1].id,
    ]
    assert response.evidence[0].platform == "rss"
    assert response.evidence[0].author_name == "Example Feed"
    assert response.evidence[1].platform == "telegram"
    assert response.evidence[1].author_name is None
    assert response.evidence[1].url is None


def test_event_detail_fails_closed_for_private_provenance() -> None:
    with pytest.raises(ApiError) as captured:
        _response(private_provenance={"chat_title": "must-not-leak"})
    assert captured.value.status_code == 500
    assert captured.value.code == "INTERNAL_SERVER_ERROR"


@pytest.mark.parametrize(
    ("source_type", "provenance", "platform", "author_name", "url"),
    [
        (
            "telegram",
            {
                "platform": "Telegram",
                "chat_title": "Public channel",
                "chat_username": "public_channel",
                "url": "https://t.me/public_channel/1",
            },
            "telegram",
            "Public channel",
            "https://t.me/public_channel/1",
        ),
        (
            "trend_radar",
            {
                "source_kind": "hotlist",
                "source_name": "Example Hotlist",
                "url": "https://example.com/hot/1",
            },
            "web",
            "Example Hotlist",
            "https://example.com/hot/1",
        ),
        (
            "research",
            {
                "source_kind": "github_document",
                "canonical_url": "https://github.com/example/repo/blob/main/README.md",
            },
            "web",
            None,
            "https://github.com/example/repo/blob/main/README.md",
        ),
    ],
)
def test_event_detail_flattens_only_controlled_public_provenance(
    source_type, provenance, platform, author_name, url
) -> None:
    signal = Signal(
        id=uuid4(),
        raw_information_id=uuid4(),
        signal_index=0,
        title=None,
        normalized_text="Public evidence",
        published_at=NOW,
        source_type=source_type,
        evidence_visibility="public",
        public_provenance=provenance,
        content_hash="3" * 64,
        created_at=NOW,
    )

    evidence = EventDetailService._evidence(signal)

    assert evidence.platform == platform
    assert evidence.author_name == author_name
    assert evidence.url == url


def test_event_detail_rejects_cross_event_or_dangling_relations() -> None:
    event, analysis, claims, timeline, conflicts, signals = _facts()
    with pytest.raises(ApiError) as captured:
        EventDetailService._response(
            EventDetailService(database=None),  # type: ignore[arg-type]
            event=event,
            analysis=analysis,
            claims=claims,
            timeline=timeline,
            conflicts=conflicts,
            signals=signals,
            claim_signal_rows=[(claims[0].id, uuid4())],
            timeline_claim_rows=[],
            conflict_claim_rows=[],
            conflict_signal_rows=[],
        )
    assert captured.value.code == "INTERNAL_SERVER_ERROR"


def test_event_detail_rejects_duplicate_top_level_records() -> None:
    event, analysis, claims, timeline, conflicts, signals = _facts()
    with pytest.raises(ApiError) as captured:
        EventDetailService._response(
            EventDetailService(database=None),  # type: ignore[arg-type]
            event=event,
            analysis=analysis,
            claims=[*claims, claims[0]],
            timeline=timeline,
            conflicts=conflicts,
            signals=signals,
            claim_signal_rows=[],
            timeline_claim_rows=[],
            conflict_claim_rows=[],
            conflict_signal_rows=[],
        )
    assert captured.value.code == "INTERNAL_SERVER_ERROR"


class _Service:
    def __init__(self, response: EventDetailResponse) -> None:
        self.response = response

    async def get(self, user, event_id):
        assert event_id == self.response.id
        return self.response


class _ScalarResult:
    def __init__(self, values) -> None:
        self.values = values

    def scalars(self):
        return self.values


class _MissingAccessDatabase:
    async def execute(self, statement):
        return _ScalarResult([])


class _AllowAccess:
    async def require_all(self, user, event_ids) -> None:
        return None


class _MissingAnalysisDatabase:
    def __init__(self, event: Event) -> None:
        self.values = iter([event, None])

    async def scalar(self, statement):
        return next(self.values)


async def test_event_access_policy_returns_non_enumerating_not_found() -> None:
    policy = EventAccessPolicy(_MissingAccessDatabase())  # type: ignore[arg-type]

    with pytest.raises(ApiError) as captured:
        await policy.require_all(_user(), [uuid4()])

    assert captured.value.status_code == 404
    assert captured.value.code == "EVENT_NOT_FOUND"


async def test_event_detail_reports_not_ready_before_loading_facts() -> None:
    event, *_ = _facts()
    service = EventDetailService(
        _MissingAnalysisDatabase(event),  # type: ignore[arg-type]
        _AllowAccess(),  # type: ignore[arg-type]
    )

    with pytest.raises(ApiError) as captured:
        await service.get(_user(), event.id)

    assert captured.value.status_code == 409
    assert captured.value.code == "EVENT_NOT_READY"


async def test_event_detail_api_returns_the_frozen_public_dto() -> None:
    response = _response()
    app.dependency_overrides[get_ready_user] = _user
    app.dependency_overrides[get_event_detail_service] = lambda: _Service(response)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            result = await client.get(f"/api/v1/events/{response.id}")
    finally:
        app.dependency_overrides.clear()

    assert result.status_code == 200
    assert result.json()["base_analysis"]["importance"] == "high"
    assert result.json()["claims"][0]["evidence_ids"] == [
        str(response.evidence[0].id),
        str(response.evidence[1].id),
    ]
    assert result.json()["evidence"][1]["author_name"] is None
