---
title: ADR - Task, Execution, and TrackedTasks Runtime Model
created: 2026-08-21
updated: 2026-08-21
type: decision
status: proposed
---

# ADR 0001 - Task, Execution, and TrackedTasks Runtime Model

## Decision summary

GPT Dive adopts **Task** and **Execution** as separate runtime concepts for durable asynchronous work.

The design exists to solve a concrete ChatGPT Web workflow problem: long-running peer review and delegated agent calls must not block Web SOL while it waits for a remote/model response, but once detached they must also not be forgotten across later tool calls or fresh ChatGPT sessions.

The canonical split is:

```text
Task
= meaningful asynchronous work Web SOL must remain aware of

Execution
= the durable runtime instance that actually performs that work

TrackedTasks
= the compact Web SOL-facing projection of unhandled Tasks
```

The normal Web-facing path is therefore:

```text
Web SOL
   |
   | start meaningful long work
   v
TaskManager
   |
   | creates durable Task + backing Execution
   v
ExecutionManager
   |
   +------------------------------> worker / process / agent
   |
   +---- control returns immediately to Web SOL

Web SOL continues foreground work
   |
   | ordinary @dive / @c calls
   v
TrackedTasks[]
   |
   +--> working
   +--> completed but unhandled
   +--> failed / cancelled
```

The low-level Execution remains available for diagnostics and control, but ordinary Web SOL returns expose **TrackedTasks only**. Web SOL should reason about delegated work, not routinely reason about PIDs, systemd units, process envelopes, or execution internals.

This ADR promotes a concept discovered while building Conduit into the **GPT Dive Runtime** domain. Conduit is a consumer of this runtime model, not its owner.

### Simplification rule: no recovery subsystem

v1 deliberately does **not** build a recovery/reconstruction subsystem for lost detached work. If the backing Execution or retained result is no longer available, the Task is treated as failed with a lost diagnostic; GPT Dive does not reconstruct it, rediscover provider semantics, reclaim orphan work, or retry it automatically. A new attempt is a new Task.

This decision supersedes earlier draft language in this ADR that proposed durable `runner`-based recovery, startup orphan reconciliation, or other recovery-oriented machinery. Those mechanisms are removal candidates during the simplification pass.

---

## 1. Problem that caused this design

The original pressure was not abstract task orchestration. It was the practical cost of synchronous peer review.

Before this design, a workflow such as `/peer-review` effectively looked like:

```text
Web SOL
   |
   +--> send peer-review request
           |
           | wait for remote/model response
           | 30 seconds ... minutes
           v
         result

During the wait:
Web SOL foreground progress = blocked
```

That is especially wasteful for review, research, and delegated-agent work because Web SOL usually has useful independent work it can continue while the external worker is thinking.

Detaching the call solves only half the problem:

```text
start background work
       |
       +--> return execution handle
       |
Web SOL continues
```

Now Web SOL must remember:

```text
- what was launched;
- which opaque handle belongs to it;
- whether it is still running;
- whether it completed;
- whether its result was already inspected;
- whether it still matters;
- whether a fresh ChatGPT session needs to rediscover it.
```

A durable execution handle alone therefore does not solve the human/model awareness problem.

The decisive distinction is:

```text
execution terminal != Web SOL handled
```

A peer review may be fully complete while still needing to remain visible because Web SOL has not yet inspected, discarded, deduplicated, or incorporated its result.

This is the runtime foundation for the Conduit concept previously called **Opportunistic Evidence Pickup (OEP)**: detach work, continue useful foreground work, notice completion opportunistically through later ordinary tool activity, and pick up the result only when useful.

---

## 2. Scope and ownership

This is a **GPT Dive Runtime ADR**.

The concepts apply to:

```text
@dive
@c / Conduit
background Code Mode
peer-review
AGY workers
long durable shell work
future asynchronous workers/runners
native MCP Tasks projection when negotiated
```

They do not belong to Conduit specifically.

```text
                    GPT Dive Runtime

               TaskManager / Task
                       |
               ExecutionManager
                       |
            durable execution backend

        +--------------+---------------+
        |              |               |
      @dive            @c         agent skills
```

`@dive` and `@c` may use different tunnels and transport surfaces. That does not create different Task domains. Their Tasks share the same durable runtime registry. The creating surface is recorded as provenance metadata (`source`) only.

---

## 3. Canonical domain language

### 3.1 Task

A **Task** is meaningful asynchronous work that Web SOL should remain aware of until it reaches a terminal state and is explicitly handled.

Examples:

```text
"Review Task/Execution ADR"
"AGY implementation review"
"Search repository for protocol regressions"
```

A Task is not a process DTO and is not a renamed Job.

### 3.2 Execution

An **Execution** is the durable runtime instance that performs a Task.

It owns low-level concerns such as:

```text
launch
process/runtime lifetime
backend identity
stdout/stderr or runtime envelope
exit observation
timeout
cancel signalling
result retention
runtime recovery
```

The canonical identifier is:

```text
execution_id
```

OS PIDs are backend details and are not durable identity. PID reuse, process termination, systemd-backed execution, and post-process result retention make PID unsuitable as the public execution identifier.

### 3.3 TrackedTasks

**TrackedTasks** is the compact projection of Tasks that Web SOL still needs to remain aware of.

It is not a second TaskManager or ExecutionManager.

```text
canonical Task records
        |
        v
compact TrackedTasks projection
        |
        v
Web SOL awareness
```

### 3.4 Awareness lifecycle

Task execution lifecycle and Web SOL handling lifecycle are separate.

```text
Task execution:
working -> completed
        -> failed
        -> cancelled

Awareness:
unhandled -> handled
```

A legal and important state is:

```text
Task.state = completed
handled_at = null
```

That Task remains in automatic TrackedTasks until explicit acknowledgement.

---

## 4. v1 Task model

The v1 canonical Task is deliberately small.

Conceptually:

```python
Task:
    task_id: str
    execution_id: str
    source: str
    label: str
    start_key: str | None
    state: TaskState
    status_cmd: str | None
    created_at: datetime
    updated_at: datetime
    handled_at: datetime | None
```

### 4.1 `task_id`

`task_id` is an independent durable identity, generated independently from `execution_id`.

Recommended implementation:

```text
uuid4().hex
```

The architecture must not depend on:

```text
task_id == execution_id
```

Even while v1 uses a 1:1 Task/Execution relationship, the identities represent different concepts.

### 4.2 `execution_id`

`execution_id` points to the Task's backing Execution.

It is intentionally hidden from the ordinary compact TrackedTasks projection. It is exposed through explicit Task detail/diagnostic inspection when Web SOL needs to descend into runtime internals.

### 4.3 `source`

`source` records where the Task originated, for example:

```text
dive
conduit
```

The database should treat it as a string rather than a closed enum so a future surface can add another provenance value without a schema migration.

