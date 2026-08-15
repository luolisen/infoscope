from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class SessionState(StrEnum):
    ANONYMOUS = "anonymous"
    ONBOARDING_REQUIRED = "onboarding_required"
    READY = "ready"


class SessionUser(BaseModel):
    username: str


class SessionResponse(BaseModel):
    state: SessionState
    user: SessionUser | None


class CredentialsRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize_username_input(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("username must not be blank")
        return stripped
