from __future__ import annotations

from pydantic import SecretStr

from infoscope.analysis.config import load_analysis_config
from infoscope.config import Settings, get_settings
from infoscope.integrations.research.client import OpenClawConfig, OpenClawResearchClient
from infoscope.integrations.research.health import (
    AgentReachHealthChecker,
    ResearchCapabilityChecker,
)


def research_runtime_config(settings: Settings | None = None) -> OpenClawConfig:
    settings = settings or get_settings()
    credential = settings.research_deepseek_api_key
    if credential is None or not credential.get_secret_value().strip():
        analysis_config = load_analysis_config(settings)
        credential = SecretStr(analysis_config.api_keys[0])
    return OpenClawConfig(
        executable=settings.research_openclaw_executable,
        config_path=settings.resolved_research_openclaw_config_path,
        state_dir=settings.resolved_research_openclaw_state_dir,
        model=settings.research_openclaw_model,
        timeout_seconds=settings.research_timeout_seconds,
        credential_environment={"DEEPSEEK_API_KEY": credential},
    )


def research_capability_checker(
    settings: Settings | None = None,
) -> ResearchCapabilityChecker:
    settings = settings or get_settings()
    return ResearchCapabilityChecker(
        OpenClawResearchClient(research_runtime_config(settings)),
        AgentReachHealthChecker(
            settings.research_agent_reach_executable,
            state_dir=settings.resolved_research_openclaw_state_dir,
        ),
    )