`source` is provenance metadata only. It does not control lifecycle semantics, visibility, ownership, or authorization inside the trusted GPT Dive runtime. A Task created through one surface may be inspected, collected, acknowledged, or cancelled through another surface.

Default TrackedTasks awareness and control are global across sources:

```text
@dive ordinary return -> sees unhandled dive + conduit Tasks
@c ordinary return    -> sees unhandled dive + conduit Tasks
```

Filtering by source may exist for diagnostics or explicit queries, but source-specific visibility must not recreate the forgotten-background-work problem.

### 4.4 `label`

`label` answers:

```text
"What work is this?"
```

The creating SOL/runtime chooses it at Task creation time. It is stable for the Task lifetime in v1.

Examples:

```text
Review Task/Execution ADR
AGY provider refactor
Repository protocol audit
```

Dynamic progress does not belong in `label`.

### 4.5 `start_key`

`start_key` is optional retry-deduplication metadata for detached launch. It is not Task identity and is not shown in ordinary TrackedTasks. When a caller intentionally retries a launch with the same effective key, the runtime returns the existing Task instead of creating a duplicate Execution.

Its idempotency namespace is `(runner, start_key)`. `source` is deliberately excluded because source is provenance only: the same retry may arrive through `@dive` or `@c`. Reusing a key under another runner is a separate launch.

A retry with the same `(runner, start_key)` must also match the original effective launch specification. The registry stores an internal launch-spec fingerprint for conflict detection. Matching fingerprint returns the existing Task; a different fingerprint fails explicitly with `start_key_conflict`. The fingerprint is validation metadata only and must never be used to synthesize `start_key`.

Do not derive `start_key` automatically from label, command, prompt, or hashes of launch arguments: two intentionally separate runs may legitimately have identical inputs. A caller that needs retry-safe launch supplies an opaque key explicitly. Completed idempotency claims live with the retained Task and may be removed when that handled Task ages out under normal retention, after which the same opaque key may be reused for a new launch.

### 4.6 `state`

`state` is the machine-readable lifecycle SSOT.

v1 has exactly:

```text
working
completed
failed
cancelled
```

Do not add `input_required`, `paused`, `retrying`, `stale`, `collecting`, `acked`, or provider-specific states until a real runtime lifecycle requires them.

The state vocabulary is deliberately smaller than possible future MCP/A2A/provider vocabularies.

Terminal state is immutable in v1:

```text
working -> completed | failed | cancelled
terminal -> another state   forbidden
```

Retry creates a new Task and new Execution rather than reviving a terminal Task. Concurrent refreshers must persist a terminal transition only while the stored state is still `working`, so a later observer cannot overwrite an already accepted terminal state.

### 4.7 `status_cmd`

`status_cmd` is an optional, best-effort display probe.

It exists because different long-running workers expose useful progress in different ways without needing to know the Task database contract.

Examples:

```text
cat /tmp/agy-worker/run-42/status.md
wc -l /tmp/research/run-17/results.jsonl
du -sh /tmp/build/output
stat -c %s /tmp/download/artifact.part
```

The worker may update a file or other observable resource; Task projection executes the probe and renders its stdout as optional status text.

The canonical Task database stores the command, not a duplicated mutable status string.

`status_cmd = null` is fully valid.

`status_cmd` is **not lifecycle state** and must never become a second execution system.

Contract:

```text
optional
short-running
read-only by convention
bounded execution
bounded stdout
best effort
failure has no effect on Task.state
```

Recommended initial budget:

```text
timeout <= 1 second
stdout <= 4 KiB
non-zero exit -> omit status text
timeout       -> omit status text
empty stdout  -> omit status text
```

Only visible unhandled `working` Tasks need status probes. Terminal or handled Tasks do not need continued progress polling.

If several visible Tasks have probes, the implementation may run them concurrently, but TrackedTasks decoration must never meaningfully reintroduce the blocking behavior this architecture was created to remove.

---

## 5. v1 Task-to-Execution relationship

v1 intentionally requires:

```text
1 Task : 1 Execution
```

Although a future Execution might conceptually coordinate several logical Tasks, supporting `1 Execution : N Tasks` immediately creates unresolved control semantics:

```text
If Task A and Task B share Execution E1,
what does cancel(Task A) mean?
Does E1 terminate and kill Task B?
Can Task B survive?
Who owns the shared result?
```

There is no current requirement strong enough to justify that complexity.

Therefore v1 is:

```text
Task T1 ---- Execution E1
Task T2 ---- Execution E2
Task T3 ---- Execution E3
```

The independent identities do not prevent a later cardinality change if a real second use case appears.

Task hierarchy is also excluded from v1. Tasks are flat; no canonical parent/child Task tree exists until actual workflow pressure requires it.

---

## 6. Detached execution invariant

Meaningful detached work must not exist as an anonymous Web SOL-visible Execution.

The runtime invariant is:

> Every normal SOL-visible detached Execution MUST have exactly one durable Task in v1.

Short bounded foreground execution does not require a Task.

```text
short foreground command
    -> no Task required

detached / durable long work
    -> Task required

implementation child process inside an Execution
    -> no additional Task required
```

This prevents the Execution model from slowly absorbing Task semantics such as labels, progress, handling state, and awareness metadata.

A raw detached Execution start is therefore not a normal SOL-facing workflow.

Conceptually:

```text
foreground code_mode                  allowed
Task-backed detached execution        allowed
raw detached Execution from SOL       disallowed normal path
```

`ExecutionManager.start()` remains a lower-level implementation primitive, but agent skills and normal Web-facing detached workflows must start through Task-aware orchestration. The model-facing raw detached launch paths (`code_mode(background=True)` and `wsl2_async(start)`) are removed from the normal Web SOL contract rather than silently creating anonymous Tasks.

Do not add an automatic anonymous-Task fallback. Violations should fail explicitly.

---

## 7. Creation ordering and orphan containment

Successful detached Task creation must be durable before success is returned to Web SOL.

Creation has two paths. Without `start_key`, the simple ordering remains:

```text
1. start backing Execution
2. obtain execution_id synchronously
3. persist durable Task bound to execution_id
4. only then return detached-start success
```

With `start_key`, concurrent duplicate starts must be prevented **before** either caller launches an Execution. The Task registry therefore owns a small atomic creation claim keyed by `(runner, start_key)`:

```text
SQLite transaction
  -> claim (runner, start_key, launch_fingerprint)
       |
       +-- existing completed claim + matching fingerprint -> return existing Task
       +-- existing claim + different fingerprint          -> start_key_conflict
       +-- winner                                           -> start Execution
                                                              -> persist Task
                                                              -> bind claim to task_id
                                                              -> return success
```

The claim is creation-coordination metadata, not a Task lifecycle state. Do not add `starting` to `Task.state` and do not expose incomplete claims in TrackedTasks. An incomplete claim left by a crash is reclaimable/cleanable after a short creation grace period. A completed claim remains associated with its retained Task; when a handled Task is removed by normal retention, its completed claim may be removed as well and the key becomes reusable.

The invariant is:

