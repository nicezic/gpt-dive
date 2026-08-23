## Problem Statement

GPT Dive can already run durable background work, but Web SOL must remember raw execution handles manually. That works for one detached process, but it does not scale to heterogeneous long-running work such as background Code Mode, AGY, peer review, and later Conduit work.

The missing layer is durable **Task awareness**:

```text
long-running work starts
        │
        ▼
existing durable execution runs
        │
        ├─ Web SOL continues foreground work
        │
        ▼
Task remains visible across later tool calls / fresh sessions
        │
        ├─ collect result when useful
        ├─ cancel while working
        └─ ack when handled
```

Execution completion and Web SOL handling are different events. A worker may finish while Web SOL still needs to be reminded that its result has not been handled.

The implementation must unify management without forcing every worker into a new runner framework. Existing background execution remains the execution owner; Task is a small durable awareness/control layer above it.

## Solution

Add a minimal durable Task registry and connect it to the existing background Code Mode lifecycle.

```text
background Code Mode / AGY / peer-review consumer
                    │
                    ▼
          existing Execution boundary
          status / result / cancel
                    │
                    ▼
               TaskStore
                    │
       awareness / handling state
                    │
                    ▼
              TrackedTasks
                    │
        ordinary tool result text
```

A Task has its own durable identity, references exactly one backing Execution in v1, and remains visible until acknowledgement. The Task layer stores only awareness state; execution logs, process identity, runtime metadata, and retained results stay with the existing execution runtime.

The first implementation proves the model on Task-aware background Code Mode. Existing raw background Code Mode remains available during rollout so current callers do not need to migrate atomically. Peer review and long AGY work then become the first real Task-aware consumers. Conduit sharing and Job-to-Execution terminology cleanup happen after the lifecycle is proven.

TrackedTasks has two representations of the same records:

```text
explicit task_list()
→ complete structured Task objects
→ optional compact readable rows

ordinary @dive tool return
→ original structured result unchanged
→ compact TrackedTasks TextContent appended
```

Optional progress decoration remains deliberately thin. A Task may carry either a `status_cmd` that returns text such as `TODOS 3/9`, or a static `status` string. Display probe failures never change lifecycle state.

## User Stories

1. As Web SOL, I want long-running delegated work to return immediately, so that I can continue unrelated foreground work.
2. As Web SOL, I want meaningful background work to have a human-readable Task label, so that I can remember why it exists.
3. As Web SOL, I want Tasks to survive later turns and fresh ChatGPT sessions, so that detached work is not forgotten when conversation context changes.
4. As Web SOL, I want ordinary GPT Dive activity to remind me about outstanding Tasks automatically, so that I do not need to poll manually.
5. As Web SOL, I want the original tool result to remain structurally unchanged when TrackedTasks is added, so that Task awareness does not break existing tool contracts.
6. As Web SOL, I want a structured `task_list()` view, so that I can inspect complete Task metadata when I need machine-readable detail.
7. As Web SOL, I want compact readable TrackedTasks rows, so that normal awareness consumes little context.
8. As Web SOL, I want elapsed time shown for a Task without storing a second duration field, so that the display is useful without duplicating lifecycle state.
9. As Web SOL, I want a worker to expose lightweight progress such as `TODOS 3/9`, so that long-running work can communicate useful progress without a progress subsystem.
10. As Web SOL, I want `status_cmd` failure or timeout to affect only display decoration, so that a broken progress probe cannot fail real work.
11. As Web SOL, I want a static status string when no dynamic command is useful, so that simple workers can provide readable state without creating files or probes.
12. As Web SOL, I want Tasks with no progress decoration to remain valid, so that label, lifecycle state, and elapsed time are sufficient defaults.
13. As Web SOL, I want to collect a completed result without removing Task awareness, so that reading a result is not confused with handling it.
14. As Web SOL, I want repeated collection to remain non-destructive while the backing result exists, so that I can inspect a result more than once.
15. As Web SOL, I want to cancel a working Task through the Task layer, so that heterogeneous background work has one common control surface.
16. As Web SOL, I want acknowledgement to remove a terminal Task from automatic awareness, so that handled work stops consuming attention.
17. As Web SOL, I want acknowledgement of working Tasks rejected, so that active work cannot silently disappear from awareness.
18. As Web SOL, I want a missing backing Execution/result represented explicitly as `lost`, so that the runtime reports what it actually knows instead of inventing recovery.
19. As Web SOL, I want `lost` work to remain visible until acknowledgement, so that missing work is not silently forgotten.
20. As Web SOL, I do not want Task awareness to trigger provider calls, agent polling, reconstruction, or automatic retries, so that ordinary tool calls remain bounded and predictable.
21. As a maintainer, I want Task awareness stored separately from execution persistence, so that there is one owner for execution lifecycle and one small owner for Web SOL awareness.
22. As a maintainer, I want one Task to reference one Execution in v1, so that retry history and multi-run execution semantics remain out of scope.
23. As a maintainer, I want existing background Code Mode to remain the initial execution path, so that Task awareness can be proven without building a new launcher hierarchy.
24. As a maintainer, I want current raw background Code Mode callers to keep working during rollout, so that Task-aware consumers can migrate incrementally.
25. As a maintainer, I want peer review to be the first real Task-aware canary, so that the original synchronous waiting problem is tested end to end.
26. As a maintainer, I want long AGY flows to reuse the same Task-aware background path, so that AGY does not gain a separate process/task manager.
27. As a maintainer, I want the current execution implementation terminology cleanup deferred until behavior is proven, so that a wide rename does not obscure lifecycle bugs.
28. As a maintainer, I want Conduit migration deferred from the first slice, so that cross-process execution namespace concerns do not expand the initial change.
29. As a maintainer, I want Task capabilities exposed through Code Mode rather than several new top-level MCP tools, so that the public command surface stays small.
30. As a maintainer, I want the first implementation to avoid recovery, idempotency, runner registries, result pinning, parent/child tasks, and structured progress, so that v1 stays intentionally small.

