---
title: GPT Dive Pydantic Providers
created: 2026-08-10
updated: 2026-08-16
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

`m3_evidence(question, evidence, ...)` is the narrow default M3 research seam. Its long-context prompt places the evidence packet before the exact question/task, following MiniMax's M-series guidance for source-grounded long-context work. It delegates to the existing tool-less `bare(model="m3")` worker, requires a validated `known / missing / conflicts / queries / done` JSON contract, and caps proposed follow-up queries. The caller/Harness owns actual GBrain/Probe execution and may run independent proposed queries in parallel. This keeps M3 useful for high-volume evidence synthesis without relying on long sequential tool-result propagation. When the caller labels packet items as `[E1]`, `[E2]`, etc., `known` and `conflicts` must cite real packet labels; uncited claims or invented labels fail validation, preserving provenance across batched retrieval. The stopping contract is scoped to the exact question: once every explicitly requested aspect is supported, M3 must stop instead of promoting optional implementation details into new research requirements. The validator backs that contract mechanically: proposed queries must be non-empty and distinct, and `done=true` is valid only when both `queries` and `missing` are empty, so a structurally valid but self-contradictory completion cannot silently stop retrieval. Output parsing accepts either a bare JSON object or one exact `json`/plain Markdown code fence around that object; prose outside the object remains invalid, while common harmless model formatting does not discard an otherwise valid result. If M3 returns malformed or contract-invalid structured output, the controller retries exactly once and then fails closed; transport/provider failures are returned immediately. Retry usage is accumulated across both attempts.

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