> A successful detached-start response means both the backing Execution and durable Task record exist.

If Execution creation succeeds but Task persistence fails:

```text
Execution started
      |
Task insert failed
      |
      v
cancel / contain Execution
      |
return explicit failure
```

Do not return success and leave an untracked orphan.

The containment attempt itself should be logged diagnostically if it fails, but the Task start remains a failure.

A process crash can still occur after step 2 and before step 3, before normal containment code can run. Startup/recovery therefore reconciles durable detached Executions against the Task registry. After a short creation grace period, a detached Execution with no bound Task is an orphan and is cancelled/cleaned up. The invariant that normal detached Executions are Task-backed makes an unbound durable Execution a recoverable error signal rather than a valid steady state.

---

## 8. Task state ownership and semantic completion

`Task.state` is written by the GPT Dive Task runtime, not directly by workers and not by `status_cmd`.

```text
worker/provider/runtime evidence
          |
          v
semantic observation/adapter
          |
          v
TaskManager
          |
          v
Task.state
```

Workers do not need database access or knowledge of the Task schema.

### 8.1 Execution state is not automatically Task state

A low-level Execution ending successfully does not necessarily mean the logical Task succeeded.

Background Code Mode already proves this semantic gap:

```text
Execution terminal
    |
read worker stdout envelope
    |
validate protocol
    |
validate envelope.ok
    |
validate exit code
    |
semantic success / failure
```

Therefore this architecture forbids the general rule:

```text
Task.state = Execution.state
```

### 8.2 Normalized propagation

Safe v1 direction:

```text
Execution definitely failed      -> Task failed
Execution definitely cancelled   -> Task cancelled
Execution completed              -> semantic observer decides completed/failed
```

A transient observation error must not fabricate a new lifecycle state.

If an Execution is definitively missing while a Task is still `working`, the Task becomes `failed` rather than introducing a separate `stale` state.

```text
observer temporarily unavailable
    -> retain last known Task.state

backing Execution definitively missing
    -> Task.state = failed
```

### 8.3 Execution runner identity selects semantic observation

Fresh-session recovery must be able to decide which semantic observer/result decoder applies without relying on ChatGPT session memory. The durable Execution therefore owns a stable `runner` identity describing what kind of work it executes, for example `shell`, `code_mode`, `peer_review`, or `agy`.

`runner` is distinct from the process `backend`:

```text
runner  = what semantic runtime is executing
backend = how the local process is kept alive, e.g. systemd or popen
```

`runner` is diagnostic/runtime metadata and is not included in ordinary TrackedTasks.

### 8.4 Adapters must remain earned abstractions

Different workers may need small semantic observation logic, but v1 must not create a decorative class hierarchy merely for symmetry.

Add an adapter/seam only when an actual runner has different success/result semantics.

Examples of real pressure include:

```text
background Code Mode envelope validation
AGY-specific terminal/result semantics
peer-review provider result semantics
plain durable shell execution
```

One adapter for a single implementation is a hypothetical seam; keep the abstraction as small as actual consumers permit.

---

## 9. Cancellation

`cancel(task_id)` controls the Task's backing Execution.

Because v1 is 1:1:

```text
cancel(Task)
     |
record/request cancellation intent
     |
cancel backing Execution
     |
observe actual terminal state
     |
Task.state = cancelled
```

Cancellation is intent followed by observation. Requesting cancellation must not immediately fabricate the terminal `cancelled` state before the runtime observes it.

If the Execution instead finishes before cancellation takes effect, semantic observation determines the actual terminal Task state.

Cancellation is idempotent. Repeating `cancel(task_id)` after cancellation has already been requested must not duplicate destructive side effects. If the Task is already terminal, cancel returns the current terminal outcome without signalling the Execution again. Cancellation intent is Execution/control metadata, not a new Task lifecycle state.

### 9.1 State-sensitive control refresh

Explicit Task controls that depend on lifecycle state perform one local bounded refresh before deciding the operation. This prevents stale SQLite state from producing the wrong answer after the backing Execution has already reached terminal state.

```text
task_collect(T1)
  -> if working, locally observe once
  -> terminal now? collect retained outcome
  -> still working? not-ready

task_ack(T1)
  -> locally observe once
  -> terminal now? acknowledge
  -> still working? reject

task_cancel(T1)
  -> locally observe once
  -> terminal now? do not send cancellation
  -> still working? record intent and cancel Execution
```

The refresh uses only local durable evidence. It does not turn explicit Task control into provider polling.

---

## 10. Result collection and acknowledgement

Result retrieval and Web SOL handling are intentionally independent.

### 10.1 `collect(task_id)` / result retrieval

Collecting is non-destructive and state-sensitive.

```text
working
  -> not-ready error

completed
  -> retained semantic result

failed
  -> retained semantic failure/error evidence

cancelled
  -> retained cancellation/outcome evidence
```

In every terminal case, collection may be repeated and does **not** acknowledge the Task. Failed and cancelled Tasks remain inspectable rather than collapsing to an opaque terminal label.

Task storage does not duplicate the Execution/worker result in v1. Result ownership stays with the execution/worker runtime and its retention mechanism.

### 10.2 `ack(task_id)`

Acknowledgement means:

```text
"Web SOL has handled this terminal Task and no longer needs automatic reminders."
```

`ack` is terminal-only.

```text
working   + ack -> error
completed + ack -> handled_at set
failed    + ack -> handled_at set
cancelled + ack -> handled_at set
```

Acknowledgement does not delete the result and does not immediately delete the Task record. Collection is not a prerequisite for acknowledgement: a terminal Task may be acknowledged without first reading its result when Web SOL deliberately decides the result is no longer useful. `ack` means "stop reminding me about this Task", not "I have read the result".

Acknowledgement is idempotent. Repeating `ack(task_id)` for an already handled Task returns success/already-handled without rewriting the original `handled_at` or repeating retention-release side effects.

### 10.3 Retention

`handled_at != null` removes the Task from automatic TrackedTasks projection.

Physical Task cleanup is a later retention concern.

Execution/result retention remains owned by the Execution/runtime layer, but an unhandled terminal Task pins its backing result: while `handled_at == null`, the result required by `collect(task_id)` must remain retrievable. v1 has **no automatic TTL for this pin**; an unhandled Task may retain its result indefinitely until explicit acknowledgement. After acknowledgement, normal Execution/result retention policy may make it eligible for cleanup. This deliberately prefers reliable later collection over silent disk cleanup. No result-copy column is introduced in the Task database merely to enforce this lifetime rule.

The pin is enforced downward rather than through an Execution-to-Task reverse dependency. Task-aware creation/binding pins the backing Execution result; acknowledgement releases that pin. Execution cleanup only needs to honor its own pin state and does not query TaskStore/TaskManager to rediscover awareness policy on every cleanup pass.

