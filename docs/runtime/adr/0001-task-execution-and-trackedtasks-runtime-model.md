---
title: ADR - Task, Execution, and TrackedTasks Runtime Model
created: 2026-08-21
updated: 2026-08-23
type: decision
status: proposed
---

# ADR 0001 - Task, Execution, and TrackedTasks Runtime Model

## Decision summary

GPT Dive will add a **thin Task-awareness layer on top of its existing durable background execution path**.

The design solves one concrete problem:

```text
long delegated work starts
        ↓
Web SOL must not wait
        ↓
Web SOL keeps doing useful foreground work
        ↓
later ordinary tool calls remind SOL what is still running or finished
```

The canonical split is deliberately small:

```text
Task
= meaningful detached work Web SOL should remember

Execution
= the durable background runtime that actually performs the work

TrackedTasks
= compact automatic projection of outstanding Tasks
```

### Why Task and Execution are separate

GPT Dive must manage heterogeneous long-running work without forcing those workers to share one implementation:

```text
background Code Mode   AGY   peer review   Conduit   future workers
        \               |        |           |            /
         +--------------+--------+-----------+-----------+
                                |
                                v
                          Execution boundary
                     status / result / cancel
                                |
                                v
                              Task
                 Web SOL awareness / handling
                                |
                                v
                          TrackedTasks
```

The separation protects two different semantics. **Execution completion is a runtime event; Task handling is a Web SOL event.** A worker may finish while its Task must remain visible until Web SOL decides that the result was handled or is no longer useful.

Execution is also the common boundary across different long-running workers, not a requirement that every worker use one runner framework. Existing worker-specific launch and result semantics stay at their current boundaries and are normalized only enough for Task awareness and control.

The v1 rule is **reuse before abstraction**. Existing background Code Mode remains the normal detached execution path. GPT Dive does not introduce a new runner framework, recovery subsystem, idempotency subsystem, or launcher hierarchy merely to implement Task awareness.

---

## 1. Problem

The motivating failure mode is synchronous delegation such as peer review:

```text
Web SOL
  → ask reviewer
  → wait 30 seconds ... minutes
  → receive answer
```

During the wait, Web SOL cannot continue unrelated foreground work.

Simply detaching the process is not enough:

```text
start background job
  → receive opaque handle
  → SOL must remember it manually
```

That handle is easy to forget across later turns or a fresh ChatGPT session.

The desired workflow is:

```text
Web SOL
  → start Task
  → return immediately
  → continue foreground work
  → ordinary @dive/@c call
  → see TrackedTasks
  → collect result when useful
  → ack when no longer worth reminding
```

Execution completion and Web SOL handling are separate events.

---

## 2. Scope

This is a GPT Dive Runtime decision.

It applies to detached work started for:

- background Code Mode;
- `/peer-review`;
- long AGY work;
- Conduit asynchronous work;
- other future long work only when a real consumer exists.

It does **not** require native MCP Tasks, a distributed scheduler, crash recovery, event sourcing, or a general workflow engine.

---

## 3. Canonical language

### Task

A **Task** is meaningful detached work that Web SOL should remain aware of until it is explicitly handled.

A Task is not a process DTO and is not a renamed Job.

### Execution

An **Execution** is the durable local background execution that performs the work.

It owns process/runtime concerns such as:

- launch;
- timeout;
- cancellation;
- stdout/stderr or worker result;
- terminal status;
- normal result retention.

The canonical durable identity is `execution_id`.

### TrackedTasks

**TrackedTasks** is the compact automatic list of Tasks Web SOL still needs to remember.

It is a projection, not another manager or persistence layer.

### Lost

**Lost** means GPT Dive can no longer find the backing Execution or retained result needed to continue observing the Task.

Lost work is **not reconstructed, recovered, re-polled, or guessed**. It remains `lost` until Web SOL acknowledges it.

---

## 4. Minimal v1 Task model

```text
Task
├─ task_id
├─ execution_id
├─ label
├─ state
├─ status_cmd?   # optional dynamic display probe
├─ status?       # optional static display text
├─ created_at
└─ updated_at
```

No v1 Task field exists for:

```text
source
runner
start_key
status_label     # derived at render time, not persisted
elapsed/duration # derived from timestamps, not persisted
handled_at
provider session ids
PID/backend
result copy
retry history
```

### 4.1 `task_id`

Independent durable Task identity, for example a UUID.

