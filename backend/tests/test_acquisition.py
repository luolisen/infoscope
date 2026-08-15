from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from infoscope.models import (
    EvidenceVisibility,
    NormalizationStatus,
    RawInformation,
    Signal,
    SourceVisibility,
)
from infoscope.services.acquisition import (
    AcquisitionRepository,
    RawInformationInput,
    SignalInput,
    public_signal_provenance,
)


class FakeDatabase:
    def __init__(self, execute_result: object | None = None) -> None:
        self.added: list[object] = []
        self.commits = 0
        self.execute = AsyncMock(return_value=execute_result)

    def add(self, value: object) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        self.commits += 1


def test_private_provenance_is_removed_by_a_deterministic_boundary() -> None:
    visibility, provenance = public_signal_provenance(
        source_visibility=SourceVisibility.PRIVATE,
        public_provenance={
            "group_name": "secret-group",
            "username": "private-user",
            "invite_link": "https://example.invalid/invite",
            "internal_id": "123",
        },
    )

    assert visibility is EvidenceVisibility.PRIVATE_SANITIZED
    assert provenance is None


def test_public_provenance_is_preserved() -> None:
    public = {"publisher": "Example", "url": "https://example.com/item"}

    visibility, provenance = public_signal_provenance(
        source_visibility=SourceVisibility.PUBLIC,
        public_provenance=public,
    )

    assert visibility is EvidenceVisibility.PUBLIC
    assert provenance == public


def test_raw_input_requires_an_aware_acquisition_time_and_sha256() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        RawInformationInput(
            source_type="telegram",
            source_key="channel:1",
            source_visibility=SourceVisibility.PRIVATE,
            acquired_at=datetime(2026, 8, 16, 10),
            published_at=None,
            content_text="payload",
            payload={},
            provenance={},
            collector_metadata={},
            content_hash="a" * 64,
        )

    with pytest.raises(ValueError, match="SHA-256"):
        RawInformationInput(
            source_type="telegram",
            source_key="channel:1",
            source_visibility=SourceVisibility.PRIVATE,
            acquired_at=datetime(2026, 8, 16, 10, tzinfo=UTC),
            published_at=None,
            content_text="payload",
            payload={},
            provenance={},
            collector_metadata={},
            content_hash="not-a-hash",
        )


async def test_signal_persistence_sanitizes_private_provenance_and_completes_raw() -> None:
    raw = RawInformation(
        id=uuid4(),
        source_type="telegram",
        source_key="channel:1",
        source_visibility=SourceVisibility.PRIVATE.value,
        acquired_at=datetime(2026, 8, 16, 10, tzinfo=UTC),
        content_text="raw",
        payload={"body": "raw"},
        provenance={"group_name": "secret-group"},
        collector_metadata={"collector": "tg-news"},
        content_hash="a" * 64,
        normalization_status=NormalizationStatus.PROCESSING.value,
        normalization_attempts=1,
    )
    normalized_at = raw.acquired_at + timedelta(minutes=1)
    persisted_signal = Signal(
        id=uuid4(),
        raw_information_id=raw.id,
        signal_index=0,
        normalized_text="normalized",
        source_type="telegram",
        evidence_visibility=EvidenceVisibility.PRIVATE_SANITIZED.value,
        public_provenance=None,
        content_hash="b" * 64,
    )
    result = AsyncMock()
    result.scalar_one_or_none = lambda: persisted_signal
    database = FakeDatabase(result)
    repository = AcquisitionRepository(database)  # type: ignore[arg-type]

    signal = await repository.persist_signal(
        raw=raw,
        value=SignalInput(
            signal_index=0,
            normalized_text="normalized",
            title=None,
            published_at=None,
            public_provenance={"group_name": "must-not-leak"},
            content_hash="b" * 64,
        ),
        normalized_at=normalized_at,
    )

    assert signal.evidence_visibility == EvidenceVisibility.PRIVATE_SANITIZED.value
    assert signal.public_provenance is None
    assert raw.normalization_status == NormalizationStatus.SUCCEEDED.value
    assert raw.normalized_at == normalized_at
    assert signal is persisted_signal
    database.execute.assert_awaited_once()
    assert database.commits == 1
