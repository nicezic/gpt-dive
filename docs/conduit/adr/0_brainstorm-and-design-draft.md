# Conduit 0 — Brainstorm and Design Draft

> Status: pre-ADR design workspace. This file contains active design ideas, canary shape, and future directions that may still change. It is intentionally prefixed `0_` so it is not mistaken for a settled ADR.
>
> Stable causal context belongs in `../bootstrap.md`. Durable decisions that survive implementation pressure should later graduate into numbered ADRs.

## Current design decisions for the first implementation/canary

Settled enough to guide the current canary, but still subject to live acceptance:

1. **Project name:** Conduit.
2. **Web-facing MCP namespace:** `@c`.
3. **`@c` is kept and evolved from the canary onward**; do not create a throwaway `c_canary` namespace.
4. **One primary action per `@c` call.** Keep the schema small and explicit rather than turning one call into an unconstrained kitchen-sink payload.
5. **Every `@c` result automatically includes a compact active-task snapshot.**
6. **Task snapshots stay small.** Typical fields: stable ID, short intent/label, status, age. Full results are not repeated in every snapshot.
7. **Completed tasks are not automatically consumed/deleted on first collection in v0.** Result retrieval should not create an easy loss window.
8. **Redis is fixed as the event/fan-out layer.** No fallback transport is being designed in parallel.
9. **Failure should be explicit.** Do not add large speculative fallback trees. If a low-value fallback idea appears, note that it was considered and excluded rather than implementing it.
10. **MCP server metadata/schema changes require restart and fresh ChatGPT Web session acceptance.** Do not treat the same stale session as authoritative after MCP schema changes.

## First live canary

The first canary exists to answer one question only:

> Can one user Enter cause ChatGPT Web SOL to call `@c`, reason over the result, then call `@c` again in the same model turn?

Target flow:

```text
USER Enter once
      ↓
c1: start t1 (5–10 second detached task)
      ↓
return: t1 running
      ↓
SOL continues reasoning
      ↓
c2: short sync action
      ↓
return: t1 running OR done
      ↓
SOL final
```

Primary PASS condition:

```text
c1 → SOL reasoning → c2
```

A later user Enter should also show the still-active/completed task automatically in the next `@c` snapshot. Whether the 5–10 second task happens to finish before c2 is secondary.

This canary is about ChatGPT Web tool-loop behavior, not about re-proving Redis, JobManager, Edge, or GBrain.

## Task semantics direction

The intended model is approximately:

```text
running
  ↓
done
  ↓
result remains retrievable
  ↓
ack hides handled task from automatic snapshots
  ↓
archive / cleanup policy later
```

Do not make `collect` destructive in the first version. Duplicate reads are preferable to losing a result because the tool response was interrupted after server-side state mutation. `ack(task_id)` is the small post-canary lifecycle addition for terminal tasks: it hides a handled task from later automatic snapshots without deleting the retained JobManager result.

Task identity should be stable and understandable enough to correlate work across later conversation turns. A short intent label alongside the task ID is preferred.

The snapshot is a point-in-time observation, not a promise that the task cannot change state immediately after the response.

## Future direction

These are extension directions, not v0 implementation requirements.

### myWeb

The existing Council project already includes a custom Svelte/Starlette web UI/backend. A future Conduit web surface can generalize or reuse that experience so the user's primary chat UI becomes local while the existing logged-in ChatGPT Web tab remains the SOL runtime.

Possible long-term path:

```text
myWeb
  ↓ user input
Edge input adapter
  ↓
existing ChatGPT Web SOL
  ↓ meaningful output
@c
  ↓
Redis
  ↓
myWeb
```

### Durable conversation/event storage

The first tracer can write NDJSON under `/tmp`. Later, a dedicated durable DB may subscribe to the same event stream. Do not force durable-storage design into the canary.

### GBrain / knowledge pipeline

Conduit creates a future path for systematic analysis of user messages, assistant messages, task events, tool events, decisions, and derived knowledge.

The intended principle is:

```text
raw events
  ↓
filter / classify / deduplicate / sanitize
  ↓
selected high-value material
  ↓
GBrain or another retrieval/knowledge layer
```

Do not blindly embed every raw tool payload. Large logs, repetitive test output, HTML, stack traces, or credential-adjacent data should stay out of the semantic corpus unless intentionally distilled.

Current production GBrain is narrowly scoped to Pydantic retrieval; Conduit knowledge ingestion should become a separate source/group rather than polluting that corpus.

### GPT Dive relationship

Conduit may eventually become the thin Web-facing conversation/control gateway while GPT Dive moves further behind it as the execution backend:

```text
ChatGPT Web
   ↓
  @c
   ↓
Conduit protocol/router
   ├─ Redis event plane
   └─ GPT Dive runtime
       ├─ Code Mode
       ├─ JobManager
       └─ workers/capabilities
```

Do not merge the implementations prematurely. First prove the protocol boundary with the live canary.
