# Model comparison — 2026-08-17

This report records sanitized runtime metrics only. It contains no API keys, endpoint URLs,
Raw Information, private provenance, account data, or model response bodies.

## Full pipeline baseline

DeepSeek official `deepseek-v4-flash` completed the 1,967-record fact-layer run:

- 1,967 normalized Signals
- 489 Events
- 1,935 Claims
- 1,167 Timeline entries
- 8 Conflicts
- 489 Base Analyses
- 40/40 non-empty batches completed through Event Reconstruction, Claims, Timeline,
  Conflicts, and Base Analysis
- 879,322 Window Analysis tokens across the 40 model-backed batch artifacts

An earlier fixed 50-Signal observation showed that `deepseek-v4-pro` passed the strict schema
on its first response but split the batch into 44 Events. That observation was not persisted as
a canonical artifact, so it is treated as qualitative evidence rather than a durable metric.

## Fixed 50-Signal capacity check

Input artifact: `037e969d-2933-4d3e-be79-df85f720e1b5`.

| Target | Result | Elapsed | Stable error |
| --- | --- | ---: | --- |
| Dragon GPT-5.5 | Failed | 510.755 s | `ANALYSIS_UPSTREAM_UNAVAILABLE` |
| AI Ping Kimi-K3 | Failed | 671.684 s | `ANALYSIS_REQUEST_FAILED` |
| AI Ping Qwen3.8-Max | Failed | 1238.119 s | `ANALYSIS_REQUEST_FAILED` |

One response during this run omitted the required top-level schema fields and entered the fixed
repair retry. The remaining failures were upstream/request failures, so the result does not prove
repeated schema non-compliance. A smaller fixed batch was used to separate model behavior from
provider capacity and timeout behavior.

## Fixed 12-Signal comparison

Input artifact: `af972309-8f63-4ae1-afb4-9a3c430222ea`. All successful responses covered the
same 12 Signal IDs under the strict `window_analysis_model.v2` contract.

| Model/channel | Result | Elapsed | Clusters | Unassigned | Tokens |
| --- | --- | ---: | ---: | ---: | ---: |
| DeepSeek official Flash | Persisted baseline | Not captured | 5 | 1 | 5,568 |
| Dragon GPT-5.5 | Success | 106.138 s | 8 | 2 | 7,366 |
| AI Ping Kimi-K3 | Success | 116.596 s | 3 | 4 | 7,083 |
| AI Ping Qwen3.8-Max | Failed | 985.516 s | — | — | — |

Repeated GPT/Kimi runs also succeeded (GPT: 317.408 s / 6,776 tokens; Kimi: 258.082 s /
5,996 tokens), confirming contract compatibility while showing high channel latency variance.

### Output character

- Flash produced five event-sized themes and left only one item unassigned. Its grouping was the
  most balanced for shared fact-layer reconstruction.
- GPT-5.5 produced eight clusters, six of them singletons. Titles were precise, but the result was
  over-fragmented for Event Reconstruction and used the most tokens.
- Kimi-K3 produced three broader multi-item themes and conservatively left four unrelated items
  unassigned. It is a reasonable synthesis/personalization candidate, but its Window grouping is
  coarser than Flash.
- Qwen3.8-Max did not return a usable response through the configured AI Ping channel in either
  the 50- or 12-Signal run. No output-quality conclusion is made.

## Recommendation

Keep DeepSeek official Flash as the deployment-level default for Window Analysis and the shared
fact layer. It is the only model validated across all 1,967 records and had the best balance of
coverage, Event-sized grouping, and token use in the durable fixed-input baseline.

Expose GPT-5.5 and AI Ping models as user-selectable options for Personalization, Brief, and Ask.
Kimi-K3 is the strongest alternative observed for broad synthesis. GPT-5.5 is useful when precise,
fine-grained decomposition is desired. Treat Qwen3.8-Max as configured but temporarily unavailable
until its channel can complete the strict contract reliably.

## Personalization and Brief validation

Both user-scoped providers completed a canonical 100-Event Personalization snapshot after the
runtime was changed to ordered 10-Event batches with concurrency 2. The Backend combined and
validated all decisions before writing one immutable artifact; no partial artifact was exposed.

| Channel | Events | Relevant | Personalization tokens | Brief items | Brief tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| Dragon GPT-5.5 | 100 | 71 | 59,094 | 8 | 11,179 |
| AI Ping Kimi-K3 | 100 | 94 | 83,054 | 8 | 8,905 |

The users have different Profile breadth, so relevant counts are not a direct quality score.
GPT-5.5 completed all ten Personalization batches without schema repair after NewAPI compatibility
was fixed. Kimi-K3 completed the same strict contract but needed substantially more output repairs
and had much higher tail latency and completion-token use.

NewAPI rejects `response_format=json_object` when no lowercase `json` token is present in the
request messages. The Intelligence adapter now sends an explicit fixed user-role json instruction
for every strict request. Personalization also names json in its canonical user prompt.

Ask validation confirmed the same model difference. Kimi initially invented `status`, `citations`,
and `cited_ids` fields and omitted required ID arrays. A payload-specific repair prompt that freezes
all exact Ask Comparison keys produced a valid answerable artifact on the next response. Direct
Finalization then completed without another model call.