Handled Task records remain explicitly inspectable while their normal Task-retention window lasts. `task_get(task_id)` may therefore return a handled Task including `handled_at`, and `task_collect(task_id)` may still return a retained result if Execution retention has not removed it. Handled Tasks are eligible for normal Task cleanup; unhandled Tasks are not automatically deleted. The exact handled-retention duration is runtime policy rather than a domain invariant.

---

## 11. Durable Task registry

v1 uses SQLite for the Task/awareness registry.

The registry is shared by GPT Dive surfaces such as `@dive` and Conduit even when they run through separate tunnels/processes.

SQLite owns Task awareness state, not duplicated Execution lifecycle state.

Conceptually:

```text
SQLite
└── tasks
    ├── task_id
    ├── execution_id
    ├── source
    ├── label
    ├── start_key
    ├── state
    ├── status_cmd
    ├── created_at
    ├── updated_at
    └── handled_at
```

The Execution runtime remains its own persistence owner.

Do not create a second `executions` SSOT in SQLite merely because Tasks use SQLite.

Rationale:

```text
Task awareness persistence  -> SQLite
Execution/process persistence -> Execution runtime
```

Duplicating both would create competing durable owners for the same execution lifecycle.

PGlite/Postgres-in-WASM is not needed for this control-plane registry. The required workload is small transactional state, cross-process local access, and simple indexed queries; SQLite is the lower-complexity fit.

---

## 12. Fresh-session recovery and refresh

Task identity is not owned by a ChatGPT conversation session.

A fresh ChatGPT Web session must be able to rediscover outstanding/unhandled work through later ordinary GPT Dive activity.

Snapshot flow:

```text
new/fresh Web session
       |
ordinary @dive or @c call
       |
load unhandled Tasks from durable registry
       |
refresh `working` Tasks against backing Execution/semantic observer
       |
persist newly observed terminal states
       |
render compact TrackedTasks
```

Terminal Tasks do not require repeated execution polling. They remain visible solely because they are unhandled.

Automatic refresh must remain **local and bounded**. It may inspect durable Execution state and locally retained worker envelopes/results, but it must not trigger provider calls, send a new agent request, or perform unbounded remote polling merely to decorate an ordinary tool return. A runner that cannot be refreshed from local durable evidence keeps its last known state until an explicit operation supplies new evidence.

No server-initiated wake-up system is required. Ordinary user/tool activity remains the intentional refresh cadence.

---

## 13. Public TrackedTasks projection

The compact projection should expose only information Web SOL normally needs to maintain awareness.

Recommended shape:

```json
{
  "id": "<task_id>",
  "label": "Review Task/Execution ADR",
  "state": "working",
  "status_label": "2/3 · reviewing lifecycle"
}
```

The optional `status_label` value is the rendered stdout of `status_cmd`; it is not stored as canonical lifecycle state.

When there is no usable probe result:

```json
{
  "id": "<task_id>",
  "label": "Review Task/Execution ADR",
  "state": "working"
}
```

The compact projection should not normally expose:

```text
execution_id
source
status_cmd
pid
systemd unit
backend
cwd
raw command
stdout/stderr
worker prompt
provider/session identifiers
```

### 13.1 Progressive disclosure

When diagnostics are needed:

```text
TrackedTasks
    |
    | task detail requested
    v
Task detail
    +--> execution_id
             |
             | execution detail requested
             v
        Execution detail
             +--> backend / logs / runtime diagnostics
```

Thus Execution remains observable without burdening every normal return.

### 13.2 Bounded projection

Automatic TrackedTasks output must be bounded so a large backlog does not consume model context on every tool call.

Conceptually:

```text
TrackedTasks (8/23)
- ...
- ...
+15 more
```

The exact v1 task-count cap is an implementation constant, not a new domain concept, but the bounded-projection rule is architectural. Per-item text is bounded as well: `label` is at most 80 characters; rendered `status_label` is normalized to a single line and capped at 256 characters. The larger `status_cmd` stdout budget is probe-processing headroom, not permission to inject multi-kilobyte status text into every ordinary tool result.

When the cap is exceeded, ordering is deterministic and biased toward work awaiting a handling decision:

```text
1. terminal + unhandled Tasks (oldest first)
2. working + unhandled Tasks  (oldest first)
3. remaining count rendered as "+N more"
```

This prevents old completed/failed/cancelled evidence from being permanently hidden behind a stream of newer running work.

---

## 14. Ordinary tool result preservation

TrackedTasks awareness is additive metadata/content. It must not mutate existing primary tool result contracts.

Forbidden generic transformation:

```json
{
  "result": "<old tool result>",
  "tracked_tasks": []
}
```

when the original tool previously returned a different machine-readable structure.

Required principle:

```text
original tool result unchanged
+
supplemental compact TrackedTasks content
```

The implementation should use a middleware/projection seam capable of preserving the original MCP `CallToolResult`, `structuredContent`, and error semantics while adding compact awareness text/content. GPT Dive already has this shape in its periodic-reminder middleware: the primary `CallToolResult` is preserved and supplemental `TextContent` is appended after the primary tool action completes.

TrackedTasks snapshotting therefore happens **after** the primary action. A newly started Task can appear in the same return; an acknowledged Task disappears from that same return; cancellation/detail operations expose the latest locally observed state.

A normal tool-level error result (`CallToolResult` with error semantics) still receives TrackedTasks when a usable MCP result exists. Transport/server failure that prevents any usable tool result cannot carry awareness metadata.

TrackedTasks refresh failure must not destroy an otherwise valid primary result. If the Task registry/projection cannot be read, preserve the primary result and append a compact explicit warning such as `TrackedTasks: unavailable` with a bounded diagnostic reason. Do not silently reuse a stale snapshot, and do not convert an unrelated successful tool action into failure solely because supplemental awareness could not be rendered.

TrackedTasks must not become the reason existing integrations break.

---

## 15. Relationship between `@dive` and `@c`

`@dive` and `@c` use different tunnel/control surfaces, but both should read the same durable Task domain.

```text
                 shared Task registry
                        |
             +----------+----------+
             |                     |
          @dive tunnel          @c tunnel
             |                     |
        source=dive          source=conduit
```

The normal snapshot is global, not source-isolated.

Conduit-specific tracking should be removed once the shared Task runtime is proven. Conduit becomes a thin consumer/control surface rather than maintaining its own second tracking lifecycle.

Any existing `conduit.json` or equivalent tracking metadata may be removed during migration. Do not preserve duplicate durable tracking indefinitely.

---

## 16. Relationship to native MCP Tasks

The GPT Dive Task domain is canonical. Native MCP Tasks is a protocol projection for clients that negotiate the extension.

```text
GPT Dive Task domain
        |
        +--> TrackedTasks -> ChatGPT Web awareness
        +--> @c projection
        +--> MCP Tasks adapter -> negotiated MCP clients
```

Do not copy the evolving MCP Tasks wire schema into the internal Task model.

GPT Dive's v1 Task vocabulary remains intentionally smaller and stable. Protocol-specific states, polling fields, TTL syntax, result envelopes, and request identifiers belong in the MCP adapter unless proven to be genuine GPT Dive domain concepts.

