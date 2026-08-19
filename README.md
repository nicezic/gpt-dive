# GPT Dive

GPT Dive connects ChatGPT Web to the user's local WSL2 environment through a small MCP surface and a Pydantic-based execution harness.

```text
ChatGPT Web
  -> Secure MCP Tunnel
  -> GPT Dive
       -> bootstrap
       -> code_mode      # default local execution, payload string required on MCP calls
       -> wsl2_sync      # transport/smoke or explicit exception
       -> wsl2_async     # durable job lifecycle
```

Fresh sessions begin with `bootstrap`. Preload files come from `~/wiki/bootstrap/preload.json`. Periodic reminder cadence and file/section sources come from `~/wiki/bootstrap/reminder.json`; the current map emits only `USER_RULES.md` → `## Reminder` every 3 non-bootstrap `@dive` tool calls, and an explicit `bootstrap` resets that connection's counter. `ERROR_CASE.md` is read only after MCP/Dive failures. Reusable execution and orchestration behavior should normally grow behind `code_mode` rather than expanding the Web-facing MCP surface.

## OpenAI Codex subscription compatibility

GPT Dive consumes official Pydantic AI. Subscription-backed `sol` / `terra` / `luna` models route through the optional local `gpt_dive.openai_codex` compatibility layer rather than a downstream Pydantic AI fork. The local layer owns only Codex-specific OAuth, credential rotation, provider transport, and the narrow Responses adaptation needed to preserve ordinary `Agent.run()`. Non-Codex providers remain ordinary Pydantic AI paths.

**Update Policy**
Maintenance SSOT, upstream seams, upgrade procedure, and retirement condition: `README.patch.openai.provider.md`.

## Documentation ownership

- **AI-facing usage / capability lifecycle:** `~/wiki/workflow/pydantic-ai/README.md`
- **Runtime architecture / operations:** `docs/runtime/architecture.md`, `docs/runtime/operations.md`
- **MCP stdio diagnostics / journald:** `docs/runtime/mcp-stdio-lifecycle.md`
- **GPT Dive Pydantic implementation:** `docs/pydantic/README.md`
- **Code Mode implementation contract:** `docs/pydantic/code-mode.md`
- **Provider integration:** `docs/pydantic/providers.md`
- **Council:** `docs/council/README.md`
- **Codex compatibility maintenance:** `README.patch.openai.provider.md`
- **Current handoff:** `CONTINUATION.md`

Registered Code Mode capability signatures and callable docstrings are model-visible live contracts exposed through `CAPABILITIES` inside `code_mode`; the public MCP schema owns the outer tool contract. `bootstrap` loads the configured Wiki preload packet, not capability signatures. When capability behavior changes, keep its signature and docstring concise and accurate; detailed AI usage/routing policy belongs in the Wiki rather than being duplicated here.

## Evolution

```text
v1  Local MCP Runtime
     -> sync / async WSL2 control / gz64

v2  Pydantic AI Harness
     -> code_mode / background execution / subagents

v3  Council
     -> human-steered shared USER / SOL / OPUS room
```

These labels describe architecture generations, not package semantic versions.

Council grew from the user's successful manual SOL + User + Opus review workflow. Its purpose is to automate transport while preserving human steering, shared reasoning context, independent judgment, and the Why behind decisions.

Council v1 is implemented / FULL PASS. The current next product area is start/reopen ergonomics.

## Council

Start here:

- `docs/council/README.md` — compact current architecture and documentation map.
- `docs/council/history.md` — reasoning lineage: manual Council → Web SOL bridge → Shared Room → v1 → startup friction.
- `docs/council/startup.md` — approved post-v1 start/reopen direction and `init.md` context shape.
- `specs/council.md` — Council v1 implementation/decision SSOT and acceptance evidence.
- `plans/council/` — historical experiments and completed implementation plans.
- `CONTINUATION.md` — fresh-session live handoff.

## Development

```bash
uv sync --python 3.14
uv run --python 3.14 python -m pytest -q
uv run --python 3.14 python -m gpt_dive
```

For live MCP operations, see [`docs/runtime/operations.md`](docs/runtime/operations.md) — **how to restart**, reload safely, and handle durable jobs.

Standard MCP restart handoff:

```bash
nohup bash -lc 'sleep 3; systemctl --user restart chatgpt-wsl2-mcp.service' >/tmp/gpt-dive-mcp-restart.log 2>&1 &
```

After dispatching this restart, **do not automatically verify or probe the restarted MCP from the same turn/session**. Return control to the user and wait for an explicit follow-up before checking PID, bootstrap, schema, or runtime state.

## Source layout

```text
src/gpt_dive/   # Python MCP runtime + harness + Council backend
web/            # Council UI: Svelte 5 + Vite + TypeScript
```
