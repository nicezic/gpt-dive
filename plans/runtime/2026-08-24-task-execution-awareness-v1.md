# Task Execution Awareness v1 — Implementation Record

> Shipped 2026-08-24 (commits `4f7f30d`..`3f73998`). Architecture authority: `docs/runtime/adr/0001-task-execution-and-trackedtasks-runtime-model.md`. This file records the implementation sequence and the acceptance checklist; the ADR keeps only the decision body.
> Checkbox state reflects the pre-split document; unverified items were not retroactively ticked.

## Implementation order

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

## Acceptance tests

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
