# GPT Dive

**A local MCP runtime that lets ChatGPT Web work in the user's WSL2 environment without tying a job's lifetime to one MCP response.**

GPT Dive runs user-requested work as durable local Executions. ChatGPT can orchestrate files, shell commands, and AI workers through a typed **Pydantic Monty Code Mode**; host access flows through registered capabilities rather than arbitrary Python imports.

## How it fits together

~~~text
ChatGPT Web
    │ Secure MCP tunnel
    ▼
GPT Dive MCP (bootstrap / code_mode / task / wsl_exec)
    │
    ├─ bootstrap ───────────► trusted ~/wiki context
    ├─ code_mode ───────────► SQLite Execution lifecycle
    │                             │
    │                             ▼
    │                         isolated Worker
    │                             │
    │                             ▼
    │                         Monty + typed capabilities
    │                             ├─ files / commands
    │                             ├─ AI workers / peer review
    │                             └─ Conduit Room emission (legacy council_emit)
    └─ task ────────────────► published Task awareness and result pickup

Conduit ──────────────────► single conversation / collaboration product
    ├─ @c transport ───────► shared Execution / Task + Redis events
    └─ Room ───────────────► USER / SOL / OPUS Git discussion + Svelte UI
~~~

**Why durable?** A Web/MCP response may time out or disconnect while local work is still running. GPT Dive records the Execution before starting user code; SQLite is the lifecycle authority, and recovery does not automatically replay side effects. Inline completion and Task publication are delivery choices for the same Execution.

## MCP surface

| Tool | Purpose |
|---|---|
| `bootstrap` | Load the configured trusted Wiki preload packet for a fresh session. |
| `code_mode` | Execute one fresh Monty program with typed local capabilities. `label` and `code` are required; `delivery=auto` waits briefly, while `delivery=task` publishes a Task. |
| `task` | `list`, `get`, `cancel`, or `dismiss` a published Task using its `execution_id`. Result pickup is non-destructive. |
| `wsl_exec` | Bounded emergency raw-shell fallback, outside the durable Code Mode lifecycle. |

**Code Mode is not ordinary CPython.** The executable code uses Monty's supported Python subset; filesystem, commands, and external models are accessed through registered capabilities. Each Execution starts with fresh Monty state. Capability signatures come from **live generated declarations**, not from a copied list in this README. `CWD` and `CAPABILITIES` are injected; `PAYLOAD` is available when supplied.

The outer MCP tool schema owns its accepted arguments. See [Code Mode integration](docs/pydantic/code-mode.md) for the implementation contract and `~/wiki/workflow/code-mode.md` for AI-facing usage rules.

## Ownership and documentation

~~~text
GPT Dive Runtime
  owns: Execution / Worker / Task / TrackedTasks
        SQLite lifecycle, deadlines, recovery, local capabilities
               ▲
               │ reuses execution and passive task awareness
Conduit
  ├─ Transport: conversation protocol, Redis event delivery, @c
  └─ Room:      human-steered USER / SOL / OPUS conversation,
                Git transcript, input-only Web SOL bridge, Svelte UI
  uses: GPT Dive Runtime lifecycle and Pydantic AI workers
~~~

**A Task is not a second job or a second ID.** Runtime owns its lifecycle; Conduit projects the same Runtime-owned TrackedTasks and does not create an independent Task store. Canonical terminology lives in [Runtime Context](docs/runtime/CONTEXT.md) and [Conduit Context](docs/conduit/CONTEXT.md).

| Read when you need… | Source of truth |
|---|---|
| Current Execution/Worker/Task architecture | [Runtime architecture](docs/runtime/architecture.md) |
| Execution terminology and invariants | [Runtime Context](docs/runtime/CONTEXT.md) |
| Conduit language and protocol ownership | [Conduit Context](docs/conduit/CONTEXT.md) and [Conduit README](docs/conduit/README.md) |
| Code Mode, filesystem, and capability integration | [Pydantic Code Mode](docs/pydantic/code-mode.md) |
| Provider aliases and Pydantic AI integration | [Providers](docs/pydantic/providers.md) |
| Conduit Room and collaborative discussion | [Room README](docs/conduit/room/README.md) |
| Service operation, restart, evidence, troubleshooting | [Runtime operations](docs/runtime/operations.md) and [timeouts](docs/runtime/timeouts.md) |
| Architecture decisions and ownership | [ADR index](docs/ADR.md) |

For **current behavior**, prefer source, tests, and the live MCP contract over historical plans, ADR records, or previous-session handoffs. Wiki preload configuration determines what a new AI session actually receives; repository docs are not loaded automatically.

## Development

Requires **Python 3.14** and `uv`. The running MCP tunnel, credentials, and local systemd services are deployment concerns described in [operations](docs/runtime/operations.md).

~~~bash
uv sync --python 3.14
uv run --locked --no-sync pytest -q tests/
uv run --locked --no-sync ruff check .
uv run --locked --no-sync ruff format --check .
uv run --locked --no-sync pyright src
~~~

To run the MCP server directly on its standard I/O transport:

~~~bash
uv run --locked --no-sync python -m gpt_dive
~~~

The pytest suite disables **real Pydantic AI model requests**; production model requests use their configured providers and credentials.

## Repository layout

~~~text
src/gpt_dive/       MCP server, Monty, Runtime, Conduit transport + Room
web/                Conduit Room frontend (Svelte)
docs/runtime/       execution behavior, operations, and decision records
docs/pydantic/      Monty, Harness, providers, and capability contracts
docs/conduit/       conversation/event protocol, Room docs, and Conduit decisions
tests/              offline regression and runtime contract tests
plans/              selected historical and open implementation plans
~~~
