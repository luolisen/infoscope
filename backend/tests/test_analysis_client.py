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
from infoscope.analysis.schemas import AnalysisSignal, WindowAnalysisPayload
from infoscope.config import Settings
from infoscope.pipeline import LogicalWindow


def _payload(signal_id) -> dict:
    return {
        "schema_version": "window_analysis.v1",
        "signal_analyses": [
            {"signal_id": str(signal_id), "categories": ["technology"], "fact_claims": ["Fact"]}
        ],
        "clusters": [],
        "unassigned_signal_ids": [str(signal_id)],
    }


def _config(*, keys: tuple[str, ...] = ("first", "second")) -> AnalysisConfig:
    return AnalysisConfig("https://api.example.com", "model", keys, 10, 1, 1024)


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

    async def handler(request: httpx.Request) -> httpx.Response:
        authorizations.append(request.headers["Authorization"])
        if len(authorizations) == 1:
            return httpx.Response(500, json={"error": {"message": "unavailable"}})
        return httpx.Response(
            200,
            json={
                "model": "deepseek-v4-pro",
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
    assert result.payload.unassigned_signal_ids == [signal.signal_id]
    assert result.token_usage.total_tokens == 15


def test_analysis_config_keeps_keys_out_of_repr() -> None:
    config = load_analysis_config(
        Settings(
            _env_file=None,
            analysis_api_keys=SecretStr("one,two,three"),
            analysis_api_base_url="https://api.deepseek.com",
        )
    )

    assert config.api_keys == ("one", "two", "three")
    assert "one" not in repr(config)


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
