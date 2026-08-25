# Plan - Task-Object Detachment Surface

> Status: spec ready for implementation · Created 2026-08-26 · Design session: unified Task-based detachment across `code_mode` and `wsl2_async`.
> Architecture context: `docs/runtime/adr/0001-task-execution-and-trackedtasks-runtime-model.md` (v1 reality), new runtime ADR 0002 will own this delta.

## Problem Statement

Detached asynchronous work has two inconsistent launch contracts, and the TrackedTasks awareness layer only covers one of them:

```text
code_mode(background=True, label="X")   → detached + tracked ✅
code_mode(background=True)              → detached + ghost handle ❌
                                          (untracked, forgotten exactly as
                                           runtime ADR 0001 §1 described)
wsl2_async(start, ...)                  → detached only, Task impossible ❌
                                          (the natural lane for long direct
                                           work such as a 1GB wget download)
```

From the user's perspective: when Web SOL starts long-running local work (a large download, a durable maintenance command), whether that work later resurfaces in TrackedTasks depends on which tool launched it. The most durable lane (`wsl2_async`) is precisely the one that produces forgettable opaque handles. A secondary defect: background Code Mode launches use a hardcoded kill limit that makes them unsuitable for genuinely long work, pushing users toward the untracked lane.

## Solution

One concept replaces the boolean flag: **detached means tracked**.

```text
                       task parameter
                            │
             ┌──────────────┴──────────────┐
         task=None                    task={label, ...}
             │                             │
      synchronous run               detached launch +
    (foreground, unchanged)       Task created always ✅
                                         │
                              TrackedTasks awareness via the
                              existing middleware seam

invariant #1 ("model-visible detached work has a labeled Task")
becomes structural: the untracked escape hatch no longer exists.
```

`wsl2_async` adopts the same contract. It has no synchronous mode — every start is detached — so its `task` parameter is required. Both tools return the same task-level start result.

## User Stories

1. As a ChatGPT Web SOL, I want `code_mode(task=None)` to keep running synchronously exactly as before, so that ordinary foreground orchestration does not pay any migration cost.
2. As a ChatGPT Web SOL, I want a single `task` object to mean "detach this work and track it", so that I express intent with one concept instead of combining a flag with optional fields.
3. As a ChatGPT Web SOL, I want detached launches to be impossible without a human-readable label, so that I can never create work that future turns cannot rediscover.
4. As a ChatGPT Web SOL, I want `wsl2_async` starts to always produce a Task, so that a 1GB wget download reappears in TrackedTasks on my next ordinary tool call instead of becoming an orphaned handle.
5. As a ChatGPT Web SOL, I want identical start-return shapes from both tools (`{task_id, execution_id, label, state}`), so that follow-up handling code and habits transfer between lanes without branching.
6. As a ChatGPT Web SOL, I want `status_cmd`/`status` to live inside the same task object as their required label, so that display decoration can never reference a nonexistent Task.
7. As a fresh-session ChatGPT Web SOL, I want all outstanding Tasks visible through TrackedTasks regardless of which tool launched them, so that session loss does not lose durable work awareness.
8. As a user, I want my long downloads and maintenance jobs to remain visible until I explicitly ack them, so that background latency never silently disappears budget or bandwidth.
9. As a user, I want the ghost-handle failure mode removed structurally rather than by reminder discipline, so that adherence does not depend on model attention.
10. As a user, I want execution-level diagnostics (`status`, raw process facts) to stay available on both tools, so that debugging keeps its low-level surface.
11. As a user, I want `task_collect` to remain non-destructive and `task_ack` to remain removal-only, so that picking up evidence never destroys it accidentally.
12. As a future worker author, I want Task creation to stay at the tool boundary rather than inside the ExecutionManager, so that internal executions (such as the Code Mode worker itself) do not spawn nested phantom Tasks.
13. As a maintainer, I want the validation matrix simplified into object-shape rules instead of cross-parameter error ladders, so that schema contracts stay explainable.
14. As a maintainer, I want wiki routing/lifetime documents updated together with the schema, so that live contracts and operational memory do not diverge.
15. As a maintainer, I want this recorded as a new runtime ADR rather than editing shipped-v1 history, so that the evidence trail in the v1 plan record stays intact.

## Implementation Decisions

