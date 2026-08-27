# GPT Dive Runtime Architecture

> Current SSOT for the stable v1-v2 runtime. Historical reasoning belongs in `history.md`; operational procedures belong in `operations.md`.

## Purpose

GPT Dive lets ChatGPT Web operate the user's local WSL2 environment through a deliberately small MCP surface while keeping reusable execution, orchestration, filtering, and policy behind an extensible local harness.

The normal path is:

```text
ChatGPT Web
  -> Secure MCP Tunnel
  -> GPT Dive MCP
  -> code_mode
  -> registered capabilities
  -> local WSL2
```

`code_mode` is the single programmable execution root for normal local work. Model-facing MCP calls require explicit string `payload` (`payload=""` when no data is needed). Detached work is always tracked: passing a `task` object (`{label, status?}`) runs the program as a durable detached execution and creates a Runtime Task on the existing process execution path; omitting `task` runs synchronously under a fixed 110s response deadline (100s execution cutoff plus a 10s cleanup window).

## Stable Web MCP Surface

Exactly two top-level tools are exposed:

- `bootstrap` — loads trusted fresh-session context from the user's local WSL2 wiki.
- `code_mode` — primary programmable execution root backed by Pydantic Monty. Supports synchronous foreground execution (`task=None`, fixed 110.0s deadline) and detached tracked execution via the `task` object (fixed 600.0s deadline).

Foreground timeout results expose `cleanup_status=complete|failed|pending`. Pending cleanup remains explicitly owned by the runtime; worker cleanup reports an un-reaped process without synthesizing an exit code.

The surface stays intentionally minimal. Reusable behavior belongs as registered `code_mode` capabilities instead of top-level MCP tools.

## Code Mode

`code_mode` executes a fresh Monty program per call and exposes `CWD` plus registered capabilities. It is designed for composition: independent work can run in parallel, large intermediate results can be filtered locally, and only compact evidence needs to return to the model context.

Current registered capability groups (18 capabilities):

```text
FileSystem
  read_file / write_file / edit_file
  list_directory / search_files / find_files
  create_directory / file_info

Model / orchestration
  subagent_call / agy_worker / peer_review / m3_evidence / council_emit

Task awareness
  task_list / task_collect / task_cancel / task_ack

Retrieval
  repo_search
```

Direct shell capabilities (`run_command`, `start_command`, `check_command`, `stop_command`, `gz64`) are completely removed from Code Mode. When shell execution is needed, compose registered capabilities or delegate to AGY / subagents.

Code Mode FileSystem resolves relative paths from `cwd` but permits host-wide non-secret reads and writes across `/` subject to normal OS permissions; credential/secret paths remain denied. `m3_evidence` is deliberately tool-less: it analyzes a caller-supplied evidence packet and proposes a bounded next-query set, while retrieval execution remains owned by the caller/Harness. Detailed Pydantic/Harness wiring lives in `docs/pydantic/code-mode.md`.

Council registers `council_emit` behind Code Mode as the explicit Web SOL output path; it remains a capability, not a fifth Web-facing MCP tool. The implemented Council runtime lives under `gpt_dive.council`.

## Durable Execution

`ExecutionManager` is GPT Dive's process lifecycle manager. It is reused by both the low-level async interface and background Code Mode.

- per-execution `execution_id`
- status / result / cancel
- concurrent executions
- timeout enforcement
- completed logs retained for 5 days
- transient `systemd --user` services when available
- guarded detached-process fallback when user systemd is unavailable

Background Code Mode launches a worker process through `ExecutionManager`. The worker rebuilds a fresh Monty runtime and capability registry, then returns a strict structured result envelope. The registry itself is not serialized across the process boundary.

Model-visible asynchronous work is tracked separately from process execution:

```text
ExecutionManager execution
      ↓ execution_id
SQLite TaskStore
      ↓
shared Task runtime + TrackedTasks projection
      ├─ @dive ordinary tool awareness
      └─ @c Conduit snapshot
```

Task state, acknowledgement, optional static status display, and derived elapsed time are Runtime-owned. Conduit uses the same ExecutionManager root, TaskStore, lifecycle normalization, and projection rather than maintaining `conduit.json` or a separate task-tracking SSOT. Execution results keep their normal retention policy; acknowledgement removes Task awareness without pinning the backing result.

## Harness and Subagents

`subagent_call` is a registered Code Mode capability rather than a top-level MCP tool. Workspace-enabled subagents use the Pydantic AI Harness coding bundle scoped to the supplied `cwd`, while GPT Dive's `guard-bin` remains first on `PATH`.

The main operating principle is SOL solo-first, with subagents used selectively for work that benefits from independent review, parallel exploration, or delegated implementation.

## Enforcement Layers

GPT Dive separates hard execution policy from harness policy.

1. **Execution policy** — command restrictions such as `guard-bin` apply below all execution surfaces. Direct native `python` execution is blocked.
2. **Harness policy** — capability shaping, orchestration, parallel composition, workspace scoping, local preprocessing, and context reduction live primarily behind `code_mode`.

## Source Layout

```text
src/gpt_dive/
├── __init__.py         # lazy app exports; worker import stays MCP-free
├── __main__.py
├── app.py              # MCP tools (bootstrap, code_mode) + singletons; capability registry lives in code_capabilities
├── code_capabilities.py
├── code_runtime.py
├── code_mode_worker.py
├── execution_manager.py
├── task_store.py
├── task_runtime.py     # shared Task lifecycle + background result normalizer (@dive/@c); TaskRuntime bundles the (executions, task_store) pair
├── conduit/
├── subagent_runtime.py
├── subagent_worker.py
├── council/            # implemented v3 Council backend + protocol + participant adapters
└── guard-bin/
```

The package entrypoints are `python -m gpt_dive` and `gpt-dive`.