`task_id` and `execution_id` are different concepts and must not intentionally share identity.

### 4.2 `execution_id`

Points to exactly one backing Execution in v1.

```text
1 Task : 1 Execution
```

### 4.3 `label`

A short human-readable description of the delegated work.

Detached work requires a non-empty label. Recommended UI limit: 80 characters.

Examples:

```text
Review Task ADR
Run provider regression
Check AGY ACP stream
```

### 4.4 `state`

The compact v1 state set is:

```text
working
completed
failed
cancelled
lost
```

Typical transitions:

```text
working → completed
        → failed
        → cancelled
        → lost
```

If a previously observed terminal Task later loses its backing retained Execution/result before acknowledgement, it may become `lost`. v1 favors simple truthful observation over preserving a historical terminal label that can no longer be collected.

There is no recovery transition out of `lost`.

### 4.5 Display status

Task display status is optional decoration and never lifecycle state.

```text
status_cmd present
    → run the small local command
    → usable stdout becomes status_label

status_cmd absent, or probe has no usable output
    → use static status when present

neither available
    → render label + state + elapsed time only
```

Typical dynamic output may be as small as `TODOS 3/9`. A worker such as AGY may expose this through a command like `cat /tmp/agy-worker/<job>/status.md` without learning the Task database contract.

`status_cmd` is best-effort, local, bounded, and only useful for visible working Tasks. Failure, timeout, or empty output does not change `Task.state`. `status_label` is derived output and is not persisted.

---

## 5. Execution contract

The existing durable background machinery supplies the v1 **Execution** boundary. Task/TrackedTasks functionality is proven on top of that machinery before terminology cleanup becomes a migration concern.

The canonical domain language is:

```text
Execution
execution_id
```

The first functional rollout used `JobManager` / `job_id` internally while the Task lifecycle was being proven. After Task awareness, AGY, and the shared Conduit Task domain were validated, the current runtime implementation was cleaned up to `ExecutionManager` / `execution_id` with the durable state root at `~/.local/state/gpt-dive/executions`. No compatibility alias or old-state migration reader remains, and the cleanup did not introduce a second execution framework.

### 5.1 One normalized Execution outcome

Task awareness must not require a second semantic collector framework.

Each background worker/launcher is responsible for making its own Execution outcome truthful before the Execution is finalized:

```text
success   → Execution completed + retained result
failure   → Execution failed + retained error/result evidence
cancel    → Execution cancelled
missing   → Task observes lost
```

If Code Mode, AGY, or peer review needs envelope validation, that logic stays inside its existing worker/launch boundary. It does not create a durable `runner` registry or a fresh-session adapter dispatch system.

---

## 6. Background launch path

GPT Dive keeps the existing background Code Mode concept instead of replacing it with new `shell_task`, `code_task`, `agy_task`, or `peer_review_task` frameworks.

Conceptually:

```text
code_mode(
  background=True,
  label="Review Task ADR",
  ...existing code/payload/cwd...
)
        ↓
start Execution
        ↓
create Task(task_id, execution_id, label, working)
        ↓
return Task-level start result immediately
```

Foreground Code Mode remains unchanged.

### 6.1 Background start result

Normal start success exposes Task-level information only:

```json
{
  "task_id": "...",
  "label": "Review Task ADR",
  "state": "working"
}
```

`execution_id`, PID, backend, raw command, and other low-level details are diagnostics, not ordinary SOL-facing output.

### 6.2 Creation failure

Recommended simple ordering:

```text
1. start Execution
2. obtain execution_id
3. persist Task
4. return success
```

If Task persistence fails after Execution start, GPT Dive makes a **best-effort cancel** and returns failure.

If GPT Dive itself crashes between those steps, v1 does not build orphan reconciliation. The backing Execution's own timeout/lifecycle eventually ends it. No startup recovery subsystem is introduced.

---

## 7. Task persistence

Use one small SQLite Task registry shared by GPT Dive surfaces.

Conceptually:

```text
SQLite
└─ tasks
   ├─ task_id PRIMARY KEY
   ├─ execution_id
   ├─ label
   ├─ state
   ├─ created_at
   └─ updated_at
```

SQLite owns **Task awareness only**.

Execution/process persistence remains owned by the backing Execution runtime. Do not duplicate Execution state into a second SQLite execution SSOT.

There is no source partition. `@dive` and `@c` read the same outstanding Task list.

---

## 8. Refresh and fresh-session behavior

