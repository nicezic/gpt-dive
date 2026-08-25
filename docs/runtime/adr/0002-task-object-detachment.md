---
title: ADR - Task-Object Detachment Surface
created: 2026-08-26
updated: 2026-08-26
type: decision
status: proposed
---

# ADR 0002 - Task-Object Detachment Surface

## Decision

GPT Dive replaces the boolean detachment flag with one **task-object launch contract** shared by both detached-work surfaces:

```text
code_mode(payload, code, cwd, task=...)        # primary programmable root
wsl2_async(action="start", command, ..., task=...)  # durable direct WSL lane
```

```text
                     task parameter
                          │
           ┌──────────────┴───────────────┐
       absent                         present
                                  {label, status_cmd?, status?}
           │                             │
    synchronous run              detached durable execution
  (foreground, unchanged)        + Task created always ✅
                                       │
                            TrackedTasks awareness through the
                            ordinary tool-call seam (unchanged)

core rule: detached means tracked
```

Launching work outside the foreground without a labeled Task is no longer a representable state.

### Contract

```text
task = {
  label: str          # required, non-empty, ≤80 characters
  status_cmd?: str    # optional bounded local display probe
  status?: str        # optional static display fallback
} | None
```

| Call | Behavior | Start result |
|---|---|---|
| `code_mode(task=None)` | synchronous foreground run (unchanged) | normal run result |
| `code_mode(task={...})` | detach + create Task | `{task_id, execution_id, label, state}` |
| `wsl2_async(start, task={...})` | detach + create Task (required) | `{task_id, execution_id, label, state}` |
| `wsl2_async(start`, no `task)` | rejected | validation error |

- `wsl2_async` has no synchronous mode — every start is detached — so its `task` is mandatory there.
- Lifecycle actions (`status` / `result` / `cancel`) stay keyed by `execution_id` on both tools.
- The Monty-visible `BACKGROUND` variable survives, derived from the actual outer mode (`task` presence).
- Validation collapses into object rules: cross-parameter error ladders (`label` only with flag, `status` only with `label`) become shape requirements of one object.

## Why

Runtime ADR 0001 proved Task awareness, but attached it per lane instead of making it a property of detachment itself:

```text
code_mode(background=True, label="X")  → detached + tracked ✅
code_mode(background=True)             → detached + ghost handle ❌
wsl2_async(start, ...)                 → detached only, Task impossible ❌
```

Observed facts (2026-08-26):

- `wsl2_async` start never creates a Task; its handles are exactly the opaque kind §1 of ADR 0001 set out to eliminate.
- Background Code Mode carries a hardcoded 600-second kill limit, so genuinely long work (a 1GB download) is pushed toward the untracked lane.
- Invariant #1 ("model-visible detached work has a labeled Task") was conventional, not structural — an escape hatch, not a wall.

The motivating case: a large `wget` belongs in the durable direct lane, which was precisely the lane TrackedTasks could not see. Under this decision the same launch participates in Opportunistic Evidence Pickup automatically, including `status_cmd` decoration (for example a byte-count probe) with zero worker cooperation.

Decision driver: instruction-following decays under familiar defaults, so a rule enforced by remembering is weaker than a contract that cannot express the mistake. The gap closes structurally, not by reminder discipline.

## Reality constraints respected

- Task creation stays at the MCP tool boundary. `ExecutionManager.start()` keeps its `(command, cwd, timeout)` signature, so internal executions (the Code Mode worker itself) cannot spawn nested phantom Tasks.
- ChatGPT Web does not negotiate native MCP Tasks; awareness continues to ride ordinary tool results through the existing middleware seam (conduit ADR 0002).
- One normalized Execution outcome per launch; no runner registry or recovery subsystem appears here.

## Consequences

- Detached ⟺ labeled Task becomes true by construction across both surfaces.
- Breaking MCP schema change, clean break, no compatibility alias for `background=True`.
- Both lanes share one start-return contract, so follow-up handling transfers between them without branching.
- Wiki routing and Code Mode lifetime documentation switch to task-object phrasing in the same change; the implementation sequence and acceptance checklist land as a dated record under `plans/runtime/`.
- This ADR flips to `accepted` when that implementation passes its acceptance checklist.

## Non-goals

- Renaming `wsl2_async` or consolidating the low-level Execution surface (deferred follow-up noted in conduit ADR 0002 consequences).
- Deduplicating lifecycle verbs between `wsl2_async` actions and `task_*` capabilities.
- The 600-second background Code Mode limit (separate decision).
- Result-retention policy, Lost semantics, native MCP Tasks negotiation, Conduit protocol.

## Rejected alternatives

- **Auto-create Tasks inside ExecutionManager for every launch** — internal executions would need labels and would double-report behind tool-level Tasks.
- **Keep the flag, make `label` mandatory** — same enforcement, but two coupled parameters keep the second concept alive and the ghost handle one refactor away.
- **Compatibility alias for `background=True`** — permanent dual contracts for a one-line caller migration; house rule rejects standing compatibility layers.

## References

- `docs/runtime/adr/0001-task-execution-and-trackedtasks-runtime-model.md`
  - Task / Execution / TrackedTasks model and invariants this refines; stays untouched as shipped-v1 history.
- `docs/conduit/adr/0002-trackedtasks-refresh-and-opportunistic-evidence-pickup.md`
  - Refresh and OEP seam that newly-tracked `wsl2_async` Tasks flow into.
- `plans/runtime/2026-08-26-task-object-detachment.md`
  - Spec SSOT: user stories, testing decisions, out-of-scope boundaries for the implementation.
