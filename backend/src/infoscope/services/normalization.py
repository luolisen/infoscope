from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from infoscope.models import RawInformation, SourceVisibility
from infoscope.services.acquisition import AcquisitionRepository, SignalInput


class NormalizationError(ValueError):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


@dataclass(frozen=True, slots=True)
class NormalizationResult:
    processed: int
    succeeded: int
    failed: int


def _clean_text(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n")
    return normalized.strip()


def _string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _allowlist(source: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: source[key] for key in keys if source.get(key) is not None}


PRIVATE_SOURCE_REDACTION = "[PRIVATE_SOURCE_REDACTED]"
_TELEGRAM_INVITE = re.compile(
    r"(?i)(?:https?://)?(?:t|telegram)\.me/(?:joinchat/|\+)[A-Za-z0-9_-]+"
)


def _replace_identity(text: str, identity: str | None) -> str:
    if identity is None or len(identity) < 3:
        return text
    return re.sub(re.escape(identity), PRIVATE_SOURCE_REDACTION, text, flags=re.IGNORECASE)


def _sanitize_private_telegram(text: str, provenance: dict[str, Any]) -> str:
    sanitized = _TELEGRAM_INVITE.sub(PRIVATE_SOURCE_REDACTION, text)
    title = _string(provenance.get("chat_title"))
    username = _string(provenance.get("chat_username"))
    sanitized = _replace_identity(sanitized, title)
    if username is not None:
        sanitized = _replace_identity(sanitized, f"@{username.lstrip('@')}")
        sanitized = _replace_identity(sanitized, f"t.me/{username.lstrip('@')}")
    peer_id = provenance.get("peer_id")
    if isinstance(peer_id, int) and len(str(abs(peer_id))) >= 8:
        sanitized = _replace_identity(sanitized, str(peer_id))
    return sanitized


class DeterministicNormalizer:
    """Map collector-specific Raw records to one source-neutral Signal without AI."""

    def normalize(self, raw: RawInformation) -> SignalInput:
        if raw.source_type not in {"telegram", "trend_radar"}:
            raise NormalizationError("NORMALIZE_UNSUPPORTED_SOURCE")
        if raw.content_text is None:
            raise NormalizationError("NORMALIZE_EMPTY_CONTENT")
        normalized_text = _clean_text(raw.content_text)
        if not normalized_text:
            raise NormalizationError("NORMALIZE_EMPTY_CONTENT")

        if raw.source_type == "telegram":
            title = None
            if raw.source_visibility == SourceVisibility.PRIVATE.value:
                normalized_text = _sanitize_private_telegram(
                    normalized_text,
                    raw.provenance,
                )
                public_provenance = None
            else:
                public_provenance = _allowlist(
                    raw.provenance,
                    ("platform", "chat_title", "chat_username", "url"),
                )
        else:
            title = self._trendradar_title(raw)
            public_provenance = _allowlist(
                raw.provenance,
                ("source_kind", "source_name", "url"),
            )

        return SignalInput(
            signal_index=0,
            normalized_text=normalized_text,
            title=title[:512] if title is not None else None,
            published_at=raw.published_at,
            public_provenance=public_provenance or None,
            content_hash=hashlib.sha256(normalized_text.encode("utf-8")).hexdigest(),
        )

    @staticmethod
    def _trendradar_title(raw: RawInformation) -> str | None:
        direct = _string(raw.payload.get("title"))
        if direct is not None:
            return _clean_text(direct)
        entry = raw.payload.get("entry")
        if isinstance(entry, dict):
            nested = _string(entry.get("title"))
            if nested is not None:
                return _clean_text(nested)
        return None


class NormalizationRunner:
    def __init__(
        self,
        *,
        repository: AcquisitionRepository,
        normalizer: DeterministicNormalizer | None = None,
    ) -> None:
        self.repository = repository
        self.normalizer = normalizer or DeterministicNormalizer()

    async def run_once(
        self,
        *,
        retry_failed: bool = False,
        limit: int = 500,
    ) -> NormalizationResult:
        raws = await self.repository.list_raw_for_normalization(
            retry_failed=retry_failed,
            limit=limit,
        )
        succeeded = 0
        failed = 0
        for raw in raws:
            await self.repository.mark_normalization_started(raw)
            try:
                signal = self.normalizer.normalize(raw)
            except NormalizationError as error:
                await self.repository.mark_normalization_failed(
                    raw,
                    error_code=error.error_code,
                )
                failed += 1
                continue
            await self.repository.persist_signal(
                raw=raw,
                value=signal,
                normalized_at=datetime.now(UTC),
            )
            succeeded += 1
        return NormalizationResult(
            processed=len(raws),
            succeeded=succeeded,
            failed=failed,
        )
