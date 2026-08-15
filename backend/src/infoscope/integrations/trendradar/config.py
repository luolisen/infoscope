from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml


@dataclass(frozen=True, slots=True)
class HotlistSource:
    id: str
    name: str
    expected_domain: str


@dataclass(frozen=True, slots=True)
class RSSFeed:
    id: str
    name: str
    url: str


@dataclass(frozen=True, slots=True)
class NewsNowConfig:
    api_url: str
    timeout_seconds: float
    max_retries: int
    sources: tuple[HotlistSource, ...]


@dataclass(frozen=True, slots=True)
class RSSConfig:
    timeout_seconds: float
    feeds: tuple[RSSFeed, ...]


@dataclass(frozen=True, slots=True)
class TrendRadarConfig:
    newsnow: NewsNowConfig
    rss: RSSConfig


def _mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be a mapping")
    return value


def _list(value: Any, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    return value


def _string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _positive_number(value: Any, field_name: str) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field_name} must be positive")
    return float(value)


def _safe_http_url(value: Any, field_name: str) -> str:
    url = _string(value, field_name)
    parsed = urlparse(url)
    local_http = parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}
    if parsed.scheme != "https" and not local_http:
        raise ValueError(f"{field_name} must use HTTPS or local HTTP")
    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError(f"{field_name} must be an absolute URL without credentials")
    return url


def _unique_ids(values: list[Any], field_name: str) -> None:
    ids = [_string(_mapping(value, field_name).get("id"), f"{field_name}.id") for value in values]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{field_name} contains duplicate ids")


def load_trendradar_config(path: Path) -> TrendRadarConfig:
    if not path.is_file():
        raise ValueError(f"TrendRadar config not found: {path}")
    document = _mapping(yaml.safe_load(path.read_text(encoding="utf-8")), "config")
    newsnow = _mapping(document.get("newsnow"), "newsnow")
    rss = _mapping(document.get("rss"), "rss")
    source_values = _list(newsnow.get("sources"), "newsnow.sources")
    feed_values = _list(rss.get("feeds"), "rss.feeds")
    _unique_ids(source_values, "newsnow.sources")
    _unique_ids(feed_values, "rss.feeds")

    sources = tuple(
        HotlistSource(
            id=_string(source.get("id"), "newsnow.sources.id"),
            name=_string(source.get("name"), "newsnow.sources.name"),
            expected_domain=_string(
                source.get("expected_domain"), "newsnow.sources.expected_domain"
            ).lower(),
        )
        for source in (_mapping(value, "newsnow.sources") for value in source_values)
    )
    feeds = tuple(
        RSSFeed(
            id=_string(feed.get("id"), "rss.feeds.id"),
            name=_string(feed.get("name"), "rss.feeds.name"),
            url=_safe_http_url(feed.get("url"), "rss.feeds.url"),
        )
        for feed in (_mapping(value, "rss.feeds") for value in feed_values)
    )
    max_retries = newsnow.get("max_retries")
    if not isinstance(max_retries, int) or isinstance(max_retries, bool) or max_retries < 0:
        raise ValueError("newsnow.max_retries must be a non-negative integer")

    return TrendRadarConfig(
        newsnow=NewsNowConfig(
            api_url=_safe_http_url(newsnow.get("api_url"), "newsnow.api_url"),
            timeout_seconds=_positive_number(
                newsnow.get("timeout_seconds"), "newsnow.timeout_seconds"
            ),
            max_retries=max_retries,
            sources=sources,
        ),
        rss=RSSConfig(
            timeout_seconds=_positive_number(rss.get("timeout_seconds"), "rss.timeout_seconds"),
            feeds=feeds,
        ),
    )
