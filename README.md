# GPT Dive

GPT Dive connects ChatGPT Web to the user's local WSL2 environment through a small MCP surface and a Pydantic-based execution harness.

```text
ChatGPT Web
  -> Secure MCP Tunnel
  -> GPT Dive
       -> bootstrap
       -> code_mode      # single programmable execution root, payload string required on MCP calls
```

Fresh sessions begin with `bootstrap`. Preload files come from `~/wiki/bootstrap/preload.json`. Periodic reminder cadence and whole-file/section sources come from `~/wiki/bootstrap/reminder.json`; the current map re-emits the full `USER_RULES.md` plus focused GPT Dive / Code Mode sections every 3 non-bootstrap `@dive` tool calls, and an explicit `bootstrap` resets that connection's counter. `ERROR_CASE.md` is read only after MCP/Dive failures. Reusable execution and orchestration behavior belongs behind `code_mode` as the single model-facing execution surface.

Code Mode enforces deterministic server-side execution deadlines (not AI arguments):

- **Foreground Code Mode (`task=None`):** fixed 110.0-second response deadline, divided into a 100-second execution cutoff and a 10-second cleanup window. The structured `code_mode_timeout` result reports `cleanup_status=complete|failed|pending`; pending cleanup remains runtime-owned until it finishes.
- **Detached Code Mode (`task={label, ...}`):** fixed 600.0-second deadline backed by durable background execution and persistent Task tracking. Direct shell execution capabilities (`run_command`, `start_command`, `check_command`, `stop_command`, `gz64`) are completely removed; use registered domain capabilities or delegate to AGY / subagents.

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
     -> programmable Code Mode root / durable Task domain

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
nohup bash -lc 'sleep 3; sudo systemctl restart gpt-dive-tunnel.service' >/tmp/gpt-dive-mcp-restart.log 2>&1 &
```

After dispatching this restart, **do not automatically verify or probe the restarted MCP from the same turn/session**. Return control to the user and wait for an explicit follow-up before checking PID, bootstrap, schema, or runtime state.

## Source layout

```text
src/gpt_dive/   # Python MCP runtime + harness + Council backend
web/            # Council UI: Svelte 5 + Vite + TypeScript
```
