from typing import Literal

from pydantic import BaseModel


class ResearchCapabilityResponse(BaseModel):
    status: Literal["ready", "unavailable"]
