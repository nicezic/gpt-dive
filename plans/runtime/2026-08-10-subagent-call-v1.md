# Mini Spec — Code Mode subagent_call v1

## Purpose

Add one model-call primitive behind the existing `code_mode` registry without changing the four-tool MCP surface.

## Decision

- Add one registered capability: `subagent_call(model, task, timeout, output_tokens_limit)`.
- Initial model aliases: `opus5`, `m3`, `terra`, `luna`.
- Reuse the verified custom Pydantic AI PR #6433 snapshot for OpenAI Codex subscription auth.
- Run model calls in a child process through `creds run ai` so provider secrets are injected only for the call and are not exposed to Monty.
- Keep orchestration features (`SubAgents`, `Advisor`, `DynamicWorkflow`) out of v1; they can compose on top of this primitive later.

## Provider mapping

- `opus5` -> AIAPIFLOW Anthropic-compatible -> `claude-opus-5`
- `m3` -> MiniMax Anthropic-compatible -> `MiniMax-M3`
- `terra` -> OpenAI Codex subscription -> `gpt-5.6-terra`
- `luna` -> OpenAI Codex subscription -> `gpt-5.6-luna`

## Test Contract

1. Existing MCP surface remains exactly four tools.
2. `CAPABILITIES` includes `subagent_call`.
3. Unit tests prove the capability delegates with model/task/limits and remains composable inside Monty.
4. Provider worker rejects unknown aliases before network access.
5. One tiny live smoke per alias returns the requested marker without exposing credentials.
6. Existing test suite remains green.


## Result

**FULL PASS — 2026-08-10**

- MCP surface remains four top-level tools.
- `code_mode` live `CAPABILITIES` includes `subagent_call`.
- Local unit suite passed after the subagent layer and PATH fix.
- Direct provider smoke passed for `opus5`, `m3`, `terra`, and `luna`.
- Actual Web SOL -> Dive `code_mode` -> `subagent_call(model="m3")` E2E returned exactly `DIVE_WEB_SUBAGENT_OK` with one model request.
- Root cause of the earlier Web failure was executable discovery: `creds` uses `#!/usr/bin/env -S uv run --script`; the subagent child now prepends `~/.local/bin` to its scoped `PATH`.
- No provider secret is exposed to Monty; secret injection remains inside `creds run ai`.