On an ordinary GPT Dive/Conduit tool call:

```text
load outstanding Tasks
        ↓
for each Task, inspect local Execution status
        ↓
update working → completed/failed/cancelled
or missing → lost
        ↓
append compact TrackedTasks
```

Refresh is local and bounded.

It must not:

- call a provider again;
- ask an agent for status;
- reconstruct missing worker state;
- search old files trying to infer a result;
- retry lost work automatically.

A fresh ChatGPT session therefore rediscovers whatever Task records still exist. If the backing Execution is gone, it sees `lost`.

---

## 9. TrackedTasks projection

`task_list()` returns complete structured TrackedTask objects and may also include the same human-readable rows used by automatic awareness. Structured data and display text are separate projections of the same Task records.

A structured item conceptually contains:

```text
TrackedTask
├─ task_id
├─ execution_id
├─ label
├─ state
├─ status_cmd?
├─ status?
├─ status_label?     # derived from status_cmd or static status
├─ created_at
├─ updated_at
└─ elapsed_seconds   # derived, not persisted
```

The compact text stays small:

```text
TrackedTasks
├─ AGY research · 🧵 working · 4:21 · TODOS 3/9
├─ Review ADR · ✅ completed · 2:08
└─ Regression · ❌ failed · 1:22
```

State markers are deliberately small and fixed:

```text
🧵 working
✅ completed
❌ failed
⛔ cancelled
⚠️ lost
```

Elapsed time is derived, not persisted: working Tasks use `now - created_at`; terminal/lost Tasks use `updated_at - created_at`. `updated_at` changes when Task state changes, not on a no-op refresh, so terminal elapsed time stays stable.

Automatic TrackedTasks appended to unrelated `@dive` / `@c` results adds only the compact readable text and does not merge Task objects into the tool's existing structured result. Explicit `task_list()` is the structured inspection surface. Automatic output may be bounded to protect foreground context; selection limits are rendering policy, not Task-domain state.

### 9.1 Preserve the primary tool result

TrackedTasks is appended to the existing MCP tool result using the same general seam already used by periodic reminder injection.

```text
original CallToolResult unchanged
+
small supplemental TrackedTasks TextContent
```

Do not wrap every tool result in a new generic JSON envelope.

If awareness projection itself fails, preserve the primary tool result and emit at most a small explicit awareness-unavailable warning. Task awareness must not break unrelated foreground work.

---

## 10. Task controls

Normal Task controls live behind Code Mode capabilities rather than adding several new top-level MCP tools.

Required operations are conceptually:

```text
task_list()
task_collect(task_id)
task_cancel(task_id)
task_ack(task_id)
```

Exact capability names/signatures are implementation details verified against live CAPABILITIES when implemented. v1 does not add a separate `task_get`; `task_list()` already exposes complete structured Task objects.

### 10.1 `task_list`

Refresh locally and return all outstanding Tasks as complete structured TrackedTask objects, plus optional human-readable rows for direct model use.

### 10.2 `task_collect`

```text
working   → not ready
completed → retained result
failed    → retained failure evidence when available
cancelled → retained cancellation evidence when available
lost      → lost / result unavailable
```

Collection is non-destructive and does not acknowledge the Task.

### 10.3 `task_cancel`

If still running, forward cancellation to the backing Execution. Repeated cancellation should be harmless.

If already terminal or lost, return the current state without inventing another lifecycle.

### 10.4 `task_ack`

Acknowledgement means:

> Web SOL no longer wants this Task in automatic awareness.

For v1, acknowledgement simply removes the Task awareness record once the Task is no longer working.

```text
working   + ack → reject
terminal  + ack → delete Task record / success
lost      + ack → delete Task record / success
```

Ack does not pin, extend, or otherwise control Execution result retention.

---

## 11. Result retention and loss

The backing Execution runtime keeps its normal result retention policy.

Task awareness does **not** pin results indefinitely.

Therefore this is legal:

```text
Task completed
        ↓
SOL ignores it for long enough
        ↓
Execution result ages out
        ↓
Task becomes lost / collect reports lost
```

This is intentional. v1 prefers a small runtime over indefinite retention coordination.

No automatic recovery is attempted.

---

## 12. `/peer-review` canary

The first real acceptance consumer is `/peer-review` because reviewer latency caused the original blocking pain.

Use a cheap Haiku-class peer model for lifecycle testing.