---

## 17. Execution terminology and removal of JobManager compatibility

The canonical runtime language is:

```text
ExecutionManager
Execution
execution_id
```

The pre-ADR implementation uses:

```text
JobManager
Job
job_id
```

This ADR does **not** require backward compatibility with that naming or persisted old Job contract.

Do not add:

```text
legacy job_id aliases
dual Job/Execution public terminology
compatibility adapters solely for old JobManager
old-state migration readers
new APIs that continue exposing job_id
```

The implementation should cleanly remove or replace the old Job-facing contract. Existing legacy persisted runtime state may be deleted or left outside the new runtime path as appropriate; the new architecture does not need to understand or migrate it.

The model-facing raw async surface is removed rather than renamed in place:

```text
code_mode(background=True) / action / job_id   -> removed from normal Web MCP contract
wsl2_async                                      -> removed as a top-level Web MCP tool
```

The stable Web MCP surface after this migration is intentionally smaller:

```text
bootstrap
code_mode      # foreground programmable root + Task/Execution capabilities
wsl2_sync      # exceptional short synchronous path
```

Low-level Execution lifecycle remains available behind Code Mode capabilities for Task-aware orchestration and diagnostics; it is not exposed as an anonymous detached-start shortcut.

The goal is a clean model, not a permanent compatibility layer for an internal design that is being replaced.

Implementation may reuse proven low-level process-management code from the current JobManager, but once moved into the new runtime it should use the Execution terminology consistently.

---

## 18. TaskManager is not a generic shell launcher

TaskManager owns Task orchestration and awareness lifecycle. It must not become a god-object that accepts arbitrary shell commands as its primary public contract.

Avoid:

```text
task.start(command="...")
```

as the universal orchestration abstraction.

Instead, concrete launchers understand how to start their work and bind it to a Task:

```text
peer-review launcher ---+
AGY launcher -----------+--> Task-aware detached start
Code Mode launcher -----+
future worker launcher -+
```

The common Task runtime owns the durable Task record, lifecycle normalization, tracking, collection, acknowledgement, cancellation, and connection to `execution_id`.

Normal Web SOL control is exposed through Code Mode capabilities rather than new top-level MCP tools. The Task control surface provides operations equivalent to `task_get`, `task_collect`, `task_cancel`, and `task_ack`; exact live capability names/signatures are implementation contracts and must be verified when implemented. Task creation remains with concrete Task-aware launchers rather than a universal `task_start(command=...)` shell API.

Worker-specific execution policy stays with the worker/launcher rather than being collapsed into TaskManager.

`Execution.runner` is a stable registry key used to recover semantic behavior across process and ChatGPT-session boundaries, for example `shell`, `code_mode`, `peer_review`, or `agy`. It is not a display label. The runtime resolves it through a runner registry that supplies the applicable observe/collect semantics. An unknown runner is a definitive semantic failure: a still-working Task becomes `failed`, `collect` returns the unknown-runner diagnostic plus retained Execution evidence, and the Task can then be acknowledged. It must never silently fall back to shell semantics or remain permanently stuck in `working`.

### 18.1 Concrete detached launchers

Removing the raw async API does not remove long-running shell or Code Mode work. It replaces anonymous detached starts with concrete Task-aware launchers exposed behind Code Mode.

```text
long arbitrary shell  -> shell_task launcher -> Task + Execution(runner="shell")
long Monty/Code Mode  -> code_task launcher  -> Task + Execution(runner="code_mode")
peer review           -> peer-review launcher -> Task + Execution(runner="peer_review")
AGY                   -> AGY launcher         -> Task + Execution(runner="agy")
```

The names `shell_task` and `code_task` describe the intended capability roles; exact live capability names/signatures are implementation contracts to verify when implemented.

Agent launchers must preserve their own semantic runner identity even when their physical launch ultimately uses a shell process. AGY must not be flattened into `runner="shell"`, because fresh-session observation, result interpretation, and provider continuation semantics differ from plain shell execution.

Every detached launcher requires a non-empty human-readable `label`. Do not synthesize anonymous labels from command text as a fallback; a Task exists specifically so Web SOL can remember what meaningful work it delegated.

`source` is injected by the calling runtime surface (`dive`, `conduit`, or a later trusted surface), not supplied as an arbitrary model/worker argument. It records provenance rather than authority.

`status_cmd` remains an optional launcher input and is persisted on the Task for bounded local display observation. `timeout`, command/program payload, cwd, provider/session settings, and other execution controls belong to the concrete launcher/Execution layer rather than the Task awareness record.

Detached launchers may also accept an optional opaque `start_key` for retry-safe creation. If a launch response is lost and the caller intentionally retries with the same `(runner, start_key)` and matching launch fingerprint, the runtime returns the already-created Task rather than starting a duplicate Execution. A conflicting fingerprint fails explicitly. `start_key` is not `task_id`, is hidden from TrackedTasks, and is never synthesized automatically from command/prompt/label content.

A successful detached launch returns Task-level information only, conceptually:

```json
{
  "task_id": "<task_id>",
  "label": "Review runtime ADR",
  "state": "working"
}
```

Ordinary launch results do not expose `execution_id`, runner, backend, PID, or other low-level execution details. Explicit Task detail is the entry point for diagnostic descent. The post-action TrackedTasks middleware may additionally show the new Task in the same tool return.

---

## 19. First implementation canary

The first acceptance consumer is `/peer-review`, because peer-review waiting was the original blocking pain that caused this design.

The runtime canary should use a **cheap model such as Haku or an equivalently inexpensive peer model**, not an expensive Opus-class reviewer.

The first canary tests runtime behavior, not reviewer intelligence.

```text
cheap peer-review request
       |
create Task + async Execution
       |
return control immediately to Web SOL
       |
Web SOL keeps working
       |
ordinary @dive return shows Task [working]
       |
peer finishes
       |
later ordinary return shows Task [completed]
       |
collect result
       |
ack
       |
Task disappears from automatic TrackedTasks
```

Only after this path proves the core lifecycle should broader consumers such as AGY and Conduit migrate to the same primitive.

Expensive peer review may later be used to review architecture quality, but it is not required to validate non-blocking lifecycle mechanics.

---

## 20. Agent skill integration

Agent skills are consumers of the Task/Execution runtime contract.

Long-running peer/agent skills should no longer force Web SOL to synchronously wait merely because their underlying provider call is synchronous in isolation.

For agent run directories, progress may remain worker-owned and simple:

```text
run-dir/
├── status.md
├── final.md
└── logs/
```

The Task can use:

```text
status_cmd = "cat <run-dir>/status.md"
```

or another cheap read-only probe.

The agent itself does not need to know the Task database or update Task state directly.

Provider-specific continuation/session identifiers such as AGY `conversation_id` remain provider/runtime details and do not replace `task_id` or `execution_id`.

---

