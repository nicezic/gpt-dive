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

`code_mode` is the primary harnessable execution root. `wsl2_sync` and `wsl2_async` remain lower-level escape/control paths rather than the main orchestration API.

## Stable Web MCP Surface

Exactly four top-level tools are exposed:

- `bootstrap` — loads trusted fresh-session context from the user's local WSL2 wiki.
- `code_mode` — primary programmable execution root backed by Pydantic Monty. Supports foreground execution and durable background execution with `background=True` plus `status/result/cancel` lifecycle actions.
- `wsl2_sync` — short synchronous shell execution with immediate result.
- `wsl2_async` — durable shell/process lifecycle interface, normally backed by `systemd --user`.

The surface stays intentionally small. New reusable behavior should normally become a registered `code_mode` capability instead of a new top-level MCP tool.

## Code Mode

`code_mode` executes a fresh Monty program per call and exposes `CWD` plus registered capabilities. It is designed for composition: independent work can run in parallel, large intermediate results can be filtered locally, and only compact evidence needs to return to the model context.

Current registered capabilities:

```text
local_exec
local_start
local_status
local_result
local_cancel
subagent_call
gz64
```

The Council transport experiment also registers `council_emit`; it is a v3-facing capability probe, not a fifth Web MCP tool and not yet the full Council runtime.

## Durable Execution

`JobManager` is GPT Dive's process lifecycle manager. It is reused by both the low-level async interface and background Code Mode.

- per-job `job_id`
- status / result / cancel
- concurrent jobs
- timeout enforcement
- completed logs retained for 5 days
- transient `systemd --user` services when available
- guarded detached-process fallback when user systemd is unavailable

Background Code Mode launches a worker process through `JobManager`. The worker rebuilds a fresh Monty runtime and capability registry, then returns a strict structured result envelope. The registry itself is not serialized across the process boundary.

## Harness and Subagents

`subagent_call` is a registered Code Mode capability rather than a top-level MCP tool. Workspace-enabled subagents use the Pydantic AI Harness coding bundle scoped to the supplied `cwd`, while GPT Dive's `guard-bin` remains first on `PATH`.

The main operating principle is SOL solo-first, with subagents used selectively for work that benefits from independent review, parallel exploration, or delegated implementation.

## Enforcement Layers

GPT Dive separates hard execution policy from harness policy.

1. **Execution policy** — command restrictions such as `guard-bin` apply below all execution surfaces. Direct native `python` execution is blocked regardless of whether the shell is reached through Code Mode or a lower-level tool.
2. **Harness policy** — capability shaping, orchestration, parallel composition, workspace scoping, local preprocessing, and context reduction live primarily behind `code_mode`.

## MCP Tasks

GPT Dive can integrate with the MCP Tasks lifecycle when the client negotiates `io.modelcontextprotocol/tasks` on the required protocol version. ChatGPT Web has not negotiated that extension in the verified environment, so GPT Dive currently relies on its own durable job lifecycle for background work.

## Source Layout

```text
src/gpt_dive/
├── __init__.py
├── __main__.py
├── app.py
├── code_runtime.py
├── code_mode_worker.py
├── job_manager.py
├── subagent_runtime.py
├── subagent_worker.py
├── tasks_extension.py
├── council.py          # v3 transport probe; not yet final Council package
└── guard-bin/
```

The package entrypoints are `python -m gpt_dive` and `gpt-dive`.
