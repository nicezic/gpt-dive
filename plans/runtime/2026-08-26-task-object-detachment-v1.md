# Task-Object Detachment v1 - Implementation Record

> Shipped 2026-08-26 on `improve/260826-task-object-detachment`. Decision authority: `docs/runtime/adr/0002-task-object-detachment.md`; spec SSOT: `2026-08-26-task-object-detachment.md`. This file records the implementation sequence and acceptance evidence only.

## Sequence

```text
design session (grill-style, no ticket)
        ↓
spec (/to-spec) → ADR 0002 (/docs) → implement (/tdd at tool seam)
```

1. New-seam tests written first (`tests/test_task_object_detachment.py`): red on missing contract, then green.
2. `TaskLaunch` model added; `code_mode` schema rebuilt around one optional `task` object; detached start returns task-level info only.
3. `wsl2_async` start requires `task`; non-start actions reject it; `capabilities` advertises the requirement; start creates the Task with best-effort cancel on persistence failure.
4. Legacy parameters (`background`, flat `label`/`status_cmd`/`status`) removed with no alias.
5. Existing suites migrated to the task-object form; wiki routing/lifetime docs updated in the same change.

## Acceptance checklist

- [x] `code_mode(task=None)` runs synchronously and creates no Task.
- [x] `code_mode(task={label})` detaches, creates a Task, returns `{task_id, execution_id, label, state}`.
- [x] `wsl2_async(start)` without `task` rejects with an explicit validation error.
- [x] `wsl2_async(start, task={...})` creates a tracked Task and returns the same unified shape as `code_mode`.
- [x] Full cycle proven at the tool seam: start → terminal → `task_list` → non-destructive `task_collect` → `task_ack` removes awareness.
- [x] Legacy flag parameters are gone from schema and signature (TypeError on direct call).
- [x] TrackedTasks middleware preservation tests pass untouched.
- [x] Full suite green: 241 passed; `uv run pyright src` 0 errors; ruff check/format clean.

## Deliberately out of scope

- `wsl2_async` rename / low-level Execution surface consolidation (conduit ADR 0002 deferred follow-up).
- Lifecycle verb dedup between `wsl2_async` actions and `task_*` capabilities.
- Hardcoded 600-second Code Mode detach limit (separate decision).
