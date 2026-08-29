# 02 — Unify Task delivery vocabulary

**What to build:** Make immediate Task publication and later `task(get)` use the same LLM-facing outcome vocabulary as Code Mode completion, so delivery timing changes only when the result is available, not how the model interprets it.

**Blocked by:** 01 — Straight-through completed output.

**Status:** completed

- [x] A still-running/published execution exposes exactly `kind`, `execution_id`, and `state` on the relevant public outcome surface.
- [x] A completed execution retrieved through `task(get)` uses the same completed shape and same retained program value as inline completion.
- [x] `code_mode` and `task(get)` share the same `kind` and `execution_id` vocabulary.
- [x] Task outcomes do not expose backend, pid, timestamp, elapsed, systemd, or other normal-path diagnostic metadata.
- [x] Task labels remain available only on awareness/list surfaces where they distinguish multiple executions.
- [x] Existing cancellation, publication, retention, and single-Execution identity semantics remain unchanged.
