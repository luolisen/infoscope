from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

from infoscope.config import Settings


class AnalysisConfigurationError(ValueError):
    error_code = "ANALYSIS_CONFIGURATION_INVALID"


@dataclass(frozen=True, slots=True)
class AnalysisConfig:
    api_base_url: str
    model: str
    api_keys: tuple[str, ...] = field(repr=False)
    timeout_seconds: float
    max_retries: int
    max_tokens: int


def load_analysis_config(settings: Settings) -> AnalysisConfig:
    if settings.analysis_api_keys is None:
        raise AnalysisConfigurationError("ANALYSIS_API_KEYS is required")
    keys = tuple(
        value.strip()
        for value in settings.analysis_api_keys.get_secret_value().split(",")
        if value.strip()
    )
    if not keys:
        raise AnalysisConfigurationError("ANALYSIS_API_KEYS must contain at least one key")
    if len(keys) != len(set(keys)):
        raise AnalysisConfigurationError("ANALYSIS_API_KEYS contains duplicate keys")
    parsed = urlparse(settings.analysis_api_base_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise AnalysisConfigurationError("ANALYSIS_API_BASE_URL must be credential-free HTTPS")
    model = settings.analysis_model.strip()
    if not model:
        raise AnalysisConfigurationError("ANALYSIS_MODEL must not be empty")
    return AnalysisConfig(
        api_base_url=settings.analysis_api_base_url.rstrip("/"),
        model=model,
        api_keys=keys,
        timeout_seconds=settings.analysis_timeout_seconds,
        max_retries=settings.analysis_max_retries,
        max_tokens=settings.analysis_max_tokens,
    )
