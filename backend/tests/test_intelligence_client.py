import json
from uuid import uuid4

import httpx

from infoscope.analysis.config import AnalysisConfig
from infoscope.analysis.intelligence_client import DeepSeekIntelligenceClient
from infoscope.analysis.intelligence_schemas import ClaimTimelineInput, EventClaimInput
from infoscope.analysis.schemas import AnalysisSignal


def _config() -> AnalysisConfig:
    return AnalysisConfig(
        api_base_url="https://example.test",
        model="test-model",
        api_keys=("secret",),
        timeout_seconds=1,
        max_retries=0,
        max_tokens=1000,
    )


async def test_intelligence_client_parses_claim_and_timeline_contracts() -> None:
    event_id, signal_id, claim_id = uuid4(), uuid4(), uuid4()
    responses = [
        {
            "schema_version": "claim_extraction.v1",
            "new_claims": [
                {
                    "decision_key": "claim",
                    "event_id": str(event_id),
                    "text": "A fact",
                    "evidence_signal_ids": [str(signal_id)],
                    "rationale": "Evidence",
                }
            ],
            "existing_claim_updates": [],
            "unused_signal_ids": [],
        },
        {
            "schema_version": "timeline_reconstruction.v1",
            "new_entries": [
                {
                    "decision_key": "entry",
                    "event_id": str(event_id),
                    "occurred_at": "2026-08-16T09:00:00Z",
                    "summary": "A change",
                    "claim_ids": [str(claim_id)],
                    "rationale": "Evolution",
                }
            ],
            "existing_entry_updates": [],
            "unused_claim_ids": [],
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        payload = responses.pop(0)
        return httpx.Response(
            200,
            request=request,
            json={
                "model": "test-model",
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(payload)}}],
                "usage": {"total_tokens": 12},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        client = DeepSeekIntelligenceClient(client=transport, config=_config())
        claim_response = await client.extract_claims(
            events=[
                EventClaimInput(
                    event_id=event_id,
                    title="Event",
                    overview="Overview",
                    signals=[
                        AnalysisSignal(
                            signal_id=signal_id,
                            title="Evidence",
                            text="Text",
                            published_at=None,
                            source_type="web",
                            evidence_visibility="public",
                            public_provenance=None,
                        )
                    ],
                )
            ],
            candidates=[],
        )
        timeline_response = await client.reconstruct_timeline(
            claims=[
                ClaimTimelineInput(
                    claim_id=claim_id,
                    event_id=event_id,
                    text="A fact",
                    state="unresolved",
                    evidence_signal_ids=[signal_id],
                )
            ],
            candidates=[],
        )

    assert claim_response.payload.new_claims[0].event_id == event_id
    assert timeline_response.payload.new_entries[0].claim_ids == [claim_id]
