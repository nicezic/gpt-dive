# GPT Dive Pydantic Providers

This page records **GPT Dive provider/model integration roles and adapter ownership**, not general provider product documentation or cross-Orchestra routing policy. Verify live model names/auth behavior before consequential changes.

## Current model aliases used by Dive work

| Alias | Provider path | Model family | Intended role |
|---|---|---|---|
| `aiapiflow-opus5` | AiApiFlow, Anthropic-compatible | `claude-opus-5` | selective premium reviewer / design challenge |
| `kunavo-opus5` | Kunavo, Anthropic-compatible | `claude-opus-5` | alternate premium reviewer route |
| `m3` | MiniMax Anthropic-compatible | MiniMax-M3 | high-quota evidence analyst/controller; prefer bounded tool-less review over autonomous multi-tool loops |
| `terra` | OpenAI Codex subscription | GPT-5.6 Terra | local subscription-backed judgment/review/worker candidate |
| `luna` | OpenAI Codex subscription | GPT-5.6 Luna | subscription-backed conductor/judgment candidate |

The alias layer hides provider URL/key/model-name details from Monty orchestration code. For paid peer review, routing metadata alone is insufficient: the configured authenticated provider `/v1/models` catalog must advertise the exact model ID before inference. That verification runs inside the credentialed `model_call_worker`: unknown ids fail fast with the provider's available list; unsupported/slow listings are skipped so verification never blocks a legitimate call.

## Adding an Anthropic-compatible provider

Provider connection info lives in one table, `PROVIDER_ROUTES` in `src/gpt_dive/model_registry.py`; alias members derive their route from it and exact-model callers read it directly.

1. Add one entry: `"name": ProviderRoute(credential_env="NAME_KEY", base_url="https://...")`.
2. Export the key through `creds` so only the spawned worker sees it.
3. Optional: add a `ModelAlias` member if the provider should serve alias lanes (`peer_review`/`subagent`); exact-model peer review needs no alias.
4. Probe `/v1/models` once to confirm the exact model id and record it here.

Removing or rotating a provider is the same table plus the credential store. Subscription transports (Codex) are separate and unaffected.

## Pydantic adapters

- AiApiFlow / MiniMax compatible paths use Pydantic's Anthropic-compatible provider/model interfaces where verified.
- GPT Dive consumes official stable `pydantic-ai-slim`; subscription-backed Codex aliases route through the local `gpt_dive.openai_codex` compatibility layer.
- `~/ref/pydantic-ai-pr-6433/` is now a slim behavioral/provenance pack only, not a Git checkout. The runtime Git source pin was removed on 2026-08-14.
- Maintenance seams, upgrade procedure, and retirement gate live in `~/gpt-dive/README.patch.openai.provider.md`.

## Credentials

Credential SSOT and scoped injection policy: `~/wiki/reference/security/credentials.md`.

For local AI calls prefer `creds run ai -- ...` so provider secrets are injected only into the child process that needs them. Do not expose secret values to Monty `CAPABILITIES`, model prompts, Wiki, logs, or diagnostics.

## Evidence

Provider compatibility probes/history remain under `~/labs/pydantic-ai-harness-course/playground/provider_compat/`; older Test Flight notes are retired under `~/wiki/pydantic/study/retired/test-flight/`. Live compatibility must be rechecked when provider or Pydantic versions change.
