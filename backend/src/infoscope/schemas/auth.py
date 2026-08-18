from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class SessionState(StrEnum):
    ANONYMOUS = "anonymous"
    ONBOARDING_REQUIRED = "onboarding_required"
    READY = "ready"


class SessionUser(BaseModel):
    display_name: str


class SessionResponse(BaseModel):
    state: SessionState
    user: SessionUser | None


class LocalAccessRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=64)

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("display_name must not be blank")
        return stripped