- **Flag removal.** `background`, `label`, `status_cmd`, `status` as flat parameters disappear from the `code_mode` schema. One optional `task` object replaces them (shape below originated from the design session and encodes the decision):

  ```text
  task = {
    label: str          # required, non-empty, ≤80 characters
    status_cmd?: str    # optional bounded local display probe
    status?: str        # optional static display fallback
  } | None
  ```

- **Mode selection.** `task=None` → synchronous foreground run (behavior unchanged). `task` present → detached durable execution plus Task creation, returning `{task_id, execution_id, label, state}`.
- **`wsl2_async` symmetry.** `action="start"` gains a required `task` object with the same shape and returns the same task-level result. Missing `task` on start is a validation error. `capabilities` discovery output reflects the new requirement.
- **Boundary placement.** `ExecutionManager.start()` keeps its `(command, cwd, timeout)` signature; Task creation remains at the MCP tool boundary. This preserves one normalized Execution outcome and prevents double-tasking of internal executions.
- **Lifecycle surfaces unchanged.** `code_mode` `action=status/result/cancel` and `wsl2_async` `status/result/cancel` keep operating on `execution_id`; deduplication with `task_collect/cancel/ack` remains the separately-deferred low-level-surface follow-up.
- **`BACKGROUND` injection retained.** The Monty-visible `BACKGROUND` variable continues to reflect the actual outer mode, derived from `task` presence.
- **Validation simplification.** Cross-parameter errors collapse to object rules: `label` required inside `task`; `status_cmd`/`status` decorate the same object; `task` and lifecycle `action` are mutually exclusive; stray legacy parameters are rejected.
- **Clean break.** No compatibility alias for `background=True` (house rule: no permanent compatibility layers). Existing sessions see the new schema immediately.
- **Docs in scope.** Wiki routing (`workflow/gpt-dive.md`) and Code Mode lifetime documentation, plus tool description text, switch to task-object phrasing in the same change.
- **ADR vehicle.** New `docs/runtime/adr/0002-task-object-detachment.md` records this decision as a delta; runtime ADR 0001 stays untouched as shipped-v1 history.

## Testing Decisions

- **Good test = external behavior at the MCP tool-function boundary**, asserting return shapes, validation errors, and observable store state — not internal call graphs.
- **Single primary seam (user-approved):** call `gpt_dive.code_mode(...)` / `gpt_dive.wsl2_async(...)` directly as functions with `TaskStore`/`ExecutionManager` rooted at a temp directory.
- **Prior art:** `tests/test_surface.py` (function-level tool calls, monkeypatched manager, live-schema exposure assertions) and `tests/test_task_runtime.py` (temp-rooted real stores, full lifecycle including lost/ack).
- **Coverage map:**
  - sync path unchanged under `task=None`;
  - detached path creates Task and returns the unified shape (both tools);
  - `wsl2_async` start without `task` rejects;
  - legacy flag parameters reject;
  - schema/surface contract tests updated for removed parameters;
  - one end-to-end cycle: start → terminal → `task_list` shows completion → `task_collect` non-destructive → `task_ack` removes;
  - middleware preservation tests keep passing untouched (TrackedTasks append seam unchanged).

## Out of Scope

- Renaming `wsl2_async` or consolidating the low-level Execution surface (explicitly deferred follow-up in conduit ADR 0002 consequences).
- Deduplicating lifecycle verbs between `wsl2_async` actions and `task_*` capabilities.
- The hardcoded 600-second kill limit on background Code Mode launches (noted during design; separate decision).
- Changes to native MCP Tasks negotiation, Conduit protocol, or Lost/recovery semantics.
- Any result-retention policy change (Execution retention still owns lifetime; ignored Tasks may still become lost).

## Further Notes

- The motivating example preserved from the design session: a 1GB `wget` belongs in `wsl2_async` (durable, arbitrary timeout), and after this change it finally participates in OEP — candidate evidence picked up whenever a later ordinary tool call surfaces its completed Task.
- `status_cmd` shines here too: e.g. an `ls -l | awk` probe decorating the working Task with downloaded bytes, requiring zero cooperation from the worker.
- Implementation record (sequence + acceptance checklist) should land as a dated file under `plans/runtime/` consistent with the v1 precedent, referenced from the new ADR.