## 21. CAPABILITIES and operational documentation consequences

Introducing Task/Execution as the runtime model requires more than core code changes.

The implementation rollout must reconcile:

```text
Code Mode CAPABILITIES
agent invocation skills
peer-review skill
AGY worker skills
runtime architecture docs
Conduit docs
bootstrap/reminder guidance where relevant
MCP Tasks adapter
existing background Code Mode lifecycle contract
existing low-level async shell contract
```

Documentation must not continue teaching Web SOL to start anonymous raw detached Jobs after the runtime invariant forbids them.

Live capability contracts remain authoritative for actual callable names and arguments during migration.

---

## 22. Rejected alternatives

### 22.1 Keep only Job/Execution handles and make SOL remember them

Rejected because it solves detached execution but not awareness.

```text
execution_id returned
       |
SOL must remember it manually
       |
turn/session changes
       |
forgotten work
```

The original problem reappears.

### 22.2 Put Task semantics directly into Execution

Rejected because Execution would accumulate:

```text
label
progress text
handled/ack state
Web awareness
provider semantics
```

and become a renamed Task/Job hybrid.

Execution should stay the lower-level durable runtime concept.

### 22.3 Show `Execution` in every ordinary return

Rejected because Web SOL normally cares about meaningful work, not execution implementation details.

Execution is available for explicit diagnostic descent only.

### 22.4 Allow anonymous detached Execution and auto-create fallback Tasks

Rejected because this weakens the invariant and hides caller mistakes.

Long detached Web-visible work must explicitly participate in Task awareness.

### 22.5 Store only a free-form `status` string

Rejected because machine lifecycle would have to infer terminality from arbitrary values such as:

```text
"done"
"finished"
"3/3"
"complete"
"끝남"
```

`state` is the machine SSOT; progress/display is optional decoration.

### 22.6 Store a mutable `status_label` value in the Task DB

Rejected for v1 in favor of `status_cmd` because workers expose progress through heterogeneous low-cost observations and should not need Task DB access.

The projection can render status text without making mutable display state canonical.

### 22.7 Make `status_cmd` determine lifecycle state

Rejected because the display probe is intentionally best effort and may fail, time out, be absent, or lag behind reality.

### 22.8 Copy Execution state directly into Task state

Rejected because background Code Mode already demonstrates that process completion is not equivalent to semantic success.

### 22.9 Persist Tasks and Executions together as duplicate SQLite SSOTs immediately

Rejected because the current execution runtime already owns durable execution state. Duplicating it creates consistency and recovery ambiguity without a proven need.

### 22.10 Use PGlite for the Task registry

Rejected for v1 because the registry requires simple local transactional durability, not a Postgres-compatible embedded data platform. SQLite has lower operational and runtime complexity.

### 22.11 Isolate TrackedTasks by tunnel/source

Rejected because a Task launched through one surface could again be forgotten while Web SOL uses another.

### 22.12 Make Conduit own the universal Task model

Rejected because the same problem applies to `@dive`, background Code Mode, peer-review, AGY, and future runners. The domain belongs in GPT Dive Runtime.

### 22.13 Mirror MCP Tasks as the canonical internal model

Rejected because native Tasks negotiation is client/protocol-dependent and evolving. GPT Dive's internal lifecycle must remain stable and smaller.

### 22.14 Preserve JobManager/job_id backward compatibility

Rejected explicitly. This is an internal runtime redesign, and permanent compatibility aliases would preserve duplicate terminology and force future code to reason about obsolete contracts.

### 22.15 Support shared Execution with multiple Tasks in v1

Rejected until a real use case justifies the cancellation/result/ownership semantics.

### 22.16 Add Task parent/child hierarchy in v1

Rejected because no current requirement requires it. Keep the public awareness list flat.

---

## 23. Runtime invariants

The implementation must preserve all of the following:

1. **Meaningful normal detached work has a durable Task.**
2. **v1 uses exactly one backing Execution per Task.**
3. **`task_id` and `execution_id` are independent identities.**
4. **Detached-start success is returned only after the Task is durably persisted.**
5. **If Task persistence fails after Execution start, the Execution is cancelled/contained and start fails.**
6. **`Task.state` is the lifecycle SSOT.**
7. **Workers do not write Task lifecycle state directly.**
8. **`status_cmd` is optional display observation only.**
9. **`status_cmd` failure never fails a Task.**
10. **Execution completion is not blindly copied to semantic Task completion.**
11. **Collect/result retrieval is non-destructive.**
12. **Collect does not imply acknowledgement.**
13. **Acknowledgement is terminal-only.**
14. **Acknowledgement hides a Task from automatic snapshots without immediately deleting its retained result.**
15. **Unhandled terminal Tasks remain visible across turns and fresh sessions.**
16. **Default TrackedTasks awareness spans `@dive` and `@c` sources.**
17. **Ordinary returns expose Task awareness, not low-level Execution internals.**
18. **TrackedTasks injection preserves the primary tool result contract.**
19. **Automatic TrackedTasks output is bounded.**
20. **The canonical runtime terminology is Execution/ExecutionManager/execution_id; no Job compatibility layer is required.**
21. **Terminal Task state is immutable; retry creates a new Task/Execution.**
22. **`source` is provenance only; trusted GPT Dive surfaces share Task visibility and control.**
23. **Durable Execution metadata preserves `runner` identity so fresh-session semantic observation is deterministic.**
24. **Unhandled terminal Tasks pin their backing result until acknowledgement.**
25. **Startup/recovery reconciles and contains detached Executions that remain unbound to any Task after the creation grace period.**
26. **Normal Web SOL Task control is exposed through Code Mode capabilities; raw detached launch is not a model-facing fallback.**
27. **Bounded TrackedTasks prioritizes terminal unhandled Tasks before working Tasks, oldest first within each group.**
28. **A terminal Task may be acknowledged without prior collection; acknowledgement means awareness is handled, not result-read confirmation.**
29. **Collect is state-sensitive: working is not-ready; completed/failed/cancelled return their retained semantic outcome evidence.**
30. **Automatic refresh is local and bounded; ordinary tool returns never trigger provider/agent remote polling.**
31. **The model-facing raw async API is removed: no `code_mode(background=True)` lifecycle fields and no top-level `wsl2_async`.**
32. **Unhandled result pinning has no automatic TTL in v1; explicit acknowledgement releases normal retention eligibility.**
33. **`Execution.runner` is a stable registry key; unknown runners fail explicitly rather than falling back to another runner.**
34. **Long shell and long Code Mode work remain available only through concrete Task-aware launchers, not raw detached execution.**
35. **Agent launchers preserve semantic runner identity even when implemented on top of shell/process execution.**
36. **Every detached Task launcher requires a non-empty human-readable label.**
37. **`source` is injected by the trusted runtime surface and is not caller-controlled launcher data.**
38. **`status_cmd` is optional launcher input; timeout and other execution controls remain Execution/launcher concerns.**
39. **Task awareness owns the retention decision, but Execution enforces result pins without a reverse Execution-to-Task dependency.**
40. **TrackedTasks refresh failure preserves the primary tool result and emits an explicit bounded awareness-unavailable warning; stale snapshots are not silently reused.**
41. **State-sensitive Task controls perform a local bounded refresh before deciding collect/ack/cancel behavior.**
42. **Automatic TrackedTasks snapshotting occurs after the primary tool action so the same return reflects newly started, acknowledged, or locally updated Tasks.**
43. **Usable tool-level error results still carry TrackedTasks; transport/server failures with no usable result cannot.**
44. **A definitive unknown runner converts a still-working Task to failed and preserves diagnostic Execution evidence for collection.**
45. **`task_ack` is idempotent: retrying an already handled Task succeeds without rewriting `handled_at` or repeating unpin side effects.**
46. **`task_cancel` is idempotent: repeated cancellation does not duplicate destructive signals, and terminal Tasks are returned without re-cancelling.**
47. **Detached launch supports an optional caller-supplied `start_key` so response-loss retries can return the existing Task instead of starting duplicate work.**
48. **Handled Tasks remain explicitly inspectable until normal handled-task retention removes them; unhandled Tasks are not auto-deleted.**
49. **Detached launcher success exposes Task-level identity/state only; Execution internals require explicit diagnostic descent.**
50. **`start_key` idempotency is scoped by `(runner, start_key)`, never by source, and same-key retries with a different launch fingerprint fail explicitly.**
51. **Concurrent keyed starts are serialized by an atomic creation claim before Execution launch; incomplete claims are recovery metadata, not Task state.**
52. **Completed start claims age out with handled Task retention, after which the opaque key may be reused.**
53. **Compact projection bounds per-item text: labels are at most 80 characters and status labels are single-line and at most 256 characters.**

