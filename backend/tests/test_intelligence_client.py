import json
from uuid import uuid4

import httpx

from infoscope.analysis.ask_schemas import AskComparisonPayload
from infoscope.analysis.config import AnalysisConfig
from infoscope.analysis.intelligence_client import DeepSeekIntelligenceClient
from infoscope.analysis.intelligence_schemas import (
    BaseAnalysisClaimInput,
    BaseAnalysisConflictInput,
    BaseAnalysisPayload,
    BaseAnalysisTimelineInput,
    ClaimTimelineInput,
    ConflictClaimInput,
    ConflictEvidenceSignal,
    EventBaseAnalysisInput,
    EventClaimInput,
    EventConflictInput,
    EventTimelineInput,
    TimelineReconstructionPayload,
)
from infoscope.analysis.personalization_schemas import PersonalizationPayload
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


def test_personalization_repair_prompt_freezes_exact_decision_keys() -> None:
    instruction = DeepSeekIntelligenceClient._repair_instruction(
        "PERSONALIZATION_SCHEMA_INVALID",
        payload_type=PersonalizationPayload,
    )

    assert instruction is not None
    assert "why_it_matters" in instruction
    assert "trailing colon" in instruction
    assert "never omit a required key" in instruction


def test_ask_comparison_repair_prompt_rejects_invented_citation_fields() -> None:
    instruction = DeepSeekIntelligenceClient._repair_instruction(
        "ANALYSIS_SCHEMA_INVALID",
        payload_type=AskComparisonPayload,
    )

    assert instruction is not None
    assert "timeline_entry_ids" in instruction
    assert "Never output status, citations, cited_ids" in instruction


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
        {
            "schema_version": "conflict_analysis.v1",
            "new_conflicts": [
                {
                    "decision_key": "conflict",
                    "event_id": str(event_id),
                    "summary": "Contradiction",
                    "claim_ids": [str(claim_id)],
                    "evidence_signal_ids": [str(signal_id)],
                    "rationale": "Evidence differs",
                }
            ],
            "existing_conflict_updates": [],
            "unconflicted_claim_ids": [],
        },
        {
            "schema_version": "base_analysis.v1",
            "new_analyses": [
                {
                    "decision_key": "base",
                    "event_id": str(event_id),
                    "summary": "Current summary",
                    "event_type": "technology.release",
                    "importance": "high",
                    "topics": ["AI"],
                    "entities": [{"name": "Example Corp", "entity_type": "organization"}],
                    "rationale": "Persisted facts",
                }
            ],
            "existing_analysis_updates": [],
        },
    ]

    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
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
            events=[
                EventTimelineInput(
                    event_id=event_id,
                    title="Event",
                    overview="Overview",
                    state="developing",
                    display_time="2026-08-16T09:00:00Z",
                    claims=[
                        ClaimTimelineInput(
                            claim_id=claim_id,
                            event_id=event_id,
                            text="A fact",
                            state="unresolved",
                            evidence_signals=[
                                AnalysisSignal(
                                    signal_id=signal_id,
                                    title="Evidence",
                                    text="Text",
                                    published_at="2026-08-16T08:55:00Z",
                                    source_type="web",
                                    evidence_visibility="public",
                                    public_provenance={"platform": "web"},
                                )
                            ],
                        )
                    ],
                )
            ],
            candidates=[],
        )
        conflict_response = await client.analyze_conflicts(
            events=[
                EventConflictInput(
                    event_id=event_id,
                    title="Event",
                    overview="Overview",
                    state="developing",
                    claims=[
                        ConflictClaimInput(
                            claim_id=claim_id,
                            event_id=event_id,
                            text="A fact",
                            state="unresolved",
                            evidence_signals=[
                                ConflictEvidenceSignal(
                                    signal_id=signal_id,
                                    published_at=None,
                                    sanitized_text="Sanitized text",
                                    public_safe_provenance=None,
                                )
                            ],
                        )
                    ],
                )
            ],
            candidates=[],
        )
        base_response = await client.analyze_base(
            events=[
                EventBaseAnalysisInput(
                    event_id=event_id,
                    title="Event",
                    overview="Overview",
                    state="developing",
                    display_time="2026-08-16T09:00:00Z",
                    claims=[
                        BaseAnalysisClaimInput(
                            claim_id=claim_id,
                            text="A fact",
                            state="unresolved",
                            evidence_signal_ids=[signal_id],
                        )
                    ],
                    timeline=[
                        BaseAnalysisTimelineInput(
                            timeline_entry_id=uuid4(),
                            occurred_at="2026-08-16T08:50:00Z",
                            summary="Change",
                            claim_ids=[claim_id],
                        )
                    ],
                    conflicts=[
                        BaseAnalysisConflictInput(
                            conflict_id=uuid4(),
                            summary="Conflict",
                            claim_ids=[claim_id],
                            evidence_signal_ids=[signal_id],
                        )
                    ],
                    evidence_signals=[
                        ConflictEvidenceSignal(
                            signal_id=signal_id,
                            published_at=None,
                            sanitized_text="Sanitized text",
                            public_safe_provenance=None,
                        )
                    ],
                )
            ],
            candidates=[],
        )

    assert claim_response.payload.new_claims[0].event_id == event_id
    assert timeline_response.payload.new_entries[0].claim_ids == [claim_id]
    assert conflict_response.payload.new_conflicts[0].claim_ids == [claim_id]
    assert base_response.payload.new_analyses[0].importance == "high"
    assert all(
        request["messages"][2]["content"]
        == "Return exactly one valid json object and no prose."
        for request in requests
    )
    timeline_prompt = requests[1]["messages"][1]["content"]
    assert '"title":"Event"' in timeline_prompt
    assert '"text":"Text"' in timeline_prompt
    assert '"published_at":"2026-08-16T08:55:00Z"' in timeline_prompt
    assert '"public_provenance":{"platform":"web"}' in timeline_prompt
    conflict_prompt = requests[2]["messages"][1]["content"]
    assert '"published_at":null' in conflict_prompt
    assert '"sanitized_text":"Sanitized text"' in conflict_prompt
    assert '"occurred_at"' not in conflict_prompt
    base_prompt_document = json.loads(requests[3]["messages"][1]["content"].split("\n", 1)[1])
    evidence = base_prompt_document["events"][0]["evidence_signals"][0]
    assert evidence == {
        "public_safe_provenance": None,
        "published_at": None,
        "sanitized_text": "Sanitized text",
        "signal_id": str(signal_id),
    }


