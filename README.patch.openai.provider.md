# OpenAI Codex Provider Compatibility Patch

This document is the maintenance SSOT for GPT Dive's local compatibility layer for subscription-backed OpenAI Codex execution.

## Why this exists

GPT Dive uses ChatGPT subscription-backed Codex models for the `sol`, `terra`, and `luna` aliases. Pydantic AI PR #6433 implemented the required OAuth, credential rotation, provider transport, and Responses API compatibility, but keeping GPT Dive pinned to that feature branch froze the rest of Pydantic AI near an older base.

GPT Dive therefore consumes official Pydantic AI and owns only the Codex-specific compatibility behavior locally. The official package is never patched in-place.

```text
GPT Dive
  |
  +-- official pydantic-ai-slim 2.30.0
  |     +-- Agent / Responses model / provider base APIs
  |
  +-- gpt_dive.openai_codex
        +-- auth.py / _oauth.py / _store.py
        +-- provider.py
        +-- model.py
```

## Reference implementation

Behavioral/reference source:

- Pydantic AI PR #6433, `feat/codex-subscription-auth`
- reference commit: `af055625bf67217a5839d6255900475d9576aa13`
- the auth/OAuth/store modules were adapted from that commit because token rotation, account consistency, locking, and secret handling are security-sensitive behavior that should not be casually re-invented
- PR #6433 is a behavioral reference, not a frozen implementation template

Current official base at this compatibility revision:

- `pydantic-ai-slim==2.30.0`
- upstream reference commit observed for v2.30.0: `c24a9008a`
- Python 3.14
- `pydantic-ai-harness==0.18.1`, which requires `pydantic-ai-slim>=2.23.0`

## Local modules and responsibility

### `auth.py`

Owns the request-time credential lifecycle: load, validity checks, concurrency-safe refresh, account continuity, and clear login-required errors. The default credential store remains `~/.pydantic-ai/auth.json`.

### `_oauth.py`

Owns OpenAI OAuth protocol behavior needed for browser/device login, refresh, and revoke. This is intentionally close to PR #6433. GPT Dive replaced Pydantic-private utility imports with Python/AnyIO/public Pydantic APIs but did not redesign the protocol.

### `_store.py`

Owns the permission-hardened file store and cross-process rotation lock. GPT Dive replaced Pydantic AI's private `run_in_executor` helper with `anyio.to_thread.run_sync`; the file format and compare-and-swap behavior remain compatible with the PR reference.

### `provider.py`

Owns the ChatGPT Codex HTTP boundary:

- base URL: `https://chatgpt.com/backend-api/codex`
- credentials are attached only to trusted URLs under that origin/path
- request headers: bearer token, ChatGPT account ID, GPT Dive originator
- a replayable 401 triggers one credential refresh and retry
- generic `max_tokens`, `temperature`, and `top_p` settings are dropped through the official `openai_unsupported_model_settings` profile seam

### `model.py`

`OpenAICodexResponsesModel` subclasses official `OpenAIResponsesModel`. The Codex backend requires streaming and `store=False`, while GPT Dive must continue to support ordinary `Agent.run()`.

The local model therefore:

1. forces `openai_store=False`;
2. implements ordinary `request()` by using official `request_stream()`, draining it, and returning the aggregate;
3. re-surfaces the local login-required error when the OpenAI SDK wraps it as a connection error;
4. fails `count_tokens()` clearly because the subscription backend does not serve the Responses input-token-count endpoint.

This is deliberately smaller than modifying official `models/openai.py`.

## Official seams we depend on

Re-check these on every Pydantic AI upgrade:

- `pydantic_ai.providers.Provider` lifecycle and `_set_http_client` contract
- `pydantic_ai.models.create_async_http_client`
- `pydantic_ai.profiles.merge_profile`
- `pydantic_ai.profiles.openai.OpenAIModelProfile`
- `pydantic_ai.profiles.openai.openai_model_profile`
- `pydantic_ai.models.openai.OpenAIResponsesModel`
- `OpenAIResponsesModel.request_stream(...)` and streamed response `.get()` aggregation
- `ModelSettings` accepting OpenAI provider-specific keys such as `openai_store`
- `openai_unsupported_model_settings` profile behavior

The only intentional deeper coupling is `OpenAICodexProvider._set_http_client()` updating the OpenAI SDK client's internal `_client` reference after Pydantic's provider lifecycle recreates an owned HTTP client. This is an OpenAI SDK private-field dependency and must be checked on upgrades.

## Differences from PR #6433

GPT Dive does **not** carry the entire PR.

