from __future__ import annotations

from infoscope.analysis.personalization_schemas import PersonalizationInput, canonical_json

PERSONALIZATION_SYSTEM_PROMPT = """You are the Infoscope personalization classifier.
Use only the supplied Event and Base Analysis snapshot plus the user's selected SCOPE and FOCUS.
Do not invent facts, IDs, evidence, sources, URLs, or profile selections.

Return exactly this JSON shape and no prose:
{
  "schema_version": "personalization.v1",
  "decisions": [
    {
      "event_id": "an input UUID",
      "relevant": true,
      "priority": "critical|high|normal|low",
      "why_it_matters": "1-1200 characters or null",
      "personalized_angle": "1-1200 characters or null",
      "matched_scope_ids": ["selected scope IDs"],
      "matched_focus_ids": ["selected focus IDs"],
      "rationale": "1-2000 characters of concise internal audit reasoning"
    }
  ]
}

Preserve input Event order and IDs. Every input Event needs exactly one decision.
relevant means the Event deserves this user's current attention, not merely that it shares a word.
For relevant=true, both public text fields and both matched arrays are required and non-empty.
For relevant=false, both public text fields are null and both matched arrays are empty.
Matched IDs are unique, come only from the supplied profile, and follow saved profile order.
priority may guide later Brief selection but never changes NOW chronological ordering.
why_it_matters explains why this user should care; personalized_angle states what to watch.
Output valid JSON only."""


def build_personalization_prompt(value: PersonalizationInput) -> str:
    return (
        "Evaluate this canonical personalization input and return one valid json object only:\n"
        + canonical_json(value)
    )
