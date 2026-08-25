# Task Execution Awareness v1 — Implementation Record

> Shipped 2026-08-24 (commits `4f7f30d`..`3f73998`). Architecture authority: `docs/runtime/adr/0001-task-execution-and-trackedtasks-runtime-model.md`. This file records the implementation sequence and the acceptance checklist; the ADR keeps only the decision body.
> Checkbox state reflects the pre-split document; unverified items were not retroactively ticked.
> 2026-08-25 update: post-ship work log appended below; a subset of acceptance boxes was backfilled **with named-suite evidence only** (see "Acceptance backfill"). Everything else stays unticked per the original discipline.

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
[x] background start returns task_id/label/state
[x] task_list returns complete structured TrackedTask objects
[ ] task_list may also return compact readable rows without discarding structured fields
[x] standard rows render label · state · derived elapsed time and optional status text
[x] status_cmd stdout such as `TODOS 3/9` can decorate a visible working Task
[x] absent/failing/empty status_cmd falls back to static status when present, otherwise no status decoration
[x] status display failure never changes Task.state
[ ] no-op refresh does not change updated_at or terminal elapsed time
[ ] a fresh ChatGPT session can rediscover retained outstanding Tasks
[x] completed/failed/cancelled states refresh from local Execution state
[x] missing Execution/result becomes lost
[ ] lost does not trigger recovery, remote polling, or reconstruction
```

### Result and handling

```text
[x] collect on working reports not-ready
[x] collect on completed returns retained result
[ ] collect on failed/cancelled returns retained evidence when available
[ ] collect on lost reports unavailable/lost
[x] collect is repeatable while the Execution result exists
[x] ack rejects working
[x] ack removes terminal/lost Task awareness
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

## Post-ship work log

> Appended 2026-08-25, newest section last. Full narrative: `.scratch/260824-night-sweep-report.md`. This log records only what touched the Task/Execution domain after ship.

### 2026-08-24 night sweep — merged to main as `d437e3c` (branch `improve/260824-night-sweep`)

- `947c0b6` background envelope parsing/normalization unified into `task_runtime.read_execution_result`; request/ref/cleanup helpers single-owner in task_runtime.
- `9ef7571` capability registry construction extracted to `code_capabilities.py`; `code_mode_worker` builds its own default-path TaskStore/ExecutionManager instead of importing app.py; shared `list_projected_tasks()` replaces triplicated listing composition.
- `e30be44` PEP 562 lazy exports so `python -m gpt_dive.code_mode_worker` skips the MCP server graph.
- `904af71` bounded `status_cmd` probes run concurrently; wall time stays near one probe.
- Same branch later renamed `bare*` → `model_call*` and unified bounded-worker plumbing (`worker_subprocess.py`: `WorkerOutcome`, `worker_failure()`, `stderr_tail`) — report Addendum 3.
- On main after merge: `0946c77` probe-call assertion made order-insensitive (concurrency made completion order nondeterministic; the test was flaky-by-design since `904af71`).

### 2026-08-25 review-followups — branch `improve/260825-review-followups` (NOT merged yet)

- `2f049ac` `probe_status_labels` reuses one lazily-created shared pool (was a fresh ThreadPoolExecutor per snapshot call); TDD seam asserts pool identity is stable across calls.
- `c251700` `_peer_model_label`: peer-review transport-error envelopes now carry the explicit model id or the route default instead of an empty `model` field.
- Pending decision: #4 Data Clump cleanup — bundle `(executions, task_store)` into `TaskRuntime(NamedTuple)` across `task_runtime.py` (5 functions) / `app.py` / `code_mode_worker.py` / `conduit/runtime.py`. Design reviewed with user; go/no-go pending. Docs impact: none required beyond an optional module-tree note in `docs/runtime/architecture.md`.

### Acceptance backfill (2026-08-25, suite = 234 passing)

Boxes ticked above cite named tests from the current suite:

| Boxes | Evidence |
|---|---|
| launch fields, structured task_list | `test_code_mode_task_aware_background_launch_and_task_list` |
| derived status/elapsed, `TODOS 3/9` decoration | `test_task_aware_launch_derives_status_and_elapsed` |
| fallback trio, display failure ≠ state change | `test_task_status_display_falls_back_without_changing_state` |
| completed/failed/cancelled refresh | collect/refresh-semantics/cancel tests in `tests/test_code_runtime.py` |
| lost | `test_terminal_task_becomes_lost_when_execution_disappears`, `test_missing_execution_becomes_lost_and_can_be_acked` |
| working not-ready, retained result, repeatability, ack rejection/removal | `test_task_collect_is_non_destructive_and_ack_preserves_execution_result` |

All other boxes remain unticked — no retroactive ticking without named evidence.
