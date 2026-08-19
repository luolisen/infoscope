from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

ModelSourceId = Literal["deepseek_official", "gpt_5_5", "ai_ping"]
ModelId = Literal[
    "deepseek-v4-flash",
    "deepseek-v4-pro",
    "gpt-5.5",
    "DeepSeek-V4-Flash-0731",
    "DeepSeek-V4-Pro",
    "Kimi-K3",
    "Qwen3.8-Max",
]


class ModelSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: ModelSourceId
    model_id: ModelId

    @model_validator(mode="after")
    def source_matches_model(self) -> "ModelSelection":
        allowed: dict[ModelSourceId, set[ModelId]] = {
            "deepseek_official": {"deepseek-v4-flash", "deepseek-v4-pro"},
            "gpt_5_5": {"gpt-5.5"},
            "ai_ping": {
                "DeepSeek-V4-Flash-0731",
                "DeepSeek-V4-Pro",
                "Kimi-K3",
                "Qwen3.8-Max",
            },
        }
        if self.model_id not in allowed[self.source_id]:
            raise ValueError("model_id does not belong to source_id")
        return self


class ModelOption(BaseModel):
    id: ModelId
    label: str
    available: bool


class ModelSourceOption(BaseModel):
    id: ModelSourceId
    label: str
    available: bool
    models: list[ModelOption]


class ModelSettingsResponse(BaseModel):
    selection: ModelSelection
    sources: list[ModelSourceOption]
