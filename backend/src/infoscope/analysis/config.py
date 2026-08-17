from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

from pydantic import SecretStr

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
    supports_deepseek_thinking: bool = False
    provider: str = "openai_compatible"


def load_analysis_config(settings: Settings) -> AnalysisConfig:
    return build_analysis_config(
        api_base_url=settings.analysis_api_base_url,
        model=settings.analysis_model,
        api_keys=settings.analysis_api_keys,
        timeout_seconds=settings.analysis_timeout_seconds,
        max_retries=settings.analysis_max_retries,
        max_tokens=settings.analysis_max_tokens,
        provider=None,
    )


def build_analysis_config(
    *,
    api_base_url: str | None,
    model: str,
    api_keys: SecretStr | None,
    timeout_seconds: float,
    max_retries: int,
    max_tokens: int,
    provider: str | None,
) -> AnalysisConfig:
    if api_keys is None:
        raise AnalysisConfigurationError("analysis API keys are required")
    get_secret_value = getattr(api_keys, "get_secret_value", None)
    raw_keys = get_secret_value() if callable(get_secret_value) else str(api_keys)
    keys = tuple(
        value.strip()
        for value in raw_keys.split(",")
        if value.strip()
    )
    if not keys:
        raise AnalysisConfigurationError("ANALYSIS_API_KEYS must contain at least one key")
    if len(keys) != len(set(keys)):
        raise AnalysisConfigurationError("ANALYSIS_API_KEYS contains duplicate keys")
    parsed = urlparse(api_base_url or "")
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise AnalysisConfigurationError("ANALYSIS_API_BASE_URL must be credential-free HTTPS")
    model = model.strip()
    if not model:
        raise AnalysisConfigurationError("ANALYSIS_MODEL must not be empty")
    supports_deepseek_thinking = parsed.hostname.endswith("deepseek.com")
    return AnalysisConfig(
        api_base_url=(api_base_url or "").rstrip("/"),
        model=model,
        api_keys=keys,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        max_tokens=max_tokens,
        supports_deepseek_thinking=supports_deepseek_thinking,
        provider=provider or ("deepseek" if supports_deepseek_thinking else "openai_compatible"),
    )
