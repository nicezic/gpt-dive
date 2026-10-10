---
title: TODO — Top-level Durable AGY Worker MCP Surface
created: 2026-08-30
updated: 2026-10-10
type: decision
status: accepted
---

# TODO — Durable AGY Worker MCP Surface

**Accepted design; not implemented as a public tool.** `agy_worker` currently lives behind Code Mode. This proposal is a narrow exception to [ADR 0004](0004-always-durable-code-mode-runtime.md)'s default of not exposing individual AI capabilities as new MCP tools. It exists to let an independent MCP-native orchestrator such as Zed delegate read-only repo investigation without writing Monty.

~~~text
code_mode Execution → await agy_worker ─┐
                                        ├─ shared official AGY stream-json core
future top-level agy_worker ────────────┘
          ↓
ExecutionManager(kind="agy")
          ├─ inline result
          └─ same GPT Dive Task / execution_id
~~~

## Why

External native-agent orchestration cannot reliably call an inner `agy_worker` as a first-class MCP tool. A standalone AGY server would duplicate authentication, recovery, output evidence and Task lifecycle. One integration core with **two wrappers** solves the actual access gap.

## Decisions / constraints

1. Expose a **single** top-level `agy_worker` for independent, read-only work. Exact strict Pydantic input schema and response shape must be defined when implementing.
2. Top-level calls acquire a durable root `Execution` from the existing `ExecutionManager`, with `kind="agy"`. Publish/lookup/cancel/dismiss reuse the current `task` lifecycle, never a second Task authority.
3. Code Mode's existing awaited AGY capability stays inside its **parent** Execution and child budget. Do not create nested durable Executions/Tasks.
4. Both entrypoints share official AGY invocation, model/CWD/conversation parameters, `stream-json` NDJSON parsing, normalized result and error metadata. `conversation_id` resume is a supported official CLI seam to preserve.
5. Retain full execution evidence independently from a bounded caller-facing result; do not let large stdout flood model context.
6. Defer native MCP Tasks `io.modelcontextprotocol/tasks`; a future adapter may project the existing Execution but must not establish its own lifecycle truth.
7. Existing scope is read-only. Worktree isolation, writable agents, speculative retries and generic agent-router frameworks are separate decisions.

## Rejected paths

| Alternative | Reason |
|---|---|
| Separate AGY MCP daemon/runtime | duplicates process containment and Task store |
| `agy_start/status/read/result/cancel` tool family | users already have `task` |
| Always nest Code Mode → AGY Execution | breaks parent cancellation/deadline ownership |
| Separate `agy_search`/`agy_review` tools | unnecessary hardcoded workflow categories |
| PTY/screen-scraping fallback | official `stream-json` is machine-readable |
| Implement native MCP Tasks first | protocol support not confirmed in target client |

## Acceptance before shipping

- Verify Zed or target caller sees and invokes the exact top-level schema.
- Confirm SQLite-first acceptance, worker CAS, cancellation containment and `execution_id` correlation.
- Verify streamed output parsing, read-only filesystem policy, provider auth, transcript retention and graceful failures.
- Check parent Code Mode execution still awaits its child without spawning a nested Task.
- Confirm service restart/recovery and no replay of side-effectful work.

**Status reminder:** this is a preserved design candidate, not evidence of an installed fifth GPT Dive MCP tool. Current MCP tool names and runtime budgets live in `src/gpt_dive/app.py` and [operations](../operations.md).
