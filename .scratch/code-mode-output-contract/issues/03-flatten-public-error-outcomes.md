# 03 — Flatten public error outcomes

**What to build:** Normalize Code Mode failures into one compact LLM-facing error shape, preserving the durable execution handle while keeping traceback, cleanup internals, and raw diagnostics off the normal model-visible path.

**Blocked by:** 02 — Unify Task delivery vocabulary.

**Status:** completed

- [x] Normal public failures expose exactly `kind`, `execution_id`, `code`, and `message`.
- [x] Error outcomes do not repeat `label` or add nested error/result wrappers.
- [x] Launch, runtime, and retained-result failure paths use the same public error vocabulary when they are represented as Code Mode outcomes.
- [x] `execution_id` remains available for later recovery/debug inspection.
- [x] Traceback, cleanup internals, process metadata, and large raw diagnostics are not copied into the normal public error outcome.
- [x] Existing lifecycle terminal-state behavior and ADR 0004 failure semantics remain unchanged.