---

## 24. Recommended implementation order

This ADR fixes the architecture but deliberately allows implementation details to evolve under the invariants above.

Recommended order:

```text
1. Introduce Runtime ADR + canonical Task/Execution terminology
2. Implement Task model + SQLite Task store
3. Refactor durable Job runtime into ExecutionManager / execution_id
4. Implement Task-aware detached creation + orphan containment
5. Implement state observation / semantic completion seam for first consumer
6. Implement compact TrackedTasks projection
7. Implement bounded status_cmd observation
8. Preserve original tool returns while appending TrackedTasks
9. Convert /peer-review to Task-backed async using Haku/cheap canary model
10. Acceptance-test non-blocking + collect + ack + fresh-session rediscovery
11. Convert AGY worker flows
12. Replace Conduit-specific tracking with shared TaskManager
13. Reproject native MCP Tasks from the shared Task domain
14. Remove stale JobManager/job_id docs, skills, CAPA guidance, and obsolete tracking artifacts
```

Do not combine unrelated fallback systems or speculative provider abstractions into this migration.

---

## 25. Acceptance tests

The v1 runtime is not considered successfully implemented until all of these behaviors are demonstrated against the real Web SOL workflow.

### Non-blocking peer-review canary

```text
[ ] /peer-review starts through a cheap Haku-class peer model
[ ] start returns control to Web SOL without waiting for peer completion
[ ] Web SOL can perform useful foreground work while review continues
```

### Durable creation

```text
[ ] successful Task start has a durable Task row
[ ] successful Task start has a valid execution_id
[ ] forced Task-store failure after Execution start does not leave a successful anonymous Execution
[ ] orphan containment/cancel path is observable in diagnostics
[ ] crash after Execution creation but before Task insert is repaired by startup/recovery orphan reconciliation
[ ] retrying a detached launch with the same `(runner, start_key)` and launch fingerprint returns the existing Task and does not create a duplicate Execution
[ ] the same opaque start_key under a different runner is a different idempotency namespace
[ ] source does not partition start-key deduplication, so the same retry may be recovered through @dive or @c
[ ] reusing `(runner, start_key)` with a different launch fingerprint fails explicitly with start_key_conflict
[ ] concurrent same-key starts create at most one Execution because the creation claim is acquired before launch
[ ] a crash leaving an incomplete creation claim can be reclaimed/cleaned after the creation grace period without inventing a Task state
[ ] omitting start_key still permits intentionally separate identical launches
[ ] after handled Task retention removes the Task and completed claim, the same opaque start_key can be reused
```

### Awareness

```text
[ ] ordinary @dive return exposes the working peer Task
[ ] ordinary @c return can see the same unhandled global Task registry
[ ] completion is noticed on a later ordinary tool interaction
[ ] completed but unhandled Task remains visible
[ ] fresh ChatGPT session rediscovers an unhandled Task
[ ] fresh-session refresh selects the correct semantic observer from durable Execution.runner metadata
[ ] @dive and @c can inspect/control the same Task regardless of source provenance
[ ] when the projection cap is exceeded, terminal unhandled Tasks are shown before working Tasks and oldest Tasks are not starved
[ ] automatic refresh uses only local durable evidence and does not issue provider/agent polling calls
[ ] TrackedTasks snapshot is taken after the primary action, so a newly started Task is visible immediately and an acknowledged Task is absent immediately
[ ] usable tool-level error results still include TrackedTasks awareness
[ ] Task-registry/projection failure preserves the primary result and appends an explicit bounded TrackedTasks-unavailable warning
[ ] awareness refresh failure never silently reuses an old snapshot as if it were current
```

### State correctness

```text
[ ] semantic worker failure becomes Task failed
[ ] Execution cancellation becomes Task cancelled after observation
[ ] process completion alone does not incorrectly mark a semantically failed worker completed
[ ] transient observation failure does not fabricate Task failed
[ ] definitively missing backing Execution for a working Task becomes failed
[ ] once a Task becomes terminal, concurrent/later observers cannot overwrite it with another lifecycle state
[ ] retry after terminal state creates a new Task and Execution rather than reviving the old Task
[ ] task_collect/task_ack/task_cancel locally refresh a stale working Task before making a state-sensitive decision
[ ] an unknown Execution.runner turns a still-working Task into failed rather than leaving it permanently working
```

### Status probe

```text
[ ] status_cmd can render useful progress text
[ ] missing status_cmd is valid
[ ] failing status_cmd does not change Task.state
[ ] timing out status_cmd does not materially delay the normal tool result
[ ] large status output is bounded
[ ] compact status_label is normalized to one line and capped at 256 characters
[ ] detached Task label rejects values over the 80-character compact-projection limit
[ ] terminal/handled Tasks do not keep running unnecessary progress probes
```

### Result and handling

