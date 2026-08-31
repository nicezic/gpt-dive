# 01 — Restore distinct Task awareness contracts

**What to build:** Restore the two Task-awareness surfaces to their intended, deliberately different public contracts before automatic structured projection is added: explicit `task(list)` returns detailed Task inspection, while passive TrackedTasks remains compact but keeps elapsed awareness.

**Blocked by:** None — can start immediately.

**Status:** completed

- [x] Explicit `task(list)` again returns the detailed Task inspection shape, including `execution_id`, `label`, `state`, `reason`, lifecycle timestamps, and `elapsed_seconds`.
- [x] Passive TrackedTasks keeps its compact identity/state/reason information and restores derived elapsed display such as `4:21`, without adding detailed timestamps, backend, or process metadata.
- [x] The two surfaces continue to reflect the same SQLite-backed Task lifecycle while remaining intentionally different public representations.
- [x] Regression expectations introduced by the four-field unification are replaced with public-surface tests that protect detailed `task(list)` inspection and elapsed TrackedTasks rendering.
- [x] Existing publication, non-destructive get, explicit dismiss, single-`execution_id`, deterministic ordering, active-before-terminal priority, and bounded projection semantics remain unchanged.
