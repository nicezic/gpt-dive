# Conduit — Current Continuation

> Updated: 2026-08-28. Stable background is in `bootstrap.md`; Runtime language is owned by `../runtime/CONTEXT.md`.

## Current position

Conduit now consumes the renewed always-durable Runtime directly.

```text
@c request
├─ start(label, command, cwd?)
│    └─ Runtime Execution + immediately published Task
├─ get(execution_id)       non-destructive
├─ cancel(execution_id)    explicit cancellation
├─ dismiss(execution_id)   terminal awareness
├─ sync(text)
└─ emit(text, session_id?)
        │
        ▼
Redis event v2 + shared TrackedTasks snapshot
```

There is no Conduit `TaskStore`, `task_id`, caller timeout, collect action, or ack action. `execution_id` is the only lifecycle handle, and SQLite Runtime state is the authority.

## Implemented renewal delta

- `ConduitRuntime` now receives only `ExecutionManager` plus its event publisher.
- `start` uses Runtime's fixed 3,590-second work policy and publishes awareness in the same accepted row.
- snapshots call the shared Runtime projection, so Code Mode and Conduit work appear together;
- Redis envelopes are version 2 and carry the single identity;
- the `c` MCP schema is a strict discriminated request union with unknown fields rejected;
- non-destructive get and explicit terminal dismissal preserve the original OEP intent.

## Validation state

Repository tests cover shared visibility, non-destructive get, explicit cancel, dismissal, retained results, event version, and strict schema shape. The Runtime-wide fresh ChatGPT session acceptance is still required after service reload because ChatGPT Web may cache the old Conduit and Dive schemas.

## Next Conduit work

Runtime stabilization and live acceptance come first. After that, resume the planned Council/Conduit product work without reopening Runtime terminology or building a second lifecycle manager.

## References

- `docs/runtime/adr/0004-always-durable-code-mode-runtime.md`
  - Authority for the shared Execution/Task identity and lifecycle now consumed here.
- `docs/conduit/adr/0001-conversation-driven-task-pull.md`
  - Preserves why conversation-driven refresh and non-destructive retrieval exist; its historical collect naming is superseded by current `get`.
- `docs/conduit/adr/0002-trackedtasks-refresh-and-opportunistic-evidence-pickup.md`
  - Preserves the accepted cross-surface awareness and OEP direction.
