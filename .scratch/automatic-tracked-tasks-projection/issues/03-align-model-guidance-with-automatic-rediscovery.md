# 03 — Align model guidance with automatic rediscovery

**What to build:** Update the minimal runtime/model guidance so Web SOL treats ordinary-result `tracked_tasks` as the normal automatic completion-discovery path, while `task(list)` remains explicit detailed inspection rather than a polling obligation.

**Blocked by:** 02 — Project TrackedTasks on ordinary results.

**Status:** completed

- [x] Guidance states that background completion is normally rediscovered from ordinary result `tracked_tasks` without remembering a polling cadence.
- [x] Guidance describes automatic TrackedTasks as compact passive awareness with elapsed information and `task(list)` as the richer detailed inspection surface.
- [x] `task(get)` remains non-destructive result pickup and `task(dismiss)` remains the explicit action that removes terminal awareness.
- [x] Guidance keeps ADR 0005 local-reduction/program-output semantics separate from ADR 0006 Task awareness and does not imply that shared SQLite authority requires identical public shapes.
- [x] The change stays narrowly scoped to the runtime workflow required for automatic rediscovery and does not perform the broader ADR 0009 naming migration.
