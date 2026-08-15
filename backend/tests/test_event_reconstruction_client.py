import json
from datetime import UTC, datetime
from uuid import uuid4

import httpx

from infoscope.analysis.config import AnalysisConfig
from infoscope.analysis.reconstruction_client import DeepSeekEventReconstructionClient
from infoscope.analysis.reconstruction_schemas import ExistingEventCandidate
from infoscope.analysis.schemas import AnalysisSignal, WindowAnalysisPayload


def _config() -> AnalysisConfig:
    return AnalysisConfig("https://api.example.com", "model", ("first", "second"), 10, 1, 1024)


async def test_reconstruction_client_rotates_key_and_parses_strict_output() -> None:
    signal_id = uuid4()
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
                        "message": {
                            "content": json.dumps(
                                {
                                    "schema_version": "event_reconstruction.v1",
                                    "new_events": [
                                        {
                                            "decision_key": "release-2",
                                            "signal_ids": [str(signal_id)],
                                            "title": "Release 2",
                                            "overview": "A release occurred.",
                                            "state": "developing",
                                            "display_time": "2026-08-16T09:00:00Z",
                                            "rationale": "The evidence describes one release.",
                                        }
                                    ],
                                    "existing_event_updates": [],
                                    "unassigned_signal_ids": [],
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
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        response = await DeepSeekEventReconstructionClient(
            client=transport,
            config=_config(),
        ).reconstruct(window_analysis=window, signals=[signal], candidates=[])

    assert authorizations == ["Bearer first", "Bearer second"]
    assert response.payload.new_events[0].signal_ids == [signal_id]
    assert response.token_usage.total_tokens == 12


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
