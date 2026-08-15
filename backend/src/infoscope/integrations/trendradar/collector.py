from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime

from infoscope.integrations.trendradar.client import (
    NewsNowClient,
    RSSClient,
    TrendRadarSourceError,
)
from infoscope.integrations.trendradar.config import TrendRadarConfig
from infoscope.integrations.trendradar.models import (
    CollectedItem,
    CollectionResult,
    SourceFailure,
)
from infoscope.models import SourceVisibility
from infoscope.services.acquisition import AcquisitionRepository, RawInformationInput


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _content_hash(item: CollectedItem) -> str:
    canonical = json.dumps(item.payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _sha256(canonical)


class TrendRadarCollector:
    def __init__(
        self,
        *,
        config: TrendRadarConfig,
        hotlists: NewsNowClient,
        rss: RSSClient,
        repository: AcquisitionRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.config = config
        self.hotlists = hotlists
        self.rss = rss
        self.repository = repository
        self.clock = clock

    async def collect(self) -> CollectionResult:
        inserted = 0
        duplicates = 0
        failures: list[SourceFailure] = []

        for source in self.config.newsnow.sources:
            try:
                items = await self.hotlists.collect(source)
            except TrendRadarSourceError as error:
                failures.append(SourceFailure(source_id=source.id, error_code=error.error_code))
                continue
            new_count, duplicate_count = await self._persist_items(items)
            inserted += new_count
            duplicates += duplicate_count

        for feed in self.config.rss.feeds:
            try:
                items = await self.rss.collect(feed)
            except TrendRadarSourceError as error:
                failures.append(SourceFailure(source_id=feed.id, error_code=error.error_code))
                continue
            new_count, duplicate_count = await self._persist_items(items)
            inserted += new_count
            duplicates += duplicate_count

        return CollectionResult(
            inserted=inserted,
            duplicates=duplicates,
            failures=tuple(failures),
        )

    async def _persist_items(self, items: list[CollectedItem]) -> tuple[int, int]:
        inserted = 0
        duplicates = 0
        for item in items:
            acquired_at = self.clock()
            identity_hash = _sha256(item.stable_id)
            content_text = item.title
            if item.source_kind == "rss":
                summary = item.payload.get("entry", {}).get("summary")
                if isinstance(summary, str) and summary.strip():
                    content_text = f"{item.title}\n{summary.strip()}"
            persisted = await self.repository.persist_raw(
                RawInformationInput(
                    source_type="trend_radar",
                    source_key=f"{item.source_kind}:{item.source_id}:{identity_hash}",
                    source_visibility=SourceVisibility.PUBLIC,
                    acquired_at=acquired_at,
                    published_at=item.published_at,
                    content_text=content_text,
                    payload=item.payload,
                    provenance={
                        "source_kind": item.source_kind,
                        "source_id": item.source_id,
                        "source_name": item.source_name,
                        "url": item.url,
                    },
                    collector_metadata={
                        "integration": "trendradar",
                        **item.collector_metadata,
                    },
                    content_hash=_content_hash(item),
                )
            )
            if persisted.inserted:
                inserted += 1
            else:
                duplicates += 1
        return inserted, duplicates
