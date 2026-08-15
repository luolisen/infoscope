from __future__ import annotations

import json

from infoscope.analysis.reconstruction_schemas import ExistingEventCandidate
from infoscope.analysis.schemas import AnalysisSignal, WindowAnalysisPayload

SYSTEM_PROMPT = """You are the Event Reconstruction component of Infoscope.
Use only the supplied normalized Signals, Window Analysis artifact, and candidate Events. Do not
add external facts. Never infer or reconstruct private source identities or hidden provenance.
Model rationale is internal analysis and must never be presented as Evidence.

Decide whether each Signal forms a new Event, updates exactly one supplied existing Event, or stays
unassigned. A Signal may belong to only one decision in this reconstruction run. Use an existing
event_id only when it appears in candidate_events. Never create an Event ID for a new Event; the
Backend assigns it after validation.

Return exactly one JSON object with this shape and no additional fields:
{
  "schema_version": "event_reconstruction.v1",
  "new_events": [
    {
      "decision_key": "lowercase-stable-key",
      "signal_ids": ["UUID"],
      "title": "event title",
      "overview": "evidence-grounded current overview",
      "state": "developing",
      "display_time": "UTC ISO 8601 timestamp",
      "rationale": "internal matching rationale"
    }
  ],
  "existing_event_updates": [
    {
      "decision_key": "lowercase-stable-key",
      "existing_event_id": "UUID from candidate_events",
      "signal_ids": ["UUID"],
      "title": "updated event title",
      "overview": "evidence-grounded current overview",
      "state": "developing",
      "display_time": "UTC ISO 8601 timestamp",
      "rationale": "internal matching rationale"
    }
  ],
  "unassigned_signal_ids": ["UUID"]
}

Allowed state suggestions are developing, confirmed, conflicting, and cooling. The state field is
non-authoritative: the Backend applies the deterministic Event state machine before persistence.
decision_key must be unique, lowercase, and contain only letters, digits, dot, underscore, or
hyphen. Every supplied Signal ID must appear exactly once across new_events,
existing_event_updates, or unassigned_signal_ids. Use the source language for title and overview.
Do not emit Claims, Timeline, Conflicts, topics, personalization, URLs, provenance, or Event IDs
for new Events.
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
        "candidate_events": [candidate.model_dump(mode="json") for candidate in candidates],
    }
    return "Reconstruct Events from this validated input and return JSON only:\n" + json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
