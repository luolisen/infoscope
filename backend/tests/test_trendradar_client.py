import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from infoscope.integrations.trendradar.client import (
    NewsNowClient,
    RSSClient,
    TrendRadarSourceError,
)
from infoscope.integrations.trendradar.config import HotlistSource, NewsNowConfig, RSSFeed


async def test_newsnow_client_parses_the_verified_hotlist_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["id"] == "zhihu"
        assert request.headers["accept-language"].startswith("zh-CN")
        assert "Mozilla/5.0" in request.headers["user-agent"]
        return httpx.Response(
            200,
            json={
                "status": "success",
                "updatedTime": 1786820192513,
                "items": [
                    {
                        "title": "A verified title",
                        "url": "https://www.zhihu.com/question/1",
                        "mobileUrl": "https://www.zhihu.com/question/1",
                        "extra": {"preserved": True},
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = NewsNowClient(
            http,
            NewsNowConfig(
                api_url="https://newsnow.example/api/s",
                timeout_seconds=10,
                max_retries=0,
                sources=(),
            ),
        )
        items = await client.collect(
            HotlistSource(id="zhihu", name="知乎", expected_domain="zhihu.com")
        )

    assert len(items) == 1
    assert items[0].source_kind == "hotlist"
    assert items[0].title == "A verified title"
    assert items[0].stable_id.endswith("\n1786820192513")
    assert items[0].collector_metadata == {
        "rank": 1,
        "upstream_updated_time": "1786820192513",
        "upstream_status": "success",
    }
    assert items[0].payload["extra"] == {"preserved": True}


async def test_newsnow_client_rejects_a_mismatched_item_domain() -> None:
    response = {"status": "cache", "items": [{"title": "unsafe", "url": "https://evil.test"}]}

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response))
    ) as http:
        client = NewsNowClient(
            http,
            NewsNowConfig("https://newsnow.example/api/s", 10, 0, ()),
        )
        with pytest.raises(TrendRadarSourceError) as error:
            await client.collect(
                HotlistSource(id="baidu", name="百度热搜", expected_domain="baidu.com")
            )

    assert error.value.error_code == "TRENDRADAR_HOTLIST_DOMAIN_MISMATCH"


async def test_newsnow_client_retries_a_transient_http_failure() -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"status": "success", "items": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = NewsNowClient(
            http,
            NewsNowConfig("https://newsnow.example/api/s", 10, 1, ()),
        )
        with patch(
            "infoscope.integrations.trendradar.client.asyncio.sleep", new_callable=AsyncMock
        ) as sleep:
            items = await client.collect(
                HotlistSource(id="baidu", name="百度热搜", expected_domain="baidu.com")
            )

    assert items == []
    assert attempts == 2
    sleep.assert_awaited_once_with(1)


async def test_rss_client_parses_rss_and_preserves_the_entry_payload() -> None:
    xml = """
    <rss version="2.0">
      <channel>
        <title>Hacker News</title>
        <item>
          <title>Example story</title>
          <link>https://example.com/story</link>
          <guid>story-1</guid>
          <pubDate>Sun, 16 Aug 2026 10:30:00 GMT</pubDate>
          <description>Story summary</description>
        </item>
      </channel>
    </rss>
    """

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=xml))
    ) as http:
        items = await RSSClient(http, timeout_seconds=15).collect(
            RSSFeed(id="hacker-news", name="Hacker News", url="https://hnrss.org/frontpage")
        )

    assert len(items) == 1
    assert items[0].stable_id == "story-1"
    assert items[0].published_at == datetime(2026, 8, 16, 10, 30, tzinfo=UTC)
    assert items[0].payload["entry"]["summary"] == "Story summary"
    assert json.loads(json.dumps(items[0].payload)) == items[0].payload


async def test_rss_client_uses_a_stable_parse_failure_code() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"not a feed"))
    ) as http:
        with pytest.raises(TrendRadarSourceError) as error:
            await RSSClient(http, timeout_seconds=15).collect(
                RSSFeed(id="broken", name="Broken", url="https://example.com/feed")
            )

    assert error.value.error_code == "TRENDRADAR_RSS_PARSE_FAILED"
