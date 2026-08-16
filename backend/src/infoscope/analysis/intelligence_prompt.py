from __future__ import annotations

import json

from infoscope.analysis.intelligence_schemas import (
    EventClaimInput,
    EventConflictInput,
    EventTimelineInput,
    ExistingClaimCandidate,
    ExistingConflictCandidate,
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

TIMELINE_SYSTEM_PROMPT = """You reconstruct important Event evolution from supplied Events,
Claims, and their normalized Evidence Signals. Ground every Timeline entry in the supplied
Evidence text and timestamps. Do not list every publication timestamp and do not add external
facts. Claim IDs and Evidence Signals must belong to the containing Event. Existing updates may
reference only supplied Timeline IDs. Never create Timeline IDs. Return JSON only with
schema_version timeline_reconstruction.v1, new_entries, existing_entry_updates, and
unused_claim_ids. Each decision has decision_key, event_id, occurred_at as an offset-aware ISO
8601 time, summary, claim_ids, and rationale; updates also have existing_timeline_entry_id. The
union of used and unused Claim IDs must cover every input Claim. Rationale is internal analysis
and is never Evidence. Never infer or expose private source identities or hidden provenance."""

CONFLICT_SYSTEM_PROMPT = """You identify semantic conflicts from supplied Events, Claims, and
their restricted Evidence Signals. A conflict is either two or more mutually inconsistent Claims,
or one Claim contradicted by at least one of that Claim's supplied Evidence Signals. You decide
semantic contradiction from supplied sanitized text; do not add external facts. Evidence IDs must
be attached to at least one selected Claim. Existing updates may reference only supplied Conflict
IDs. Never create Conflict IDs and never decide Claim or Event state. Existing updates are
append-only assertions: omitted historical relations are not removed. Return JSON only with
schema_version conflict_analysis.v1, new_conflicts, existing_conflict_updates, and
unconflicted_claim_ids. Each decision has decision_key, event_id, summary, claim_ids,
evidence_signal_ids, and rationale; updates also have existing_conflict_id. Every input Claim must
appear in at least one decision or unconflicted_claim_ids. unconflicted means no new or updated
conflict in this run and never resolves a historical Conflict. Rationale is internal audit context,
not Evidence. Never infer timestamps, source identities, or hidden provenance."""


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
    events: list[EventTimelineInput], candidates: list[ExistingTimelineCandidate]
) -> str:
    return "Reconstruct Timeline entries from this input and return JSON only:\n" + json.dumps(
        {
            "events": [item.model_dump(mode="json") for item in events],
            "existing_timeline": [item.model_dump(mode="json") for item in candidates],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def build_conflict_prompt(
    events: list[EventConflictInput], candidates: list[ExistingConflictCandidate]
) -> str:
    return "Analyze Conflicts from this input and return JSON only:\n" + json.dumps(
        {
            "events": [item.model_dump(mode="json") for item in events],
            "existing_conflicts": [item.model_dump(mode="json") for item in candidates],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
