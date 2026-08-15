from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import feedparser
import httpx

from infoscope.integrations.trendradar.config import HotlistSource, NewsNowConfig, RSSFeed
from infoscope.integrations.trendradar.models import CollectedItem

NEWSNOW_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 Chrome/140.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
}


class TrendRadarSourceError(Exception):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


def _safe_payload(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _url_matches_domain(url: str, expected_domain: str) -> bool:
    if not url:
        return True
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    expected = expected_domain.lower()
    return parsed.scheme == "https" and (hostname == expected or hostname.endswith(f".{expected}"))


def _published_at(entry: Any) -> datetime | None:
    value = entry.get("published_parsed") or entry.get("updated_parsed")
    if value is None:
        return None
    return datetime(*value[:6], tzinfo=UTC)


class NewsNowClient:
    def __init__(self, client: httpx.AsyncClient, config: NewsNowConfig) -> None:
        self.client = client
        self.config = config

    async def collect(self, source: HotlistSource) -> list[CollectedItem]:
        response: httpx.Response | None = None
        for attempt in range(self.config.max_retries + 1):
            try:
                response = await self.client.get(
                    self.config.api_url,
                    params={"id": source.id, "latest": ""},
                    headers=NEWSNOW_HEADERS,
                    timeout=self.config.timeout_seconds,
                )
                response.raise_for_status()
                break
            except (httpx.HTTPError, httpx.TimeoutException) as error:
                if attempt == self.config.max_retries:
                    raise TrendRadarSourceError("TRENDRADAR_HOTLIST_REQUEST_FAILED") from error
                await asyncio.sleep(2**attempt)

        if response is None:
            raise TrendRadarSourceError("TRENDRADAR_HOTLIST_REQUEST_FAILED")
        try:
            document = response.json()
        except ValueError as error:
            raise TrendRadarSourceError("TRENDRADAR_HOTLIST_INVALID_JSON") from error
        if not isinstance(document, dict) or document.get("status") not in {"success", "cache"}:
            raise TrendRadarSourceError("TRENDRADAR_HOTLIST_INVALID_STATUS")
        raw_items = document.get("items")
        if not isinstance(raw_items, list):
            raise TrendRadarSourceError("TRENDRADAR_HOTLIST_INVALID_ITEMS")
        updated_time = document.get("updatedTime")
        snapshot_id = str(updated_time) if isinstance(updated_time, int | str) else ""

        items: list[CollectedItem] = []
        for rank, raw_item in enumerate(raw_items, start=1):
            if not isinstance(raw_item, dict):
                continue
            title = raw_item.get("title")
            if not isinstance(title, str) or not title.strip():
                continue
            url = raw_item.get("url") if isinstance(raw_item.get("url"), str) else ""
            mobile_url = (
                raw_item.get("mobileUrl") if isinstance(raw_item.get("mobileUrl"), str) else ""
            )
            if not _url_matches_domain(url, source.expected_domain) or not _url_matches_domain(
                mobile_url, source.expected_domain
            ):
                raise TrendRadarSourceError("TRENDRADAR_HOTLIST_DOMAIN_MISMATCH")
            item_identity = url or mobile_url or title.strip()
            stable_id = f"{item_identity}\n{snapshot_id}" if snapshot_id else item_identity
            items.append(
                CollectedItem(
                    source_kind="hotlist",
                    source_id=source.id,
                    source_name=source.name,
                    stable_id=stable_id,
                    title=title.strip(),
                    url=url or mobile_url,
                    published_at=None,
                    payload=_safe_payload(raw_item),
                    collector_metadata={
                        "rank": rank,
                        "upstream_updated_time": snapshot_id or None,
                        "upstream_status": document["status"],
                    },
                )
            )
        return items


class RSSClient:
    def __init__(self, client: httpx.AsyncClient, *, timeout_seconds: float) -> None:
        self.client = client
        self.timeout_seconds = timeout_seconds

    async def collect(self, feed: RSSFeed) -> list[CollectedItem]:
        try:
            response = await self.client.get(feed.url, timeout=self.timeout_seconds)
            response.raise_for_status()
        except (httpx.HTTPError, httpx.TimeoutException) as error:
            raise TrendRadarSourceError("TRENDRADAR_RSS_REQUEST_FAILED") from error

        parsed = feedparser.parse(response.content)
        if parsed.bozo and not parsed.entries:
            raise TrendRadarSourceError("TRENDRADAR_RSS_PARSE_FAILED")

        items: list[CollectedItem] = []
        for entry in parsed.entries:
            title = str(entry.get("title") or "").strip()
            url = str(entry.get("link") or "").strip()
            guid = str(entry.get("id") or entry.get("guid") or "").strip()
            if not title and not url:
                continue
            items.append(
                CollectedItem(
                    source_kind="rss",
                    source_id=feed.id,
                    source_name=feed.name,
                    stable_id=guid or url or f"{title}\n{entry.get('published', '')}",
                    title=title or url,
                    url=url,
                    published_at=_published_at(entry),
                    payload={
                        "feed_url": feed.url,
                        "entry": _safe_payload(dict(entry)),
                    },
                    collector_metadata={"guid": guid},
                )
            )
        return items