async def test_intelligence_retry_disables_thinking_and_adds_truncation_repair() -> None:
    event_id, signal_id = uuid4(), uuid4()
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
                                    "schema_version": "claim_extraction.v1",
                                    "new_claims": [],
                                    "existing_claim_updates": [],
                                    "unused_signal_ids": [str(signal_id)],
                                }
                            )
                        },
                    }
                ],
                "usage": {},
            },
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
    signal = AnalysisSignal(
        signal_id=signal_id,
        title="Evidence",
        text="Evidence text.",
        published_at=None,
        source_type="web",
        evidence_visibility="public",
        public_provenance=None,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        response = await DeepSeekIntelligenceClient(
            client=transport, config=config
        ).extract_claims(
            events=[
                EventClaimInput(
                    event_id=event_id,
                    title="Event",
                    overview="Overview",
                    signals=[signal],
                )
            ],
            candidates=[],
        )

    assert response.payload.unused_signal_ids == [signal_id]
    assert requests[0]["thinking"] == {"type": "disabled"}
    assert requests[1]["thinking"] == {"type": "disabled"}
    assert "previous response was truncated" not in requests[0]["messages"][1]["content"]
    assert "previous response was truncated" in requests[1]["messages"][1]["content"]
    assert requests[1]["messages"][1]["content"].count("Evidence text.") == 1


def test_base_analysis_schema_repair_forbids_generated_entity_ids() -> None:
    instruction = DeepSeekIntelligenceClient._repair_instruction(
        "ANALYSIS_SCHEMA_INVALID", payload_type=BaseAnalysisPayload
    )

    assert instruction is not None
    assert "exactly name and entity_type" in instruction
    assert "never emit entity_id" in instruction


def test_backend_generates_internal_decision_keys_and_drops_empty_timeline_entries() -> None:
    normalized = DeepSeekIntelligenceClient._normalize_internal_decisions(
        {
            "new_entries": [
                {"decision_key": "INVALID:VALUE", "claim_ids": []},
                {"decision_key": "also invalid", "claim_ids": [str(uuid4())]},
            ],
            "existing_entry_updates": [
                {"decision_key": "duplicate", "claim_ids": [str(uuid4())]}
            ],
            "unused_claim_ids": [],
        },
        payload_type=TimelineReconstructionPayload,
    )

    assert [item["decision_key"] for item in normalized["new_entries"]] == [
        "timeline-0000"
    ]
    assert [item["decision_key"] for item in normalized["existing_entry_updates"]] == [
        "timeline-0001"
    ]


def test_backend_normalizes_base_analysis_topics_and_entities() -> None:
    normalized = DeepSeekIntelligenceClient._normalize_internal_decisions(
        {
            "new_analyses": [
                {
                    "decision_key": "ignored",
                    "topics": [" AI ", "ai", *[f"topic-{index}" for index in range(20)]],
                    "entities": [
                        {
                            "name": f" Entity {index} ",
                            "entity_type": "organization",
                            "entity_id": f"forbidden-{index}",
                        }
                        for index in range(40)
                    ],
                }
            ],
            "existing_analysis_updates": [],
        },
        payload_type=BaseAnalysisPayload,
    )

    decision = normalized["new_analyses"][0]
    assert decision["decision_key"] == "base-0000"
    assert len(decision["topics"]) == 12
    assert decision["topics"][:2] == ["AI", "topic-0"]
    assert len(decision["entities"]) == 32
    assert decision["entities"][0] == {
        "name": "Entity 0",
        "entity_type": "organization",
    }
