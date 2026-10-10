# GPT Dive Pydantic Providers

This page records **GPT Dive provider/model integration roles and adapter ownership**, not general provider product documentation or cross-Orchestra routing policy. Verify live model names/auth behavior before consequential changes.

## Current model aliases used by Dive work

| Alias | Provider path | Model family | Intended role |
|---|---|---|---|
| `m3` | MiniMax Anthropic-compatible | MiniMax-M3 | high-quota evidence analyst/controller; prefer bounded tool-less review over autonomous multi-tool loops |
| `astra6` | OpenAI Codex subscription | `gpt-6-astra` | premium review / coding |
| `sol6` | OpenAI Codex subscription | `gpt-6.1-sol` | main high-performance review / coding |
| `terra5` | OpenAI Codex subscription | `gpt-5.6-terra` | balanced review / coding |
| `luna6` | OpenAI Codex subscription | `gpt-6-luna` | fast, low-cost review / coding |
| `opus-5-micu` | Micu, Anthropic-compatible | `claude-opus-5` | independent reviewer route |
| `muse-free` | `opencode-zen` | `muse-spark-1.3-contributor-free` | free OpenAI Responses route |

The alias layer hides provider URL/key/model-name details from Monty orchestration code. Anthropic-compatible exact-model routes may soft-check their authenticated `/v1/models` catalog before inference. OpenAI Codex authentication and transport are owned by Pydantic AI's official `openai-codex` provider.

## Adding an Anthropic-compatible provider

Provider connection info lives in one table, `PROVIDER_ROUTES` in `src/gpt_dive/model_registry.py`; alias members derive their route from it and exact-model callers read it directly.

1. Add one entry: `"name": ProviderRoute(credential_env="NAME_KEY", base_url="https://...")`.
2. Export the key through `creds` so only the spawned worker sees it.
3. Optional: add an entry in `MODEL_ALIASES` if the provider should serve alias lanes (`peer_review`/`subagent`); exact-model peer review needs no alias.
4. Probe `/v1/models` once to confirm the exact model id and record it here.

Removing or rotating a provider is the same table plus the credential store. Subscription transports (Codex) are separate and unaffected.

## Pydantic adapters

- Micu / MiniMax compatible paths use Pydantic's Anthropic-compatible provider/model interfaces where verified.
- Let upstream ModelProfile and request defaults handle model capabilities and token settings. Apply UsageLimits only when a caller explicitly supplies a token budget; peer review does not force max_tokens.
- OpenCode Go was removed after its subscription ended; OpenCode Zen retains the free muse-free alias. Its OPENCODE_GO_API_KEY env name is legacy; it still requires a valid Zen key, and free availability is not guaranteed.
- Do not send private repository contents to free/contributor models before reviewing their data-training and retention policy.
- GPT Dive consumes official stable `pydantic-ai-slim`; subscription-backed Codex aliases use Pydantic AI's official `OpenAICodexModel` / `OpenAICodexProvider`.

## Credentials

Credential SSOT and scoped injection policy: `~/wiki/reference/security/credentials.md`.

For local AI calls prefer `creds run ai -- ...` so provider secrets are injected only into the child process that needs them. Do not expose secret values to Monty `CAPABILITIES`, model prompts, Wiki, logs, or diagnostics.

## Evidence

Provider compatibility probes/history remain under `~/labs/pydantic-ai-harness-course/playground/provider_compat/`; older Test Flight notes are retired under `~/wiki/pydantic/study/retired/test-flight/`. Live compatibility must be rechecked when provider or Pydantic versions change.
