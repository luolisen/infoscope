import json
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from infoscope.analysis.client import DeepSeekAnalysisClient
from infoscope.analysis.config import (
    AnalysisConfig,
    AnalysisConfigurationError,
    load_analysis_config,
)
from infoscope.analysis.schemas import (
    AnalysisSignal,
    WindowAnalysisModelPayload,
    WindowAnalysisPayload,
)
from infoscope.config import Settings
from infoscope.pipeline import LogicalWindow


def _payload(signal_id) -> dict:
    return {
        "schema_version": "window_analysis_model.v2",
        "signal_analyses": [
            {
                "signal_id": str(signal_id),
                "categories": ["technology"],
                "fact_claims": ["Fact"],
                "cluster_key": None,
            }
        ],
        "clusters": [],
    }


def _config(
    *,
    keys: tuple[str, ...] = ("first", "second"),
    supports_thinking: bool = True,
    max_retries: int = 1,
) -> AnalysisConfig:
    return AnalysisConfig(
        "https://api.example.com",
        "model",
        keys,
        10,
        max_retries,
        1024,
        supports_thinking,
    )


def _signal():
    return AnalysisSignal(
        signal_id=uuid4(),
        title=None,
        text="Evidence",
        published_at=datetime(2026, 8, 16, 9, tzinfo=UTC),
        source_type="telegram",
        evidence_visibility="private_sanitized",
        public_provenance=None,
    )


async def test_client_rotates_keys_on_retry_and_parses_json_output() -> None:
    signal = _signal()
    authorizations: list[str] = []
    thinking_modes: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        authorizations.append(request.headers["Authorization"])
        thinking_modes.append(json.loads(request.content)["thinking"]["type"])
        if len(authorizations) == 1:
            return httpx.Response(500, json={"error": {"message": "unavailable"}})
        return httpx.Response(
            200,
            json={
                "model": "deepseek-v4-flash",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(_payload(signal.signal_id))},
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                    "prompt_cache_hit_tokens": 3,
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        result = await DeepSeekAnalysisClient(client=transport, config=_config()).analyze(
            window=LogicalWindow.starting_at(datetime(2026, 8, 16, 9, tzinfo=UTC)),
            signals=[signal],
        )

    assert authorizations == ["Bearer first", "Bearer second"]
    assert thinking_modes == ["disabled", "disabled"]
    assert result.payload.unassigned_signal_ids == [signal.signal_id]
    assert result.token_usage.total_tokens == 15


async def test_client_tries_full_key_allowlist_when_retry_budget_is_zero() -> None:
    signal = _signal()
    authorizations: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        authorizations.append(request.headers["Authorization"])
        if len(authorizations) < 3:
            return httpx.Response(502, json={"error": {"message": "temporary"}})
        return httpx.Response(
            200,
            json={
                "model": "deepseek-v4-flash",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(_payload(signal.signal_id))},
                    }
                ],
                "usage": {},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        result = await DeepSeekAnalysisClient(
            client=transport,
            config=_config(keys=("first", "second", "third"), max_retries=0),
        ).analyze(
            window=LogicalWindow.starting_at(datetime(2026, 8, 16, 9, tzinfo=UTC)),
            signals=[signal],
        )

    assert result.payload.unassigned_signal_ids == [signal.signal_id]
    assert authorizations == ["Bearer first", "Bearer second", "Bearer third"]


async def test_schema_retry_adds_fixed_repair_instruction_without_old_output() -> None:
    signal = _signal()
    prompts: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        document = json.loads(request.content)
        prompts.append(document["messages"][1]["content"])
        payload = _payload(signal.signal_id)
        if len(prompts) == 1:
            payload["clusters"] = [
                {
                    "cluster_key": key,
                    "signal_ids": [str(signal.signal_id)],
                    "proposed_title": key,
                    "summary": key,
                    "relationships": [],
                    "missing_context": [],
                }
                for key in ("one", "two")
            ]
            payload["unassigned_signal_ids"] = []
        return httpx.Response(
            200,
            json={
                "model": "deepseek-v4-flash",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(payload)},
                    }
                ],
                "usage": {},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        result = await DeepSeekAnalysisClient(client=transport, config=_config()).analyze(
            window=LogicalWindow.starting_at(datetime(2026, 8, 16, 9, tzinfo=UTC)),
            signals=[signal],
        )

    assert result.payload.unassigned_signal_ids == [signal.signal_id]
    assert len(prompts) == 2
    assert "previous response" not in prompts[0].lower()
    assert "set exactly one cluster_key or null" in prompts[1].lower()
    assert "\"cluster_key\": \"one\"" not in prompts[1]


