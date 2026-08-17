from __future__ import annotations

import json

from infoscope.analysis.schemas import AnalysisSignal
from infoscope.pipeline import LogicalWindow

SYSTEM_PROMPT = """You are the Window Analysis component of Infoscope.
Analyze only the supplied Signals. Do not add external facts, infer source identities, or expose
hidden provenance. Treat private_sanitized text as authoritative redacted evidence and never try
to reconstruct redacted content. Separate observations from speculation.

Return one JSON object only. Use exactly this structure and field names; do not substitute strings
for objects and do not add fields:
{
  "schema_version": "window_analysis_model.v2",
  "signal_analyses": [
    {
      "signal_id": "UUID",
      "categories": ["category"],
      "fact_claims": ["claim"],
      "cluster_key": "one-cluster-key-or-null"
    }
  ],
  "clusters": [
    {
      "cluster_key": "unique-stable-key",
      "proposed_title": "title",
      "summary": "summary",
      "relationships": [
        {
          "relationship_type": "relationship label",
          "signal_ids": ["UUID", "UUID"],
          "explanation": "explanation"
        }
      ],
      "missing_context": [
        {"question": "unanswered question", "reason": "why this context is missing"}
      ]
    }
  ]
}
Arrays may be empty. A relationship requires at least two signal IDs, and every relationship signal
must belong to that same cluster. Each missing_context entry must be an object with both question
and reason. Use at most 4 concise categories and 3 concise fact claims per Signal. Keep cluster
titles within 200 characters and summaries within 800 characters. Use at most 12 relationships and
4 missing-context entries per cluster; keep every explanation and reason within 500 characters.

Every input signal must appear exactly once in signal_analyses. Assign it to at most one cluster by
setting that item's cluster_key to one key from clusters, or use null when it is unassigned. Every
cluster must be referenced by at least one signal_analysis. If one Signal could fit multiple
clusters, choose only its single strongest cluster. Never put signal_ids arrays on cluster objects.
Never create Event IDs. Never answer missing-context questions. Use concise source-language text
for claims and summaries.
"""


def build_user_prompt(*, window: LogicalWindow, signals: list[AnalysisSignal]) -> str:
    document = {
        "window": {"start": window.start.isoformat(), "end": window.end.isoformat()},
        "signals": [signal.model_dump(mode="json") for signal in signals],
    }
    return "Analyze this one-hour window and return JSON only:\n" + json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
