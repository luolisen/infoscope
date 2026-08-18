import json
from uuid import uuid4

import pytest

from infoscope.integrations.research.client import ResearchRuntimeError
from infoscope.integrations.research.grok import GrokBuildResearchClient
from infoscope.integrations.research.schemas import ResearchRequestPayload


def _payload() -> ResearchRequestPayload:
    event_id = uuid4()
    return ResearchRequestPayload.model_validate(
        {
            "request_id": uuid4(),
            "trigger": "ask_missing_fact",
            "source_event_ids": [event_id],
            "research_questions": ["What changed?"],
            "missing_fact_descriptions": [],
            "allowed_source_kinds": ["web_page"],
            "current_fact_snapshot": {
                "events": [{
                    "event_id": event_id,
                    "title": "Event",
                    "overview": "Overview",
                    "state": "developing",
                    "display_time": "2026-08-18T00:00:00Z",
                    "claims": [],
                    "timeline": [],
                    "conflicts": [],
                    "evidence_signals": [],
                }],
            },
        }
    )


def test_grok_stream_requires_completed_x_search_and_parses_public_candidate() -> None:
    payload = _payload()
    document = {
        "schema_version": "research_discovery.v1",
        "request_id": str(payload.request_id),
        "candidates": [{
            "source_kind": "web_page",
            "source_url": "https://x.com/githubstatus/status/2089647660680564850",
            "relevance_summary": "Official incident update.",
        }],
    }
    stream = "\n".join([
        json.dumps(
            {
                "type": "tool_call_update",
                "toolName": "X search:",
                "rawOutput": {"name": "x_keyword_search"},
            }
        ),
        json.dumps({"type": "text", "data": json.dumps(document)}),
        json.dumps({"type": "usage", "usage": {"input": 10, "output": 8, "total": 18}}),
    ]).encode()
    response = GrokBuildResearchClient._parse_stream(stream, payload)
    assert response.provider == "grok-build"
    assert response.payload.candidates[0].source_url.startswith("https://x.com/")


def test_grok_stream_fails_closed_without_x_tool() -> None:
    payload = _payload()
    stream = json.dumps({"type": "text", "data": "{}"}).encode()
    with pytest.raises(ResearchRuntimeError, match="GROK_SEARCH_TOOL_NOT_USED"):
        GrokBuildResearchClient._parse_stream(stream, payload)
