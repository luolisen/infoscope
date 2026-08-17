import json
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest

from infoscope.analysis.client import AnalysisError
from infoscope.analysis.config import AnalysisConfig
from infoscope.analysis.reconstruction_client import DeepSeekEventReconstructionClient
from infoscope.analysis.reconstruction_schemas import ExistingEventCandidate
from infoscope.analysis.schemas import AnalysisSignal, WindowAnalysisPayload


def _config() -> AnalysisConfig:
    return AnalysisConfig("https://api.example.com", "model", ("first", "second"), 10, 1, 1024)


async def test_reconstruction_client_rotates_key_and_parses_strict_output() -> None:
    signal_id = uuid4()
    authorizations: list[str] = []
    requests: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        authorizations.append(request.headers["Authorization"])
        requests.append(json.loads(request.content))
        if len(authorizations) == 1:
            return httpx.Response(500, json={"error": {"message": "unavailable"}})
        return httpx.Response(
            200,
            json={
                "model": "deepseek-v4-flash",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "schema_version": "event_reconstruction_model.v2",
                                    "new_events": {
                                        "release-2": {
                                            "title": "Release 2",
                                            "overview": "A release occurred.",
                                            "state": "developing",
                                            "display_time": "2026-08-16T09:00:00Z",
                                            "rationale": "The evidence describes one release.",
                                        }
                                    },
                                    "existing_event_updates": {},
                                    "signal_assignments": {
                                        str(signal_id): "release-2"
                                    },
                                }
                            )
                        },
                    }
                ],
                "usage": {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12},
            },
        )

    signal = AnalysisSignal(
        signal_id=signal_id,
        title="Release 2",
        text="A release occurred.",
        published_at=datetime(2026, 8, 16, 9, tzinfo=UTC),
        source_type="web",
        evidence_visibility="public",
        public_provenance={"platform": "web"},
    )
    window = WindowAnalysisPayload(
        signal_analyses=[
            {"signal_id": signal_id, "categories": ["technology"], "fact_claims": []}
        ],
        clusters=[],
        unassigned_signal_ids=[signal_id],
    )
    candidate = ExistingEventCandidate(
        event_id=uuid4(),
        title="Existing",
        overview="Existing overview",
        state="developing",
        display_time=datetime(2026, 8, 16, 8, tzinfo=UTC),
        signal_ids=[uuid4()],
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        response = await DeepSeekEventReconstructionClient(
            client=transport,
            config=_config(),
        ).reconstruct(window_analysis=window, signals=[signal], candidates=[candidate])

    assert authorizations == ["Bearer first", "Bearer second"]
    assert response.payload.new_events[0].signal_ids == [signal_id]
    assert response.token_usage.total_tokens == 12
    prompt_document = json.loads(requests[-1]["messages"][1]["content"].split("\n", 1)[1])
    assert "signal_ids" not in prompt_document["candidate_events"][0]


async def test_reconstruction_retry_disables_thinking_and_adds_truncation_repair() -> None:
    signal_id = uuid4()
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return httpx.Response(
                200,
                request=request,
                json={
                    "choices": [
                        {"finish_reason": "length", "message": {"content": "{"}}
                    ]
                },
            )
        return httpx.Response(
            200,
            request=request,
            json={
                "model": "deepseek-v4-flash",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "schema_version": "event_reconstruction.v1",
                                    "new_events": [],
                                    "existing_event_updates": [],
                                    "unassigned_signal_ids": [str(signal_id)],
                                }
                            )
                        },
                    }
                ],
                "usage": {},
            },
        )

    signal = AnalysisSignal(
        signal_id=signal_id,
        title="Evidence",
        text="Evidence text.",
        published_at=None,
        source_type="web",
        evidence_visibility="public",
        public_provenance=None,
    )
    window = WindowAnalysisPayload(
        signal_analyses=[
            {"signal_id": signal_id, "categories": ["technology"], "fact_claims": []}
        ],
        clusters=[],
        unassigned_signal_ids=[signal_id],
    )
    config = AnalysisConfig(
        api_base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        api_keys=("first", "second"),
        timeout_seconds=10,
        max_retries=1,
        max_tokens=16_384,
        supports_deepseek_thinking=True,
        provider="deepseek",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        response = await DeepSeekEventReconstructionClient(
            client=transport, config=config
        ).reconstruct(window_analysis=window, signals=[signal], candidates=[])

    assert response.payload.unassigned_signal_ids == [signal_id]
    assert requests[0]["thinking"] == {"type": "disabled"}
    assert requests[1]["thinking"] == {"type": "disabled"}
    assert "previous response was truncated" not in requests[0]["messages"][1]["content"]
    assert "previous response was truncated" in requests[1]["messages"][1]["content"]
    assert requests[1]["messages"][1]["content"].count("Evidence text.") == 1


def test_candidate_contract_keeps_event_ids_backend_supplied() -> None:
    candidate = ExistingEventCandidate(
        event_id=uuid4(),
        title="Existing",
        overview="Existing overview",
        state="confirmed",
        display_time=datetime(2026, 8, 16, 8, tzinfo=UTC),
        signal_ids=[uuid4()],
    )

    assert candidate.event_id


def test_reconstruction_schema_repair_requires_a_signal_partition() -> None:
    instruction = DeepSeekEventReconstructionClient._repair_instruction(
        "ANALYSIS_SCHEMA_INVALID"
    )

    assert instruction is not None
    assert "event_reconstruction_model.v2" in instruction
    assert "JSON objects keyed by unique decision_key" in instruction


async def test_unknown_model_assignment_is_rejected() -> None:
    expected_signal_id, unknown_signal_id = uuid4(), uuid4()
    document = {
        "model": "deepseek-v4-flash",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": json.dumps(
                        {
                            "schema_version": "event_reconstruction_model.v2",
                            "new_events": {
                                "hallucinated": {
                                    "title": "Hallucinated",
                                    "overview": "Should not persist.",
                                    "state": "developing",
                                    "display_time": "2026-08-16T09:00:00Z",
                                    "rationale": "Unknown assignment only.",
                                }
                            },
                            "existing_event_updates": {},
                            "signal_assignments": {
                                str(unknown_signal_id): "hallucinated"
                            },
                        }
                    )
                },
            }
        ],
        "usage": {},
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
        trust_env=False,
    ) as transport:
        with pytest.raises(AnalysisError) as raised:
            DeepSeekEventReconstructionClient(
                client=transport, config=_config()
            )._parse_response(document, signal_ids=[expected_signal_id])

    assert raised.value.error_code == "ANALYSIS_SIGNAL_COVERAGE_INVALID"