async def test_coverage_retry_requires_every_original_signal_id() -> None:
    signals = [_signal(), _signal()]
    prompts: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        prompts.append(json.loads(request.content)["messages"][1]["content"])
        included = signals[:1] if len(prompts) == 1 else signals
        payload = {
            "schema_version": "window_analysis_model.v2",
            "signal_analyses": [
                {
                    "signal_id": str(signal.signal_id),
                    "categories": [],
                    "fact_claims": [],
                    "cluster_key": None,
                }
                for signal in included
            ],
            "clusters": [],
        }
        return httpx.Response(
            200,
            json={
                "model": "deepseek-v4-flash",
                "choices": [
                    {"finish_reason": "stop", "message": {"content": json.dumps(payload)}}
                ],
                "usage": {},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        result = await DeepSeekAnalysisClient(client=transport, config=_config()).analyze(
            window=LogicalWindow.starting_at(datetime(2026, 8, 16, 9, tzinfo=UTC)),
            signals=signals,
        )

    assert len(result.payload.signal_analyses) == 2
    assert "one signal_analysis for every supplied signal_id" in prompts[1]


def test_analysis_config_keeps_keys_out_of_repr() -> None:
    config = load_analysis_config(
        Settings(
            _env_file=None,
            analysis_api_keys=SecretStr("one,two,three"),
            analysis_api_base_url="https://api.deepseek.com",
        )
    )

    assert config.api_keys == ("one", "two", "three")
    assert config.supports_deepseek_thinking is True
    assert config.provider == "deepseek"
    assert "one" not in repr(config)


def test_generic_openai_compatible_provider_omits_deepseek_thinking() -> None:
    config = load_analysis_config(
        Settings(
            _env_file=None,
            analysis_api_keys=SecretStr("one"),
            analysis_api_base_url="https://newapi.example.com",
            analysis_model="gpt-5.5",
        )
    )

    assert config.supports_deepseek_thinking is False
    assert config.provider == "openai_compatible"


@pytest.mark.parametrize(
    "settings",
    [
        Settings(_env_file=None),
        Settings(_env_file=None, analysis_api_keys=SecretStr("same,same")),
        Settings(
            _env_file=None,
            analysis_api_keys=SecretStr("one"),
            analysis_api_base_url="http://api.example.com",
        ),
    ],
)
def test_analysis_config_rejects_missing_duplicate_or_insecure_keys(settings: Settings) -> None:
    with pytest.raises(AnalysisConfigurationError):
        load_analysis_config(settings)


def test_payload_rejects_a_signal_assigned_twice() -> None:
    signal_id = uuid4()
    with pytest.raises(ValueError, match="multiple clusters"):
        WindowAnalysisPayload.model_validate(
            {
                "schema_version": "window_analysis.v1",
                "signal_analyses": [
                    {"signal_id": signal_id, "categories": [], "fact_claims": []}
                ],
                "clusters": [
                    {
                        "cluster_key": "one",
                        "signal_ids": [signal_id],
                        "proposed_title": "One",
                        "summary": "One",
                        "relationships": [],
                        "missing_context": [],
                    },
                    {
                        "cluster_key": "two",
                        "signal_ids": [signal_id],
                        "proposed_title": "Two",
                        "summary": "Two",
                        "relationships": [],
                        "missing_context": [],
                    },
                ],
                "unassigned_signal_ids": [],
            }
        )


def test_payload_rejects_relationship_outside_its_cluster() -> None:
    first = uuid4()
    second = uuid4()
    with pytest.raises(ValueError, match="relationship signals"):
        WindowAnalysisPayload.model_validate(
            {
                "schema_version": "window_analysis.v1",
                "signal_analyses": [
                    {"signal_id": first, "categories": [], "fact_claims": []},
                    {"signal_id": second, "categories": [], "fact_claims": []},
                ],
                "clusters": [
                    {
                        "cluster_key": "one",
                        "signal_ids": [first],
                        "proposed_title": "One",
                        "summary": "One",
                        "relationships": [
                            {
                                "relationship_type": "related",
                                "signal_ids": [first, second],
                                "explanation": "Second is not a member",
                            }
                        ],
                        "missing_context": [],
                    }
                ],
                "unassigned_signal_ids": [second],
            }
        )


def test_model_payload_drops_an_invalid_optional_relationship() -> None:
    first = uuid4()
    second = uuid4()
    model_payload = WindowAnalysisModelPayload.model_validate(
        {
            "schema_version": "window_analysis_model.v2",
            "signal_analyses": [
                {
                    "signal_id": first,
                    "categories": [],
                    "fact_claims": [],
                    "cluster_key": "one",
                },
                {
                    "signal_id": second,
                    "categories": [],
                    "fact_claims": [],
                    "cluster_key": "two",
                },
            ],
            "clusters": [
                {
                    "cluster_key": "one",
                    "proposed_title": "One",
                    "summary": "One",
                    "relationships": [
                        {
                            "relationship_type": "invalid-cross-cluster",
                            "signal_ids": [first, second],
                            "explanation": "Must not survive conversion",
                        }
                    ],
                    "missing_context": [],
                },
                {
                    "cluster_key": "two",
                    "proposed_title": "Two",
                    "summary": "Two",
                    "relationships": [],
                    "missing_context": [],
                },
            ],
        }
    )

    payload = model_payload.to_window_payload()

    assert payload.clusters[0].relationships == []
    assert payload.clusters[0].signal_ids == [first]
