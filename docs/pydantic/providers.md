---
title: GPT Dive Pydantic Providers
created: 2026-08-10
updated: 2026-08-17
type: reference
status: trusted
---

# GPT Dive Pydantic Providers

This page records **GPT Dive provider/model integration roles and adapter ownership**, not general provider product documentation or cross-Orchestra routing policy. Verify live model names/auth behavior before consequential changes.

## Current model aliases used by Dive work

| Alias | Provider path | Model family | Intended role |
|---|---|---|---|
| `opus5` | AIAPIFLOW, Anthropic-compatible | Claude Opus 5 | selective premium reviewer / design challenge |
| `m3` | MiniMax Anthropic-compatible | MiniMax-M3 | high-quota evidence analyst/controller; prefer bounded tool-less review over autonomous multi-tool loops |
| `terra` | OpenAI Codex subscription | GPT-5.6 Terra | local subscription-backed judgment/review/worker candidate |
| `luna` | OpenAI Codex subscription | GPT-5.6 Luna | subscription-backed conductor/judgment candidate |

The alias layer should hide provider URL/key/model-name details from Monty orchestration code.

`m3_evidence(question, evidence, ...)` is the narrow default M3 research seam. Its long-context prompt places the evidence packet before the exact question/task and wraps source material in one escaped `<source_data>...</source_data>` boundary, following MiniMax's M-series guidance to index/delimit long-context sources before the task. Retrieved source content is explicitly treated as data rather than controller instructions. It delegates to the underlying tool-less `invoke_bare(model="m3", peer_review=False)` worker path, requires a validated `known / missing / conflicts / queries / done` JSON contract, and caps proposed follow-up queries. The caller/Harness owns actual GBrain/Probe execution and may run independent proposed queries in parallel. This keeps M3 useful for high-volume evidence synthesis without relying on long sequential tool-result propagation. When the caller labels packet items as `[E1]`, `[E2]`, etc., item-label definitions must be unique and `known` / `conflicts` must cite real packet labels; duplicate item labels, uncited claims, or invented labels fail validation, preserving unambiguous provenance across batched retrieval. The stopping contract is scoped to the exact question: once every explicitly requested aspect is supported, M3 must stop instead of promoting optional implementation details into new research requirements. For explicit current/latest questions, conflicting evidence with explicit dates is resolved toward the newest applicable dated source while preserving the older/newer disagreement in `conflicts`; this follows MiniMax's long-context guidance and prevents a newer dated source from triggering a redundant retrieval round. Research depth is also mechanically bounded: `max_rounds` defaults to 3, `round_number` cannot exceed it, and the final round may report unresolved `missing` evidence but must return no further `queries`. The validator backs the contract mechanically: proposed queries must be non-empty and distinct, and `done=true` is valid only when both `queries` and `missing` are empty, so a structurally valid but self-contradictory completion cannot silently stop retrieval. Output parsing accepts either a bare JSON object or one exact `json`/plain Markdown code fence around that object; prose outside the object remains invalid, while common harmless model formatting does not discard an otherwise valid result. If M3 returns malformed or contract-invalid structured output, the controller retries exactly once and then fails closed; transport/provider failures are returned immediately. Retry usage is accumulated across both attempts.

A fixed live regression set lives at `tests/fixtures/m3_evidence_eval.json`. Run `uv run python -m gpt_dive.m3_evidence_eval` before prompt/controller changes: it executes 11 representative and edge cases against real M3 and reports pass rate, retry cases, query counts, and per-case latency. One case explicitly requires three independent facts to survive as three `known` items, guarding against silent list-item loss in otherwise valid structured output. Cases may also require case-insensitive semantic substrings in `known`, `missing`, `conflicts`, or `queries`, so well-formed structured output that silently drops or changes a key fact can fail the gate instead of passing on shape/count alone. Use `--repeat N` to run the same fixed set sequentially multiple times; the report then adds sample count, per-case pass/retry rates, `flaky_cases` for cases that both pass and fail across runs, and `run_stats` (per-run pass/fail/retry/mean-latency) so serving-window-wide degradation is visible separately from one flaky case. Sequential repetition is deliberate: it measures controller/model stability without adding concurrent-request ordering as another variable. Treat this as a regression gate, not a benchmark of general M3 intelligence.

For real-user coverage, `uv run python -m gpt_dive.m3_gbrain_replay --against <capture.ndjson>` consumes query rows from `gbrain eval export` and materializes the exact captured `retrieved_chunk_ids` from GBrain's read-only engine, preserving captured order and source scope. It labels those chunks as `[E1..En]` and sends them through `m3_evidence`. This deliberately avoids both `gbrain query` re-execution and whole-page expansion: replay cannot feed synthetic retrieval calls back into `eval_candidates`, and M3 does not receive evidence that was outside the original captured retrieval result. Current exact-chunk capture is required; older exports without `retrieved_chunk_ids` fail closed instead of silently widening to full pages. This runner measures controller behavior on real captured questions (`done`, unresolved evidence, retries, proposed follow-up queries, controller failures); it is not an answer-accuracy benchmark because capture rows do not contain answer gold. GBrain's own `eval replay` remains authoritative for retrieval-regression scoring.

## Pydantic adapters

- AIAPIFLOW / MiniMax compatible paths use Pydantic's Anthropic-compatible provider/model interfaces where verified.
- GPT Dive consumes official stable `pydantic-ai-slim`; subscription-backed Codex aliases route through the local `gpt_dive.openai_codex` compatibility layer.
- `~/ref/pydantic-ai-pr-6433/` is now a slim behavioral/provenance pack only, not a Git checkout. The runtime Git source pin was removed on 2026-08-14.
- Maintenance seams, upgrade procedure, and retirement gate live in `~/gpt-dive/README.patch.openai.provider.md`.

## Credentials

Credential SSOT and scoped injection policy: `~/wiki/reference/security/credentials.md`.

For local AI calls prefer `creds run ai -- ...` so provider secrets are injected only into the child process that needs them. Do not expose secret values to Monty `CAPABILITIES`, model prompts, Wiki, logs, or diagnostics.

## Evidence

Provider compatibility probes/history remain under `~/labs/pydantic-ai-harness-course/playground/provider_compat/`; older Test Flight notes are retired under `~/wiki/pydantic/study/retired/test-flight/`. Live compatibility must be rechecked when provider or Pydantic versions change.
