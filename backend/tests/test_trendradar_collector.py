from datetime import UTC, datetime
from types import SimpleNamespace

from infoscope.integrations.trendradar.client import TrendRadarSourceError
from infoscope.integrations.trendradar.collector import TrendRadarCollector
from infoscope.integrations.trendradar.config import (
    HotlistSource,
    NewsNowConfig,
    RSSConfig,
    RSSFeed,
    TrendRadarConfig,
)
from infoscope.integrations.trendradar.models import CollectedItem
from infoscope.models import SourceVisibility


class FakeHotlists:
    async def collect(self, source: HotlistSource) -> list[CollectedItem]:
        if source.id == "failed-source":
            raise TrendRadarSourceError("TRENDRADAR_HOTLIST_REQUEST_FAILED")
        return [
            CollectedItem(
                source_kind="hotlist",
                source_id=source.id,
                source_name=source.name,
                stable_id="https://example.com/hotlist-item",
                title="Hotlist item",
                url="https://example.com/hotlist-item",
                published_at=None,
                payload={"title": "Hotlist item", "rank": 1},
                collector_metadata={"rank": 1, "upstream_status": "success"},
            )
        ]


class FakeRSS:
    async def collect(self, feed: RSSFeed) -> list[CollectedItem]:
        return [
            CollectedItem(
                source_kind="rss",
                source_id=feed.id,
                source_name=feed.name,
                stable_id="rss-guid",
                title="RSS item",
                url="https://example.com/rss-item",
                published_at=datetime(2026, 8, 16, 9, tzinfo=UTC),
                payload={"entry": {"summary": "Summary"}},
                collector_metadata={"guid": "rss-guid"},
            )
        ]


class FakeRepository:
    def __init__(self) -> None:
        self.values: list[object] = []

    async def persist_raw(self, value: object) -> SimpleNamespace:
        self.values.append(value)
        return SimpleNamespace(inserted=len(self.values) == 1)


async def test_collector_isolates_source_failures_and_persists_each_raw() -> None:
    config = TrendRadarConfig(
        newsnow=NewsNowConfig(
            api_url="https://newsnow.example/api/s",
            timeout_seconds=10,
            max_retries=0,
            sources=(
                HotlistSource("working-source", "Working", "example.com"),
                HotlistSource("failed-source", "Failed", "example.com"),
            ),
        ),
        rss=RSSConfig(
            timeout_seconds=15,
            feeds=(RSSFeed("hacker-news", "Hacker News", "https://hnrss.org/frontpage"),),
        ),
    )
    repository = FakeRepository()
    acquired_at = datetime(2026, 8, 16, 10, tzinfo=UTC)
    collector = TrendRadarCollector(
        config=config,
        hotlists=FakeHotlists(),  # type: ignore[arg-type]
        rss=FakeRSS(),  # type: ignore[arg-type]
        repository=repository,  # type: ignore[arg-type]
        clock=lambda: acquired_at,
    )

    result = await collector.collect()

    assert result.inserted == 1
    assert result.duplicates == 1
    assert [(failure.source_id, failure.error_code) for failure in result.failures] == [
        ("failed-source", "TRENDRADAR_HOTLIST_REQUEST_FAILED")
    ]
    assert len(repository.values) == 2
    hotlist, rss = repository.values
    assert hotlist.source_type == "trend_radar"  # type: ignore[attr-defined]
    assert hotlist.source_visibility is SourceVisibility.PUBLIC  # type: ignore[attr-defined]
    assert hotlist.acquired_at == acquired_at  # type: ignore[attr-defined]
    assert rss.content_text == "RSS item\nSummary"  # type: ignore[attr-defined]
    assert rss.source_key.startswith("rss:hacker-news:")  # type: ignore[attr-defined]