```text
[ ] collect can retrieve the Task result
[ ] collect can be repeated
[ ] collect does not remove the Task from TrackedTasks
[ ] ack rejects a working Task
[ ] ack succeeds for terminal Tasks
[ ] ack removes the Task from later automatic TrackedTasks
[ ] ack does not immediately destroy the retained result
[ ] completed/failed/cancelled but unhandled Task keeps its backing result collectable
[ ] backing result becomes normally cleanup-eligible only after acknowledgement
[ ] terminal Task can be acknowledged without collecting its result first
[ ] collect on working returns a not-ready outcome
[ ] collect on failed/cancelled returns retained failure/cancellation evidence
[ ] unhandled result remains pinned without automatic TTL until explicit acknowledgement
[ ] Task bind pins the backing Execution result without requiring Execution cleanup to query TaskStore
[ ] acknowledgement releases the Execution result pin and makes normal retention eligibility possible
[ ] repeating ack on an already handled Task succeeds without rewriting handled_at or repeating unpin side effects
[ ] repeating cancel does not duplicate cancellation signalling; terminal Tasks are returned without re-cancelling
[ ] handled Task remains available to explicit task_get until handled-task retention removes the record
[ ] handled Task may still be collected while its Execution result remains retained
[ ] handled Tasks become eligible for normal Task retention cleanup while unhandled Tasks do not auto-expire
```

### Contract preservation

```text
[ ] existing primary @dive tool result remains structurally compatible
[ ] TrackedTasks is appended/supplemental rather than generic result wrapping
[ ] low-level execution fields are absent from ordinary TrackedTasks projection
[ ] explicit Task detail can reveal execution_id for diagnostics
[ ] Code Mode exposes Task get/collect/cancel/ack control capabilities without adding a generic raw task_start(command=...) API
[ ] model-facing code_mode no longer exposes background/action/job_id lifecycle fields
[ ] wsl2_async is no longer exposed as a top-level Web MCP tool
[ ] low-level Execution lifecycle remains reachable only through Task-aware/diagnostic Code Mode capabilities
[ ] unknown Execution.runner fails explicitly and never falls back to shell semantics
[ ] long arbitrary shell work launches through a Task-aware shell launcher with runner="shell"
[ ] detached Monty/Code Mode work launches through a Task-aware code launcher with runner="code_mode"
[ ] AGY/peer-review launchers retain their own semantic runner identity rather than degrading to shell
[ ] detached launch rejects an empty/missing label rather than synthesizing an anonymous Task
[ ] source provenance is injected by the runtime surface rather than accepted as arbitrary launcher input
[ ] status_cmd is optional launcher input while timeout remains an Execution/launcher setting
[ ] successful detached launch returns task_id/label/state without exposing execution_id/runner/backend/PID
[ ] start_key is hidden from ordinary TrackedTasks and is never synthesized automatically from command/prompt/label content
```

### Migration cleanliness

```text
[ ] new runtime/domain code uses ExecutionManager / Execution / execution_id
[ ] no permanent JobManager/job_id compatibility shim remains
[ ] agent skills no longer teach anonymous long blocking/detached patterns
[ ] Conduit no longer owns a duplicate Task tracking SSOT after migration
```

---

## 26. Consequences

### Positive

- Web SOL no longer has to block on peer-review and other long delegated work.
- Detached work remains difficult to forget because later ordinary tool traffic refreshes awareness.
- Fresh ChatGPT sessions can rediscover still-unhandled work.
- Worker implementations remain heterogeneous without forcing one giant provider protocol.
- Execution/runtime diagnostics stay available without polluting ordinary model context.
- The distinction between semantic Task completion and process completion is explicit.
- Result pickup and acknowledgement remain independent, enabling OEP-style optional evidence.
- `@dive` and Conduit gain one shared runtime concept instead of parallel async systems.
- The small Task schema leaves room for real future pressure without encoding speculative lifecycle states today.

### Costs

- Long-running consumers must migrate to Task-aware launch rather than raw detached execution.
- The runtime gains a small SQLite Task registry and lifecycle reconciliation logic.
- Agent skills, CAPABILITIES docs, Runtime docs, Conduit docs, and MCP Task projection need coordinated cleanup.
- Semantic completion may require thin worker-specific observation logic.
- Automatic TrackedTasks injection requires careful preservation of existing MCP tool result contracts.

These costs are accepted because they directly remove blocking latency from Web SOL's critical path while preserving reliable awareness of detached work.

---

## 27. Non-goals for v1

This ADR does not require:

```text
server-initiated push notifications
Task parent/child hierarchy
multiple Tasks sharing one Execution
multiple Executions per Task / retry history
structured progress percentages/phases
input_required lifecycle state
provider-specific Task fields
Task-owned copy of final results
Postgres/PGlite
conversation-scoped Task identity
full event sourcing
cross-machine distributed execution
per-provider orchestration policy
```

Any of these may be reconsidered after actual implementation pressure appears.

---

## 28. Relationship to earlier Conduit work

This ADR builds on, narrows, and promotes the runtime portion of:

```text
docs/conduit/adr/0002-trackedtasks-refresh-and-opportunistic-evidence-pickup.md
docs/conduit/trackedtasks-vA-research-2026-08-21.md
docs/conduit/trackedtasks-vB-research-2026-08-21.md
```

Conduit ADR 0002 established the important workflow direction:

```text
launch -> do not wait -> keep working -> later ordinary tool call
       -> notice terminal work -> inspect when useful
```

The vA/vB research then separated low-level durable execution from Web SOL awareness and exposed the semantic gap between process completion and higher-level Task success.

This Runtime ADR resolves the previously deferred universal domain shape:

```text
Task
  -> exactly one Execution in v1
  -> independent task_id / execution_id
  -> canonical state
  -> optional status_cmd
  -> explicit terminal acknowledgement

TrackedTasks
  -> compact awareness projection only

Execution
  -> lower-level runtime and diagnostics
  -> durable runner identity selects semantic observation
```

Where older Conduit documents use Job/JobManager terminology, this ADR is authoritative for the new GPT Dive Runtime model.

---

## 29. Final architecture

```text
                              ChatGPT Web SOL
                                     |
                   ordinary @dive / @c tool activity
                                     |
                                     v
                         +------------------------+
                         |     TrackedTasks[]     |
                         |  compact + bounded     |
                         +-----------+------------+
                                     |
                         public awareness boundary
                                     |
              +----------------------+----------------------+
              |                                             |
              v                                             v
          TaskManager                                 Task detail
              |                                             |
              | durable SQLite Task                         | execution_id
              v                                             v
            Task                                      Execution detail
     +--------+---------+                             diagnostics only
     | task_id          |
     | execution_id ----+-------------------+
     | source           |                   |
     | label            |                   |
     | state            |                   |
     | status_cmd?      |                   |
     | handled_at?      |                   |
     +------------------+                   |
                                            v
                                   ExecutionManager
                                            |
                                   +--------+--------+
                                   |                 |
                              process/backend    worker runtime
                                   |                 |
                                   |         runner identity
                                   |                 |
                                   +--------+--------+
                                            |
                                         result
```

The guiding rule is simple:

> **Web SOL tracks meaningful Tasks. GPT Dive executes them through durable Executions. Ordinary tool traffic keeps the Tasks visible until Web SOL explicitly handles them.**
