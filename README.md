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

See [`docs/runtime/architecture.md`](docs/runtime/architecture.md) for the current runtime SSOT.

## Evolution

```text
v1  Local MCP Runtime
     -> sync / async WSL2 control / gz64

v2  Pydantic AI Harness
     -> code_mode / background execution / subagents

v3  Council              <- current design work
     -> human-steered shared USER / SOL / OPUS discussion
```

These labels describe architecture generations, not the package semantic version.

Council grew from the manual SOL + User + Opus review workflow. Its goal is to automate transport while preserving human steering, shared reasoning context, independent judgment, and the Why behind decisions. The current v3 implementation/decision SSOT is [`specs/council.md`](specs/council.md).

See [`docs/council/history.md`](docs/council/history.md) for the reasoning lineage.

## Development

```bash
uv sync --python 3.14
uv run --python 3.14 python -m pytest -q
uv run --python 3.14 python -m gpt_dive
```

Operational notes, including safe MCP reload and Web schema-cache behavior, live in [`docs/runtime/operations.md`](docs/runtime/operations.md).

## Documentation

- [`docs/runtime/architecture.md`](docs/runtime/architecture.md) — current v1-v2 runtime architecture
- [`docs/runtime/history.md`](docs/runtime/history.md) — v1 -> v2 evolution and Why
- [`docs/runtime/operations.md`](docs/runtime/operations.md) — development and runtime operations
- [`docs/council/history.md`](docs/council/history.md) — Council evolution and current pre-spec direction
- [`plans/runtime/`](plans/runtime/) — completed/runtime implementation plans
- [`plans/council/`](plans/council/) — Council experiments and implementation plans
- [`specs/council.md`](specs/council.md) — Council v3 implementation/decision SSOT

## Source Layout

```text
src/gpt_dive/   # Python MCP runtime + harness
web/            # reserved for Council UI: Svelte 5 + Vite + TypeScript
```

The Council Python package split and Web app scaffold belong to v3 implementation and are intentionally not part of this documentation-only cleanup.