## Implementation Decisions

- Add one small SQLite-backed TaskStore as the durable owner of Task awareness. It stores Task identity, backing execution identity, label, lifecycle state, optional display status inputs, and creation/update timestamps.
- TaskStore does not persist execution logs, stdout/stderr, provider/session state, process metadata, runtime backend data, or a copied final result. Those remain owned by the backing Execution runtime.
- v1 uses one Task per one Execution. `task_id` and `execution_id` are separate identities even though there is only one backing Execution per Task.
- The lifecycle state set is `working`, `completed`, `failed`, `cancelled`, and `lost`.
- A terminal Task remains present until acknowledgement. v1 has no Task TTL or handled-retention state machine; acknowledgement removes the Task awareness record.
- Existing Execution result retention remains unchanged. A previously terminal Task may later become `lost` if its backing retained result disappears before acknowledgement.
- `lost` is terminal awareness state with no recovery transition. The runtime does not reconstruct missing work, search historical artifacts, re-poll providers, or retry automatically.
- Existing background Code Mode is the first Task-aware launch path. A Task-aware launch creates the backing execution first, then durably creates the Task before reporting Task-level success.
- If the backing execution starts but Task persistence fails, the launch fails and best-effort cancellation is attempted. No separate orphan-recovery subsystem is introduced.
- During rollout, background Code Mode without Task metadata keeps the existing raw execution-handle behavior. Task-aware consumers opt in through a non-empty Task label.
- A Task-aware background launch may also accept optional `status_cmd` and optional static `status` display text.
- `status_cmd` is a bounded local display probe. Usable stdout becomes the rendered status text. If the probe is absent, fails, times out, or produces no usable text, static `status` is used when present; otherwise no progress decoration is rendered.
- Display status never determines lifecycle state. `status_label` and elapsed time are derived at read/render time and are not persisted as canonical Task fields.
- Reuse the existing bounded local command execution seam for `status_cmd`; do not create another shell/process runner.
- Task lifecycle refresh uses local backing Execution evidence only. It must preserve the worker-specific success/failure interpretation already owned by the current background worker boundary rather than blindly copying a low-level process status.
- A backing Execution reported as still running keeps the Task `working`; a truthful normalized success/failure/cancellation updates the Task terminal state; missing required backing execution/result evidence becomes `lost`.
- The initial Task control surface contains only `task_list`, `task_collect`, `task_cancel`, and `task_ack`. Do not add `task_get` in v1; `task_list` already provides complete structured Task objects.
- `task_collect` is non-destructive and does not imply acknowledgement. Working Tasks report not-ready; completed Tasks return retained results; failed/cancelled Tasks return retained evidence when available; lost Tasks report result unavailable.
- `task_cancel` forwards cancellation to the backing Execution while working. Repeated cancellation should remain harmless; already terminal/lost Tasks return their current state instead of creating a second lifecycle.
- `task_ack` rejects working Tasks and removes terminal/lost Task awareness records. Ack does not pin, extend, copy, or otherwise manage Execution result retention.
- Register Task operations as Code Mode capabilities rather than adding several new top-level MCP tools.
- `task_list()` returns complete structured Task objects. It may also return compact readable rows generated from the same records.
- Automatic awareness on ordinary GPT Dive tool results uses the existing result-content middleware seam: preserve the original `CallToolResult` and append a small TrackedTasks `TextContent` block.
- Automatic awareness does not merge Task objects into unrelated tools' existing `structuredContent`. Structured Task inspection is the responsibility of explicit `task_list()`.
- Automatic TrackedTasks output may cap the number of rendered Tasks to protect model context. The cap and selection order are rendering policy, not persisted Task state.
- Awareness refresh/render failure must not fail unrelated foreground work. Preserve the primary result and emit at most a small explicit awareness-unavailable message.
- The first production canary is Task-aware peer review, followed by long AGY workflows using the same background Code Mode path.
- Conduit migration to the shared Task domain is a later slice. The first implementation does not force currently separate execution roots into a shared namespace.
- Job/Execution terminology cleanup is deferred until Task lifecycle behavior is proven. The final model uses Execution language, but the first behavioral slice does not require a wide rename or permanent dual compatibility layer.

