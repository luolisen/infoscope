from __future__ import annotations

import json

from infoscope.analysis.intelligence_schemas import (
    ClaimTimelineInput,
    EventClaimInput,
    ExistingClaimCandidate,
    ExistingTimelineCandidate,
)

CLAIM_SYSTEM_PROMPT = """You extract independently verifiable Claims from supplied Events and
their normalized Signals. Use no external facts. A Signal may support multiple Claims. Evidence
IDs must be supplied Signal IDs belonging to the same Event. Existing updates may reference only
provided Claim IDs. Never create Claim IDs and never decide Claim state. Return JSON only with
schema_version claim_extraction.v1, new_claims, existing_claim_updates, and unused_signal_ids.
Each decision has decision_key, event_id, text, evidence_signal_ids, and rationale; updates also
have existing_claim_id. The union of used and unused Signal IDs must cover every input Signal.
Rationale is internal analysis and is never Evidence. Do not expose or infer private provenance."""

TIMELINE_SYSTEM_PROMPT = """You reconstruct important Event evolution from supplied Claims and
existing Timeline candidates. Do not list every publication timestamp. Use no external facts.
Claim IDs must belong to the same Event. Existing updates may reference only supplied Timeline
IDs. Never create Timeline IDs. Return JSON only with schema_version timeline_reconstruction.v1,
new_entries, existing_entry_updates, and unused_claim_ids. Each decision has decision_key,
event_id, occurred_at as an offset-aware ISO 8601 time, summary, claim_ids, and rationale; updates
also have existing_timeline_entry_id. The union of used and unused Claim IDs must cover every
input Claim. Rationale is internal analysis and is never Evidence."""


def build_claim_prompt(
    events: list[EventClaimInput], candidates: list[ExistingClaimCandidate]
) -> str:
    return "Extract Claims from this input and return JSON only:\n" + json.dumps(
        {
            "events": [item.model_dump(mode="json") for item in events],
            "existing_claims": [item.model_dump(mode="json") for item in candidates],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def build_timeline_prompt(
    claims: list[ClaimTimelineInput], candidates: list[ExistingTimelineCandidate]
) -> str:
    return "Reconstruct Timeline entries from this input and return JSON only:\n" + json.dumps(
        {
            "claims": [item.model_dump(mode="json") for item in claims],
            "existing_timeline": [item.model_dump(mode="json") for item in candidates],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