async def test_assignment_to_unknown_decision_becomes_unassigned() -> None:
    signal_id = uuid4()
    document = {
        "model": "deepseek-v4-flash",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": json.dumps(
                        {
                            "schema_version": "event_reconstruction_model.v2",
                            "new_events": {},
                            "existing_event_updates": {},
                            "signal_assignments": {str(signal_id): "missing-decision"},
                        }
                    )
                },
            }
        ],
        "usage": {},
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
        trust_env=False,
    ) as transport:
        response = DeepSeekEventReconstructionClient(
            client=transport, config=_config()
        )._parse_response(document, signal_ids=[signal_id])

    assert response.payload.new_events == []
    assert response.payload.existing_event_updates == []
    assert response.payload.unassigned_signal_ids == [signal_id]


async def test_update_to_unknown_candidate_becomes_new_event() -> None:
    signal_id, unknown_event_id = uuid4(), uuid4()
    document = {
        "model": "deepseek-v4-flash",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": json.dumps(
                        {
                            "schema_version": "event_reconstruction_model.v2",
                            "new_events": {},
                            "existing_event_updates": {
                                "unknown-update": {
                                    "existing_event_id": str(unknown_event_id),
                                    "title": "Grounded event",
                                    "overview": "Grounded overview",
                                    "state": "developing",
                                    "display_time": "2026-08-16T09:00:00Z",
                                    "rationale": "Current evidence",
                                }
                            },
                            "signal_assignments": {
                                str(signal_id): "unknown-update"
                            },
                        }
                    )
                },
            }
        ],
        "usage": {},
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
        trust_env=False,
    ) as transport:
        response = DeepSeekEventReconstructionClient(
            client=transport, config=_config()
        )._parse_response(document, signal_ids=[signal_id], candidate_ids=set())

    assert response.payload.existing_event_updates == []
    assert response.payload.new_events[0].decision_key == "unknown-update"
    assert response.payload.new_events[0].signal_ids == [signal_id]
