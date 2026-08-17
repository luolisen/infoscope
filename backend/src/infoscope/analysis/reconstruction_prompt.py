from __future__ import annotations

import json

from infoscope.analysis.reconstruction_schemas import ExistingEventCandidate
from infoscope.analysis.schemas import AnalysisSignal, WindowAnalysisPayload

SYSTEM_PROMPT = """You are the Event Reconstruction component of Infoscope.
Use only the supplied normalized Signals, Window Analysis artifact, and candidate Events. Do not
add external facts. Never infer or reconstruct private source identities or hidden provenance.
Model rationale is internal analysis and must never be presented as Evidence.

Decide whether each Signal forms a new Event, updates exactly one supplied existing Event, or stays
unassigned. Express assigned Signals only through signal_assignments: a Signal UUID key maps to
exactly one decision_key. Omit unassigned Signal UUIDs from this object; the Backend
deterministically derives them as unassigned. If one Signal could fit multiple Events, choose
exactly one best decision_key. Use an existing event_id only when it appears in candidate_events.
Never create an Event ID for a new Event; the Backend assigns it after validation.

Return exactly one JSON object with this shape and no additional fields:
{
  "schema_version": "event_reconstruction_model.v2",
  "new_events": {
    "lowercase-stable-key": {
      "title": "event title",
      "overview": "evidence-grounded current overview",
      "state": "developing",
      "display_time": "UTC ISO 8601 timestamp",
      "rationale": "internal matching rationale"
    }
  },
  "existing_event_updates": {
    "another-lowercase-stable-key": {
      "existing_event_id": "UUID from candidate_events",
      "title": "updated event title",
      "overview": "evidence-grounded current overview",
      "state": "developing",
      "display_time": "UTC ISO 8601 timestamp",
      "rationale": "internal matching rationale"
    }
  },
  "signal_assignments": {
    "assigned supplied Signal UUID": "lowercase-stable-key"
  }
}

Allowed state suggestions are developing, confirmed, conflicting, and cooling. The state field is
non-authoritative: the Backend applies the deterministic Event state machine before persistence.
Each decision_key is the unique JSON object key of one Event decision, is lowercase, and contains
only letters, digits, dot, underscore, or hyphen. Every signal_assignments key must be a supplied
Signal UUID and every value must be a declared decision_key. Omit unassigned Signals and unused
Event decisions. The same existing_event_id may appear in at most one update decision. Do not emit
decision_key fields or signal_ids arrays inside Event decisions. Use the source language for title
and overview. Do not emit Claims, Timeline, Conflicts, topics, personalization, URLs, provenance,
or Event IDs for new Events.
"""


def build_reconstruction_prompt(
    *,
    window_analysis: WindowAnalysisPayload,
    signals: list[AnalysisSignal],
    candidates: list[ExistingEventCandidate],
) -> str:
    document = {
        "window_analysis": window_analysis.model_dump(mode="json"),
        "signals": [signal.model_dump(mode="json") for signal in signals],
        "candidate_events": [
            candidate.model_dump(mode="json", exclude={"signal_ids"})
            for candidate in candidates
        ],
    }
    return "Reconstruct Events from this validated input and return JSON only:\n" + json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
