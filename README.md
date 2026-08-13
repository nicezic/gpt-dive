# GPT Dive

GPT Dive connects ChatGPT Web to the user's local WSL2 environment through a small MCP surface and an extensible Pydantic-based execution harness.

## Architecture at a Glance

```text
ChatGPT Web
  -> Secure MCP Tunnel
  -> GPT Dive
       -> code_mode      # primary programmable harness
       -> wsl2_sync      # short direct shell
       -> wsl2_async     # durable job lifecycle
```

Fresh sessions begin with `bootstrap`. Reusable execution and orchestration behavior should normally grow behind `code_mode` rather than expanding the Web-facing MCP surface.

## Stable MCP Surface

Exactly four top-level tools:

- `bootstrap`
- `code_mode`
- `wsl2_sync`
- `wsl2_async`

See `docs/runtime/architecture.md` for the stable runtime SSOT.

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

Operational notes, including safe MCP reload and Web schema-cache behavior, live in `docs/runtime/operations.md`.

## Documentation

### Runtime

- `docs/runtime/architecture.md` — current v1-v2 runtime architecture.
- `docs/runtime/history.md` — v1 → v2 evolution and Why.
- `docs/runtime/operations.md` — development/runtime operations.
- `plans/runtime/` — completed runtime plans.

### Council

- `docs/council/README.md`
- `docs/council/history.md`
- `docs/council/startup.md`
- `specs/council.md`
- `plans/council/`

## Source Layout

```text
src/gpt_dive/   # Python MCP runtime + harness + Council backend
web/            # Council UI: Svelte 5 + Vite + TypeScript
```