## Testing Decisions

- Test at the highest existing behavioral seams rather than private helper structure: public background Code Mode behavior, Code Mode Task capabilities, and MCP result middleware output.
- Preserve the existing raw background Code Mode test suite as regression coverage for callers that do not opt into Task awareness during rollout.
- Add a focused Task-aware background launch test proving immediate return, durable Task creation, distinct Task/Execution identities, and non-empty label behavior.
- Add lifecycle tests proving `working → completed`, `working → failed`, `working → cancelled`, and missing backing execution/result → `lost`.
- Failure-state tests must use the worker-level normalized background result semantics, including malformed/error envelopes, rather than assuming low-level process completion means Task success.
- Add TaskStore persistence coverage by reopening the store and proving outstanding Tasks are rediscovered without conversation-session state.
- Add `task_list` coverage proving complete structured Task fields are returned and derived display fields do not replace persisted canonical fields.
- Add status display coverage for dynamic `status_cmd` output such as `TODOS 3/9`, static status fallback, absent display status, probe failure, probe timeout, and empty output. None of these display cases may change Task lifecycle state.
- Add elapsed-time coverage proving running elapsed time is derived from creation time and terminal elapsed time remains stable once the state-changing update timestamp is written.
- Add collection coverage proving working is not ready, completed returns retained result, failure/cancellation expose retained evidence where available, lost reports unavailable, and repeat collection does not acknowledge.
- Add cancellation coverage proving active cancellation is forwarded and repeated cancellation is harmless.
- Add acknowledgement coverage proving working Tasks are rejected and terminal/lost Tasks disappear from Task awareness without changing backing result retention policy.
- Add middleware coverage at the existing `CallToolResult` seam proving the original content/structured result remains compatible while compact TrackedTasks text is appended.
- Add middleware failure coverage proving Task awareness failure preserves an otherwise successful primary tool result.
- Add a fresh-session/process-style acceptance test that reconstructs TaskStore state and sees retained outstanding Tasks without relying on in-memory conversation state.
- Use peer review as the first end-to-end non-blocking canary: launch asynchronously, continue foreground work, observe it through later ordinary tool traffic, collect the result, then acknowledge it.
- After the peer-review canary passes, run the same lifecycle path through a long AGY workflow and verify worker-owned progress can surface through the optional display probe.
- Defer cross-process Conduit integration tests until the later Conduit migration slice.
- Defer broad Job-to-Execution rename/migration tests until terminology cleanup follows the proven lifecycle.

## Out of Scope

- Native MCP Tasks as the primary v1 Task model.
- A new generic execution/runner framework.
- Durable runner or adapter registries.
- Start keys, launch fingerprints, idempotency claims, or automatic response-loss deduplication.
- Multiple Executions per Task, retries attached to one Task, retry history, or multiple Tasks sharing one Execution.
- Parent/child Task hierarchy or workflow graphs.
- Startup orphan reconciliation or crash-recovery machinery.
- Provider polling, server-initiated wakeups, automatic remote status requests, or reconstruction of missing work.
- Result pin/unpin coordination, indefinite result retention, or copying final results into TaskStore.
- Task TTL, automatic three-day cleanup, handled-at retention state, or other Task garbage-collection policy beyond explicit acknowledgement.
- Structured progress phases, percentages, worker-to-Task progress update APIs, or mutable progress as lifecycle SSOT.
- New top-level MCP tools solely for Task controls.
- Automatic merging of Task objects into unrelated tools' structured response contracts.
- Conduit migration in the first implementation slice.
- Sharing currently separate execution roots merely to make Conduit migration happen sooner.
- Wide JobManager/job_id to ExecutionManager/execution_id source rename before lifecycle acceptance.
- Permanent compatibility shims for old Job terminology after eventual terminology cleanup.

## Further Notes

The Runtime Task/Execution/TrackedTasks ADR is the architecture authority for this plan. The important separation is semantic rather than implementation-heavy:

```text
Execution completion
= runtime event

Task acknowledgement
= Web SOL handling event
```

Existing AGY history already demonstrates the preferred reuse pattern: worker-specific semantics can remain above background Code Mode while background Code Mode supplies durable execution lifecycle. Task awareness extends that same principle instead of introducing an AGY-specific Task runtime.

The first slice should optimize for proof, not renaming. Once Task-aware peer review and AGY can run, reappear through ordinary tool traffic, be collected, cancelled, lost truthfully, and acknowledged, the later Conduit migration and Execution terminology cleanup can be performed against a proven lifecycle instead of an abstract model.
