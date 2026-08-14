---
title: GPT Dive Pydantic Providers
created: 2026-08-10
updated: 2026-08-10
type: reference
status: trusted
---

# GPT Dive Pydantic Providers

This page records **GPT Dive provider/model integration roles and adapter ownership**, not general provider product documentation or cross-Orchestra routing policy. Verify live model names/auth behavior before consequential changes.

## Current model aliases used by Dive work

| Alias | Provider path | Model family | Intended role |
|---|---|---|---|
| `opus5` | AIAPIFLOW, Anthropic-compatible | Claude Opus 5 | selective premium reviewer / design challenge |
| `m3` | MiniMax Anthropic-compatible | MiniMax-M3 | available high-quota subagent; reliability evidence means do not assume default-worker suitability |
| `terra` | OpenAI Codex subscription | GPT-5.6 Terra | local subscription-backed judgment/review/worker candidate |
| `luna` | OpenAI Codex subscription | GPT-5.6 Luna | subscription-backed conductor/judgment candidate |

The alias layer should hide provider URL/key/model-name details from Monty orchestration code.

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
