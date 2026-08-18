from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from infoscope.analysis.config import AnalysisConfigurationError
from infoscope.config import Settings, get_settings
from infoscope.integrations.research.client import ResearchRuntimeError
from infoscope.integrations.research.runtime import research_capability_checker
from infoscope.schemas.research_capability import ResearchCapabilityResponse


class ResearchCapabilityService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def status(self) -> ResearchCapabilityResponse:
        try:
            await research_capability_checker(self.settings).check()
        except (AnalysisConfigurationError, ResearchRuntimeError):
            return ResearchCapabilityResponse(status="unavailable")
        return ResearchCapabilityResponse(status="ready")


def get_research_capability_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ResearchCapabilityService:
    return ResearchCapabilityService(settings)
