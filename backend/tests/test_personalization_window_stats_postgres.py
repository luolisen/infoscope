import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from infoscope.db import session_factory
from infoscope.models import PipelineRun, RawInformation, Signal
from infoscope.services.personalization import PersonalizationRepository

pytestmark = pytest.mark.skipif(
    os.environ.get("INFOSCOPE_POSTGRES_INTEGRATION") != "1",
    reason="requires the local PostgreSQL integration database",
)


@pytest.mark.asyncio(loop_scope="module")
async def test_window_stats_count_raws_and_only_canonical_signals() -> None:
    start = datetime(2099, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=1)
    async with session_factory() as database:
        run = PipelineRun(
            pipeline_name="window_analysis",
            status="succeeded",
            window_start=start,
            window_end=end,
            attempt=1,
            started_at=start,
            finished_at=end,
        )
        raw = RawInformation(
            source_type="test",
            source_key=f"window-stats-{uuid4()}",
            source_visibility="public",
            acquired_at=start + timedelta(minutes=1),
            published_at=start,
            content_text="Test information",
            payload={},
            provenance={},
            collector_metadata={},
            content_hash="a" * 64,
            normalization_status="succeeded",
        )
        database.add_all([run, raw])
        await database.flush()
        canonical = Signal(
            raw_information_id=raw.id,
            signal_index=0,
            title="Canonical",
            normalized_text="Canonical factor",
            published_at=start,
            source_type="test",
            evidence_visibility="public",
            public_provenance={},
            content_hash="b" * 64,
        )
        database.add(canonical)
        await database.flush()
        database.add(
            Signal(
                raw_information_id=raw.id,
                signal_index=1,
                title="Duplicate",
                normalized_text="Duplicate factor",
                published_at=start,
                source_type="test",
                evidence_visibility="public",
                public_provenance={},
                content_hash="b" * 64,
                duplicate_of_signal_id=canonical.id,
            )
        )
        await database.flush()

        assert await PersonalizationRepository(database).window_stats() == (
            start,
            end,
            1,
            1,
        )
        await database.rollback()