```text
/peer-review
    ↓
background Code Mode + label
    ↓
Task [working]
    ↓
SOL continues other work
    ↓
later ordinary tool call
    ↓
Task [completed]
    ↓
collect
    ↓
ack
```

The canary validates non-blocking Task awareness, not reviewer intelligence.

After that path works, long AGY workflows can use the same background Code Mode + Task mechanism. No AGY-specific Task runtime is required.

---

## 13. Conduit

Conduit consumes the same Task registry and TrackedTasks projection.

It must not keep a second long-term Task-tracking SSOT once migration is complete.

Conduit-specific conversation concepts such as Mirrored Full Output and Turn Marker remain Conduit-owned. Task/Execution/TrackedTasks remain Runtime-owned.

No `source=dive|conduit` field is required for v1 Task semantics.

---

## 14. Native MCP Tasks

Native MCP Tasks integration is **deferred from v1**.

The internal Task model should remain simple and should not mirror an external protocol schema merely in anticipation of future client negotiation.

If native MCP Tasks becomes useful later, it can be implemented as a projection/adapter over the established Task model.

---

## 15. Explicitly removed over-design

The following ideas were explored during grilling and are deliberately **not part of v1**.

| Removed design | Why it is out |
|---|---|
| `start_key` + launch fingerprint + atomic creation claim | Response-loss dedupe became a small idempotency subsystem with little value for the core problem. |
| durable `Runner` / `RunnerRegistry` | Fresh-session decoder selection is unnecessary when each Execution persists one normalized outcome. |
| startup orphan reconciliation / creation grace recovery | Crash repair is fallback complexity; orphan Execution is allowed to die under its own timeout. |
| unhandled result pin/unpin | Couples awareness to retention and can retain data forever. Normal Execution retention is enough. |
| handled Task retention lifecycle | `ack` can simply remove awareness. No `handled_at` state machine is needed. |
| Task `source` provenance | Shared registry is enough; provenance is diagnostic logging, not Task domain state. |
| structured progress/status subsystem | v1 keeps only optional `status_cmd` + static `status` display text; no progress phases, percentages, persistence protocol, or worker-to-Task update API. |
| `shell_task` / `code_task` / agent-specific Task launcher hierarchy | Reuse background Code Mode rather than creating parallel launch abstractions. |
| native MCP Tasks v1 integration | Not required for ChatGPT Web Task awareness. |
| detailed TrackedTasks ordering/fairness rules | Compact bounded rendering is implementation policy, not an architectural invariant. |

This simplification is intentional:

```text
prefer ordinary failure over fallback
prefer lost over recovery
prefer existing primitive over new abstraction
prefer one useful field over a new subsystem
```

---

## 16. Rejected alternatives

### Keep only Execution handles

Rejected because Web SOL can forget detached work across turns/sessions.

### Merge Task into Execution

Rejected because process/runtime lifecycle and Web-SOL awareness are different concerns.

### Create a second JobManager-like TrackedTask manager

Rejected. Task persistence is only a small awareness registry.

### Make progress text the lifecycle SSOT

Rejected. Machine lifecycle remains a small explicit state.

### Build recovery for lost Tasks

Rejected. Missing backing state becomes `lost`; no reconstruction or remote polling occurs.

### Preserve permanent JobManager/job_id compatibility

Rejected. The existing implementation may remain during the first functional rollout, but later terminology cleanup does not need permanent dual aliases or old-state readers.

---

## 17. Runtime invariants

v1 implementation must preserve these rules:

1. Long model-visible background work has a Task with a human-readable label.
2. v1 uses one Task per one Execution.
3. `task_id` and `execution_id` are distinct identities.
4. Existing background execution paths are reused rather than replaced by a new launcher framework.
5. Task persistence is a small SQLite awareness registry; Execution persistence remains separate.
6. Background Execution exposes one normalized terminal outcome; no durable Runner/collector registry exists.
7. Missing backing Execution/result becomes `lost`; v1 performs no automatic recovery.
8. Ordinary tool traffic refreshes outstanding Tasks using local evidence only.
9. TrackedTasks is supplemental and does not mutate primary tool result contracts.
10. `task_list()` exposes complete structured TrackedTask objects; automatic `@dive` / `@c` awareness adds compact text only.
11. Optional `status_cmd` or static `status` decorates display only and never owns lifecycle state.
12. Elapsed time and `status_label` are derived and are not persisted Task state.
13. Collection is non-destructive and does not imply acknowledgement.
14. Ack removes Task awareness and does not manage result retention.
15. Normal Execution retention may cause an ignored Task/result to become lost.
16. No start-key/idempotency, structured progress, runner registry, or recovery subsystem exists in v1.
17. Current runtime code and public lifecycle identity use Execution / `execution_id`; no permanent Job compatibility layer remains.

