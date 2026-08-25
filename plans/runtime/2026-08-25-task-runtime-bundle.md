# TaskRuntime bundle — review-followups slice

> Created 2026-08-25. Origin: 2026-08-24 code-review finding #4 (Data Clump across task-runtime signatures). History chain: v1 plan `plans/plan-260824-task-execution-awareness-v1.md` (verbatim record) → implementation record `plans/runtime/2026-08-24-task-execution-awareness-v1.md` (post-ship work log) → `.scratch/260824-night-sweep-report.md`. Working branch: `improve/260825-review-followups` (already carries `2f049ac` shared probe pool, `c251700` peer model label; this slice is NOT yet implemented).
>
> Notation: unfamiliar English terms are annotated as term(한글 발음, 뜻).

## Problem

Five free functions in `task_runtime.py` require the same two arguments as separate parameters — a Data Clump(데이터 클럼프, 늘 함께 이동하는데 따로 노는 인자 묶음 — Refactoring 책의 code smell 항목):

```text
src/gpt_dive/task_runtime.py — all five share the same head
def list_projected_tasks(executions: ExecutionManager,
                         task_store: TaskStore, *, limit=None)
def refresh_task(executions: ExecutionManager,
                 task_store: TaskStore, task: dict[str, Any])
def collect_task(executions, task_store, task_id: str)
def cancel_task (executions, task_store, task_id: str)
def ack_task    (executions, task_store, task_id: str)

# executions = process lifecycle owner, task_store = durable Task ledger.
# Half a pair is useless — they are one unit in practice.
```

Three callers assemble and carry the pair by hand:

```text
app.py:459                module-level singletons passed positionally
code_mode_worker.py:23    rebuilds its own pair, then four closures forward both args
conduit/runtime.py:110+   ConduitRuntime holds self.executions/self.task_store fields
```

Cost today: every new Task-domain function repeats the pair, and call sites accumulate noise. Type order mistakes are caught by pyright, but the clutter compounds.

## Design

Bundle the pair into one value object. Third application of the repo's NamedTuple precedent (`ProviderRoute`, `WorkerOutcome`):

```python
class TaskRuntime(NamedTuple):
    """Paired handles for Task-aware execution bookkeeping."""
    executions: ExecutionManager
    task_store: TaskStore
```

```text
def list_projected_tasks(rt: TaskRuntime, *, limit=None)
def refresh_task(rt: TaskRuntime, task: dict[str, Any])
def collect_task(rt: TaskRuntime, task_id: str)
def cancel_task (rt: TaskRuntime, task_id: str)
def ack_task    (rt: TaskRuntime, task_id: str)

app.py:           TASK_RUNTIME = TaskRuntime(executions, task_store)
code_mode_worker: rt = TaskRuntime(ExecutionManager(), TaskStore())
ConduitRuntime:   self.rt = ...   # two fields become one
```

Bundling removes the position where the pair could be split or reordered at all.

## Migration steps

```text
1. Define TaskRuntime in task_runtime.py            — pure addition
2. Convert the five signatures + their unit tests
3. app.py module-level swap                         ⚠ largest blast radius:
     tests patch app_module.task_store = TaskStore(...) directly;
     they must rebuild/exchange the bundle instead
4. Simplify code_mode_worker closures               — also trims smell #5 Middle Man
5. Consolidate ConduitRuntime fields                — snapshot logic unchanged
6. docs/runtime/architecture.md module-tree note    — optional single line
```

## risk(리스크, 잘못 진행하면 터질 수 있는 지점)

1. stale reference(스테일 레퍼런스, 교체 후에도 옛 객체를 계속 참조) — step 3: a test that swaps only `task_store` leaves the bundle reading a ghost ledger. Mitigate by making tests exchange the whole bundle first.
2. worker subprocess path must keep default-path assembly order unchanged (same code serves `python -m gpt_dive.code_mode_worker`).
3. MCP capability contract(컨트랙트, 외부 약속 인터페이스) is frozen — tool names, docstrings, payload shapes do not move; internal signatures only.

## Acceptance tests

```text
[x] no function in task_runtime.py retains the bare (executions, task_store) pair signature
[x] app.py keeps the module-global swap pattern working: pair assembled at call time via _task_runtime(); existing tests untouched and green
    (deviation from original wording: an accessor replaced a TASK_RUNTIME constant so tests need no churn)
[x] code_mode_worker closures take the bundle; real-subprocess task capabilities exercised by test_code_runtime suite
[x] ConduitRuntime holds a single rt field; snapshot output identical
[x] MCP capability surface unchanged (names/docstrings/payloads)
[x] docs/runtime/architecture.md module-tree note updated
[x] full gates green at every commit (pytest · ruff · pyright)
```

## Implementation record

- `e18d73e` mechanical conversion of steps 1–5 in one commit (intermediate states would have broken callers); import-sort fixes included.
- Deviation noted: plan originally expected tests to rebuild a `TASK_RUNTIME` constant; implemented as a call-time accessor (`_task_runtime()`) reading the live globals instead — same bundle benefit, zero blast radius on the ~6 swap-pattern tests.
- Live canary evidence for the worker path comes from the existing real-subprocess coverage (`test_code_mode_task_aware_background_launch_and_task_list` et al.), which spawns the worker and drives `task_list`/`task_collect`/`task_ack` end to end.

## Out of scope

- `probe_status_labels` internals beyond what bundling requires (pool already shared via `2f049ac`).
- Any retention-policy, lifecycle-state, or capability-surface change.
- ADR edits (ADR 0001 decision body unaffected).
