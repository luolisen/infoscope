from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated
from urllib.parse import urlparse
from uuid import UUID

from fastapi import Depends, status
from pydantic import SecretStr
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from infoscope.analysis.config import (
    AnalysisConfig,
    AnalysisConfigurationError,
    build_analysis_config,
)
from infoscope.config import Settings, get_settings
from infoscope.db import get_session
from infoscope.errors import ApiError
from infoscope.models import UserModelPreference
from infoscope.schemas.model_settings import (
    ModelId,
    ModelOption,
    ModelSelection,
    ModelSettingsResponse,
    ModelSourceId,
    ModelSourceOption,
)


@dataclass(frozen=True, slots=True)
class _ModelDefinition:
    source_id: ModelSourceId
    source_label: str
    model_id: ModelId
    model_label: str
    key_group: int


MODEL_DEFINITIONS = (
    _ModelDefinition("deepseek_official", "Deepseek官方", "deepseek-v4-pro", "Pro", 0),
    _ModelDefinition("deepseek_official", "Deepseek官方", "deepseek-v4-flash", "Flash", 0),
    _ModelDefinition("gpt_5_5", "GPT-5.5", "gpt-5.5", "GPT-5.5", 0),
    _ModelDefinition(
        "ai_ping",
        "AI Ping",
        "DeepSeek-V4-Flash-0731",
        "DeepSeek V4 Flash 0731",
        1,
    ),
    _ModelDefinition("ai_ping", "AI Ping", "Kimi-K3", "Kimi K3", 1),
    _ModelDefinition("ai_ping", "AI Ping", "Qwen3.8-Max", "Qwen 3.8 Max", 2),
)
_DEFINITIONS_BY_SELECTION = {
    (item.source_id, item.model_id): item for item in MODEL_DEFINITIONS
}


def _credentials(
    settings: Settings,
    definition: _ModelDefinition,
) -> tuple[str | None, SecretStr | None, str]:
    if definition.source_id == "deepseek_official":
        return settings.analysis_api_base_url, settings.analysis_api_keys, "deepseek"
    if definition.source_id == "gpt_5_5":
        return settings.dragon_api_base_url, settings.dragon_api_keys, "dragon"
    keys = (
        settings.aiping_api_keys_group_1
        if definition.key_group == 1
        else settings.aiping_api_keys_group_2
    )
    return settings.aiping_api_base_url, keys, "ai_ping"


def analysis_config_for_selection(
    settings: Settings,
    selection: ModelSelection,
) -> AnalysisConfig:
    definition = _DEFINITIONS_BY_SELECTION.get((selection.source_id, selection.model_id))
    if definition is None:
        raise AnalysisConfigurationError("unsupported model selection")
    api_base_url, keys, provider = _credentials(settings, definition)
    return build_analysis_config(
        api_base_url=api_base_url,
        model=definition.model_id,
        api_keys=keys,
        timeout_seconds=settings.analysis_timeout_seconds,
        max_retries=settings.analysis_max_retries,
        max_tokens=min(settings.analysis_max_tokens, settings.user_analysis_max_tokens),
        provider=provider,
    )


def default_model_selection(settings: Settings) -> ModelSelection:
    hostname = urlparse(settings.analysis_api_base_url).hostname or ""
    if hostname.endswith("deepseek.com") and (
        "deepseek_official",
        settings.analysis_model,
    ) in _DEFINITIONS_BY_SELECTION:
        return ModelSelection(
            source_id="deepseek_official",
            model_id=settings.analysis_model,  # type: ignore[arg-type]
        )
    return ModelSelection(source_id="deepseek_official", model_id="deepseek-v4-flash")


async def selected_model_for_user(
    database: AsyncSession,
    user_id: UUID,
    settings: Settings,
) -> ModelSelection:
    preference = await database.get(UserModelPreference, user_id)
    if preference is None:
        return default_model_selection(settings)
    return ModelSelection(source_id=preference.source_id, model_id=preference.model_id)


async def analysis_config_for_user(
    database: AsyncSession,
    user_id: UUID,
    settings: Settings,
) -> AnalysisConfig:
    return analysis_config_for_selection(
        settings,
        await selected_model_for_user(database, user_id, settings),
    )


class ModelSettingsService:
    def __init__(self, database: AsyncSession, settings: Settings) -> None:
        self.database = database
        self.settings = settings

    async def get(self, user_id: UUID) -> ModelSettingsResponse:
        return self._response(await selected_model_for_user(self.database, user_id, self.settings))

    async def update(
        self,
        user_id: UUID,
        selection: ModelSelection,
    ) -> ModelSettingsResponse:
        try:
            analysis_config_for_selection(self.settings, selection)
        except AnalysisConfigurationError as error:
            raise ApiError(
                status_code=status.HTTP_409_CONFLICT,
                code="MODEL_SELECTION_UNAVAILABLE",
                message="The selected model is not configured on this server.",
            ) from error
        await self.database.execute(
            insert(UserModelPreference)
            .values(
                user_id=user_id,
                source_id=selection.source_id,
                model_id=selection.model_id,
            )
            .on_conflict_do_update(
                index_elements=[UserModelPreference.user_id],
                set_={
                    "source_id": selection.source_id,
                    "model_id": selection.model_id,
                    "updated_at": func.now(),
                },
            )
        )
        await self.database.commit()
        return self._response(selection)

    def _response(self, selection: ModelSelection) -> ModelSettingsResponse:
        sources: list[ModelSourceOption] = []
        for source_id in ("deepseek_official", "gpt_5_5", "ai_ping"):
            definitions = [item for item in MODEL_DEFINITIONS if item.source_id == source_id]
            models = [
                ModelOption(
                    id=item.model_id,
                    label=item.model_label,
                    available=self._available(item),
                )
                for item in definitions
            ]
            sources.append(
                ModelSourceOption(
                    id=source_id,
                    label=definitions[0].source_label,
                    available=any(model.available for model in models),
                    models=models,
                )
            )
        return ModelSettingsResponse(selection=selection, sources=sources)

    def _available(self, definition: _ModelDefinition) -> bool:
        try:
            analysis_config_for_selection(
                self.settings,
                ModelSelection(source_id=definition.source_id, model_id=definition.model_id),
            )
        except AnalysisConfigurationError:
            return False
        return True


def get_model_settings_service(
    database: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ModelSettingsService:
    return ModelSettingsService(database, settings)