---

## 18. Implementation order

```text
1. Add minimal SQLite TaskStore.
2. Extend existing code_mode(background=True) so a label creates and returns a Task while reusing the current background runtime.
3. Persist one normalized Execution terminal outcome usable after reconnect.
4. Add task_list / task_collect / task_cancel / task_ack Code Mode capabilities.
5. Add optional status_cmd / static status display and derived elapsed time.
6. Append compact TrackedTasks text after ordinary tool calls using the existing result-content middleware seam.
7. Verify fresh-session rediscovery and lost behavior.
8. Convert /peer-review to the Task-backed background Code Mode path using a cheap Haiku-class canary.
9. Convert long AGY workflows to the same path.
10. Point Conduit at the shared TaskStore and remove duplicate tracking metadata.
11. Completed: clean Job terminology into Execution terminology and update current runtime/API/docs without permanent compatibility aliases.
```

Native MCP Tasks, structured progress, launch idempotency, and recovery remain outside this v1 implementation sequence.

---

## 19. Acceptance tests

### Non-blocking

```text
[ ] /peer-review background start returns immediately
[ ] SOL can continue foreground Code Mode/tool work while review runs
[ ] ordinary later tool output shows the Task without explicit polling
```

### Task awareness

```text
[ ] background start returns task_id/label/state
[ ] task_list returns complete structured TrackedTask objects
[ ] task_list may also return compact readable rows without discarding structured fields
[ ] standard rows render label · state · derived elapsed time and optional status text
[ ] status_cmd stdout such as `TODOS 3/9` can decorate a visible working Task
[ ] absent/failing/empty status_cmd falls back to static status when present, otherwise no status decoration
[ ] status display failure never changes Task.state
[ ] no-op refresh does not change updated_at or terminal elapsed time
[ ] a fresh ChatGPT session can rediscover retained outstanding Tasks
[ ] completed/failed/cancelled states refresh from local Execution state
[ ] missing Execution/result becomes lost
[ ] lost does not trigger recovery, remote polling, or reconstruction
```

### Result and handling

```text
[ ] collect on working reports not-ready
[ ] collect on completed returns retained result
[ ] collect on failed/cancelled returns retained evidence when available
[ ] collect on lost reports unavailable/lost
[ ] collect is repeatable while the Execution result exists
[ ] ack rejects working
[ ] ack removes terminal/lost Task awareness
[ ] ack does not extend or pin result retention
```

### Contract preservation

```text
[ ] primary MCP tool result remains structurally compatible
[ ] ordinary @dive / @c results append compact TrackedTasks text without merging Task objects into existing structuredContent
[ ] explicit task_list exposes the structured Task objects when needed
[ ] no ordinary TrackedTasks text exposes PID/backend/raw command or status_cmd itself
[ ] no runner registry, start claim, structured progress subsystem, or recovery subsystem is introduced
```

### Migration cleanliness

```text
[x] after terminology cleanup, current runtime code/docs use Execution/execution_id terminology consistently
[x] no permanent JobManager/job_id compatibility shim remains
[x] no duplicate Conduit Task SSOT remains after migration
[x] long agent skills use the shared background Code Mode Task path rather than separate Task launcher frameworks
```

---

## 20. Final architecture

```text
                         ChatGPT Web SOL
                                │
                       ordinary tool calls
                                │
                                v
                       +----------------+
                       | TrackedTasks[] |
                       +-------+--------+
                               │
                               v
                         SQLite TaskStore
                               │
                         execution_id
                               │
                               v
                       Execution runtime
                               │
                    existing durable machinery
                               │
                       normalized result
```

Launch path:

```text
code_mode(background=True, label="...")
           │
           ├── Execution
           └── Task

return immediately → SOL continues → later TrackedTasks → collect → ack
```

Failure philosophy:

```text
missing backing state → lost
lost                  → stays lost
recovery              → not a v1 feature
```

The guiding rule is:

> **Reuse the existing background execution primitive. Add only enough durable Task awareness so Web SOL can keep working without forgetting detached work.**
