from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from infoscope.models import (
    EvidenceVisibility,
    NormalizationStatus,
    RawInformation,
    Signal,
    SourceVisibility,
)
from infoscope.pipeline import AcquisitionCursor, LogicalWindow


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_sha256(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("content_hash must be a lowercase SHA-256 hex digest")


@dataclass(frozen=True, slots=True)
class RawInformationInput:
    source_type: str
    source_key: str
    source_visibility: SourceVisibility
    acquired_at: datetime
    published_at: datetime | None
    content_text: str | None
    payload: dict[str, Any]
    provenance: dict[str, Any]
    collector_metadata: dict[str, Any]
    content_hash: str

    def __post_init__(self) -> None:
        if not self.source_type or not self.source_key:
            raise ValueError("source_type and source_key are required")
        _require_aware(self.acquired_at, "acquired_at")
        if self.published_at is not None:
            _require_aware(self.published_at, "published_at")
        _require_sha256(self.content_hash)


@dataclass(frozen=True, slots=True)
class SignalInput:
    signal_index: int
    normalized_text: str
    title: str | None
    published_at: datetime | None
    public_provenance: dict[str, Any] | None
    content_hash: str

    def __post_init__(self) -> None:
        if self.signal_index < 0:
            raise ValueError("signal_index must not be negative")
        if not self.normalized_text:
            raise ValueError("normalized_text is required")
        if self.published_at is not None:
            _require_aware(self.published_at, "published_at")
        _require_sha256(self.content_hash)


@dataclass(frozen=True, slots=True)
class PersistedRaw:
    raw: RawInformation
    inserted: bool


def public_signal_provenance(
    *,
    source_visibility: SourceVisibility,
    public_provenance: dict[str, Any] | None,
) -> tuple[EvidenceVisibility, dict[str, Any] | None]:
    """Apply the deterministic privacy boundary before Signal persistence."""
    if source_visibility is SourceVisibility.PRIVATE:
        return EvidenceVisibility.PRIVATE_SANITIZED, None
    return EvidenceVisibility.PUBLIC, public_provenance


class AcquisitionRepository:
    def __init__(self, database: AsyncSession) -> None:
        self.database = database

    async def persist_raw(self, value: RawInformationInput) -> PersistedRaw:
        """Persist Raw in its own transaction before downstream processing."""
        raw_id = uuid4()
        statement = (
            insert(RawInformation)
            .values(
                id=raw_id,
                source_type=value.source_type,
                source_key=value.source_key,
                source_visibility=value.source_visibility.value,
                acquired_at=value.acquired_at,
                published_at=value.published_at,
                content_text=value.content_text,
                payload=value.payload,
                provenance=value.provenance,
                collector_metadata=value.collector_metadata,
                content_hash=value.content_hash,
            )
            .on_conflict_do_nothing(
                index_elements=[RawInformation.source_type, RawInformation.source_key]
            )
            .returning(RawInformation)
        )
        result = await self.database.execute(statement)
        raw = result.scalar_one_or_none()
        inserted = raw is not None
        if raw is None:
            raw = (
                await self.database.execute(
                    select(RawInformation).where(
                        RawInformation.source_type == value.source_type,
                        RawInformation.source_key == value.source_key,
                    )
                )
            ).scalar_one()
        await self.database.commit()
        return PersistedRaw(raw=raw, inserted=inserted)

    async def list_raw_window(
        self,
        *,
        window: LogicalWindow,
        after: AcquisitionCursor | None = None,
        limit: int = 500,
    ) -> list[RawInformation]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        statement = select(RawInformation).where(
            RawInformation.acquired_at >= window.start,
            RawInformation.acquired_at < window.end,
        )
        if after is not None:
            statement = statement.where(
                tuple_(RawInformation.acquired_at, RawInformation.id)
                > tuple_(after.acquired_at, after.raw_id)
            )
        result = await self.database.execute(
            statement.order_by(RawInformation.acquired_at, RawInformation.id).limit(limit)
        )
        return list(result.scalars())

    async def mark_normalization_started(self, raw: RawInformation) -> None:
        if raw.normalization_status not in {
            NormalizationStatus.PENDING.value,
            NormalizationStatus.FAILED.value,
        }:
            raise ValueError("only pending or failed Raw can start normalization")
        raw.normalization_status = NormalizationStatus.PROCESSING.value
        raw.normalization_attempts += 1
        raw.last_error_code = None
        await self.database.commit()

    async def mark_normalization_failed(self, raw: RawInformation, *, error_code: str) -> None:
        if raw.normalization_status != NormalizationStatus.PROCESSING.value:
            raise ValueError("only processing Raw can fail normalization")
        if not error_code:
            raise ValueError("a stable error_code is required")
        raw.normalization_status = NormalizationStatus.FAILED.value
        raw.last_error_code = error_code
        raw.normalized_at = None
        await self.database.commit()

    async def persist_signal(
        self,
        *,
        raw: RawInformation,
        value: SignalInput,
        normalized_at: datetime,
    ) -> Signal:
        _require_aware(normalized_at, "normalized_at")
        if raw.normalization_status != NormalizationStatus.PROCESSING.value:
            raise ValueError("only processing Raw can produce Signals")
        visibility, provenance = public_signal_provenance(
            source_visibility=SourceVisibility(raw.source_visibility),
            public_provenance=value.public_provenance,
        )
        statement = (
            insert(Signal)
            .values(
                id=uuid4(),
                raw_information_id=raw.id,
                signal_index=value.signal_index,
                title=value.title,
                normalized_text=value.normalized_text,
                published_at=value.published_at,
                source_type=raw.source_type,
                evidence_visibility=visibility.value,
                public_provenance=provenance,
                content_hash=value.content_hash,
            )
            .on_conflict_do_nothing(index_elements=[Signal.raw_information_id, Signal.signal_index])
            .returning(Signal)
        )
        signal = (await self.database.execute(statement)).scalar_one_or_none()
        if signal is None:
            signal = (
                await self.database.execute(
                    select(Signal).where(
                        Signal.raw_information_id == raw.id,
                        Signal.signal_index == value.signal_index,
                    )
                )
            ).scalar_one()
        raw.normalization_status = NormalizationStatus.SUCCEEDED.value
        raw.last_error_code = None
        raw.normalized_at = normalized_at
        await self.database.commit()
        return signal


def cursor_for(raw: RawInformation) -> AcquisitionCursor:
    return AcquisitionCursor(acquired_at=raw.acquired_at, raw_id=raw.id)
