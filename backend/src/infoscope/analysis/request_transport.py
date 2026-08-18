from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Literal

import httpx

from infoscope.analysis.config import AnalysisConfig

TransientFailureKind = Literal["request", "rate_limited", "upstream_unavailable"]


class TransientRequestFailure(RuntimeError):
    def __init__(self, kind: TransientFailureKind) -> None:
        super().__init__(kind)
        self.kind = kind


async def post_with_key_failover(
    *,
    client: httpx.AsyncClient,
    config: AnalysisConfig,
    next_key: Callable[[], Awaitable[str]],
    payload: dict[str, Any],
) -> httpx.Response:
    """Try at least every fixed allowlisted key for transient transport failures."""
    attempts = max(config.max_retries + 1, len(config.api_keys))
    last_kind: TransientFailureKind = "request"
    last_exception: httpx.HTTPError | None = None
    for attempt in range(attempts):
        try:
            response = await client.post(
                f"{config.api_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {await next_key()}"},
                json=payload,
                timeout=config.timeout_seconds,
            )
        except httpx.HTTPError as error:
            last_kind = "request"
            last_exception = error
        else:
            if response.status_code == 429:
                last_kind = "rate_limited"
            elif response.status_code >= 500:
                last_kind = "upstream_unavailable"
            else:
                return response
        if attempt < attempts - 1:
            await asyncio.sleep(min(2**attempt, 8))
    if last_exception is not None:
        raise TransientRequestFailure(last_kind) from last_exception
    raise TransientRequestFailure(last_kind)
