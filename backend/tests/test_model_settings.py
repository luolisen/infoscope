import os
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import delete

from infoscope.analysis.config import AnalysisConfigurationError
from infoscope.api.app import app
from infoscope.api.dependencies import get_ready_user
from infoscope.config import Settings
from infoscope.db import session_factory
from infoscope.models import User, UserModelPreference
from infoscope.schemas.model_settings import ModelSelection, ModelSettingsResponse
from infoscope.services.model_settings import (
    ModelSettingsService,
    analysis_config_for_selection,
    get_model_settings_service,
)


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        analysis_api_base_url="https://api.deepseek.com",
        analysis_api_keys=SecretStr("deepseek-one,deepseek-two"),
        dragon_api_base_url="https://dragon.example.com/v1",
        dragon_api_keys=SecretStr("dragon-one"),
        aiping_api_base_url="https://aiping.example.com/api/v1",
        aiping_api_keys_group_1=SecretStr("aiping-one"),
        aiping_api_keys_group_2=SecretStr("aiping-two"),
    )


def _ready_user() -> User:
    return User(
        id=uuid4(),
        username="alan",
        username_normalized="alan",
        password_hash="unused",
        onboarding_completed=True,
        scope_ids=["ai"],
        investment_market_ids=[],
        focus_ids=["major_changes"],
    )


def test_fixed_catalog_maps_each_model_to_isolated_server_credentials() -> None:
    settings = _settings()
    gpt = analysis_config_for_selection(
        settings,
        ModelSelection(source_id="gpt_5_5", model_id="gpt-5.5"),
    )
    kimi = analysis_config_for_selection(
        settings,
        ModelSelection(source_id="ai_ping", model_id="Kimi-K3"),
    )
    qwen = analysis_config_for_selection(
        settings,
        ModelSelection(source_id="ai_ping", model_id="Qwen3.8-Max"),
    )

    assert (gpt.provider, gpt.api_keys) == ("dragon", ("dragon-one",))
    assert (kimi.provider, kimi.api_keys) == ("ai_ping", ("aiping-one",))
    assert (qwen.provider, qwen.api_keys) == ("ai_ping", ("aiping-two",))
    assert "dragon-one" not in repr(gpt)


def test_invalid_source_model_pair_is_rejected() -> None:
    with pytest.raises(ValidationError, match="does not belong"):
        ModelSelection(source_id="gpt_5_5", model_id="Kimi-K3")


def test_unconfigured_provider_fails_closed() -> None:
    with pytest.raises(AnalysisConfigurationError):
        analysis_config_for_selection(
            Settings(_env_file=None),
            ModelSelection(source_id="gpt_5_5", model_id="gpt-5.5"),
        )


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.environ.get("INFOSCOPE_POSTGRES_INTEGRATION") != "1",
    reason="requires the local PostgreSQL integration database",
)
async def test_model_preference_upsert_preserves_created_at_and_advances_updated_at() -> None:
    user = _ready_user()
    service_settings = _settings()
    initial_selection = ModelSelection(
        source_id="deepseek_official",
        model_id="deepseek-v4-flash",
    )
    updated_selection = ModelSelection(source_id="gpt_5_5", model_id="gpt-5.5")

    try:
        async with session_factory() as database:
            database.add(user)
            await database.commit()

            service = ModelSettingsService(database, service_settings)
            await service.update(user.id, initial_selection)
            preference = await database.get(UserModelPreference, user.id)
            assert preference is not None
            created_at = preference.created_at
            initial_updated_at = preference.updated_at

            await service.update(user.id, updated_selection)
            await database.refresh(preference)

            assert preference.created_at == created_at
            assert preference.updated_at > initial_updated_at
            assert preference.source_id == updated_selection.source_id
            assert preference.model_id == updated_selection.model_id
    finally:
        async with session_factory() as database:
            await database.execute(delete(User).where(User.id == user.id))
            await database.commit()


class FakeModelSettingsService:
    def __init__(self, response: ModelSettingsResponse) -> None:
        self.response = response
        self.updated: ModelSelection | None = None

    async def get(self, _user_id):
        return self.response

    async def update(self, _user_id, selection):
        self.updated = selection
        return self.response.model_copy(update={"selection": selection})


@pytest.mark.asyncio
async def test_model_settings_api_exposes_catalog_without_credentials() -> None:
    user = _ready_user()

    class EmptyDatabase:
        async def get(self, _model, _key):
            return None

    response = await ModelSettingsService(  # type: ignore[arg-type]
        EmptyDatabase(),
        _settings(),
    ).get(user.id)
    service = FakeModelSettingsService(response)
    app.dependency_overrides[get_ready_user] = lambda: user
    app.dependency_overrides[get_model_settings_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            fetched = await client.get("/api/v1/settings/models")
            updated = await client.put(
                "/api/v1/settings/models",
                json={"source_id": "ai_ping", "model_id": "Qwen3.8-Max"},
            )
    finally:
        app.dependency_overrides.clear()

    assert fetched.status_code == 200
    document = fetched.json()
    assert [item["label"] for item in document["sources"]] == [
        "Deepseek官方",
        "GPT-5.5",
        "AI Ping",
    ]
    assert "key" not in fetched.text.casefold()
    assert "base_url" not in fetched.text.casefold()
    assert updated.status_code == 200
    assert updated.json()["selection"] == {
        "source_id": "ai_ping",
        "model_id": "Qwen3.8-Max",
    }