- No modification of official Pydantic AI source files.
- No `openai-codex` provider registration in Pydantic's global provider inference table. GPT Dive constructs the local provider explicitly.
- No Pydantic CLI authentication integration. GPT Dive owns the auth object directly.
- No embeddings integration; Codex subscription is a Responses model transport only.
- Ordinary `Agent.run()` compatibility is implemented in the local subclass rather than by adding Codex-specific profile flags to official `OpenAIResponsesModel`.
- The request `originator` is `gpt-dive`.
- Codex-specific `/responses/compact` response-shape adaptation from #6433 is not currently carried. GPT Dive does not depend on provider-side compaction. Add it only if a real GPT Dive use case and acceptance test require it.
- Explicit `openai_previous_response_id`/server-side stored-response workflows are not a supported Codex assumption because the backend is forced to `store=False`; normal GPT Dive history is replayed as messages.

## Invariants

- `from pydantic_ai import Agent` and ordinary official Pydantic AI behavior do not import the local Codex compatibility package.
- Anthropic-compatible and ordinary OpenAI API-key providers remain independent of this package.
- Only subscription-backed `sol`, `terra`, and `luna` routing lazily imports the local layer.
- Ordinary `Agent.run()` works for Codex subscription execution.
- Tool-call round trips work.
- Python 3.14 is supported.
- Secret values are never emitted by status/tests/docs.
- Failure of the Codex-specific layer must not break base Pydantic imports or non-Codex providers.

## Authentication operation

Normal requests use the managed credential record in `~/.pydantic-ai/auth.json`. `OpenAICodexAuth` performs lazy load and request-time refresh; provider construction itself does not read credentials or start login work.

When interactive re-authentication is required, use `OpenAICodexAuth.login_browser(...)` or `login_device(...)` from a narrowly scoped operator command and persist through the same managed store. Do not copy raw tokens into configuration, prompts, Wiki, logs, or test fixtures.

A safe secret-free status probe is:

```bash
uv run --python 3.14 python - <<'PY'
import anyio
from gpt_dive.openai_codex import OpenAICodexAuth

status = anyio.run(OpenAICodexAuth().status)
print(status)
PY
```

## Upgrade procedure

For each official Pydantic AI update:

1. Verify the latest stable tag from the official upstream, not from stale Wiki memory.
2. Update/lock official `pydantic-ai-slim`; never re-introduce a downstream Pydantic fork merely to preserve this patch.
3. Compare the official seams listed above with the previous version.
4. Check whether upstream now ships equivalent Codex subscription auth/provider behavior. If yes, attempt retirement before adapting the local layer.
5. Run the focused compatibility suite before any live credential call.
6. Verify base imports and a non-Codex model route do not import `gpt_dive.openai_codex`.
7. Run live `Agent.run()`, one tool-call round trip, `bare(sol)`, and `subagent_call(sol)`.
8. Verify credential status; only force a live refresh when refresh behavior itself needs acceptance. Never print token values.
9. Run full GPT Dive pytest, Ruff, and Pyright, distinguishing pre-existing failures from patch regressions.
10. Update the compatibility history and exact seams in this file.

## PASS gates

A release/cut-over is accepted only when:

- official `pydantic-ai-slim` resolves from the package registry, not PR #6433
- upstream `pydantic_ai.providers.openai_codex` is not required
- focused compatibility tests PASS
- local provider trusted-URL auth and 401 refresh/replay tests PASS
- `Agent.run()` live PASS
- Codex tool-call live PASS
- `bare(sol)` live PASS
- `subagent_call(sol)` live PASS
- live credential refresh + post-refresh request PASS when refresh is part of the acceptance run
- non-Codex lazy-import isolation PASS
- relevant Ruff/Pyright PASS and full-suite regressions are accounted for

## Compatibility history

### 2026-08-14 — local compatibility introduced

- Reference: PR #6433 `af055625bf67217a5839d6255900475d9576aa13`; the local slim provenance artifact is `~/ref/pydantic-ai-pr-6433/codex-reference.patch.gz` (metadata in its `README.md`).
- Removed GPT Dive's Git source pin to the PR fork.
- Cut over to official `pydantic-ai-slim==2.30.0` / `pydantic-graph==2.30.0`.
- Kept security-sensitive auth/OAuth/store behavior locally with Pydantic-private utility dependencies removed.
- Replaced PR modifications to official `models/openai.py` with a narrow local `OpenAIResponsesModel` subclass.
- Live accepted ordinary `Agent.run()`, tool calling, `bare(sol)`, `subagent_call(sol)`, OAuth refresh, and a post-refresh request.

## Retirement condition

Delete `gpt_dive.openai_codex` when an official released Pydantic AI version provides equivalent ChatGPT subscription-backed Codex authentication/provider behavior **and** the GPT Dive acceptance suite passes after routing directly through that official implementation. The local layer is a compatibility bridge, not permanent architecture.
