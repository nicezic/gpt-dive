# 04 — Lock the LLM contract and live canary

**What to build:** Lock the new LLM-optimized output contract against regression, clean stale naming only along the changed output path, and verify the actual MCP-visible behavior end to end with live Code Mode and Task canaries.

**Blocked by:** 01 — Straight-through completed output; 02 — Unify Task delivery vocabulary; 03 — Flatten public error outcomes.

**Status:** implemented-awaiting-live-reload

- [x] Exact public-contract tests fail if redundant fields such as `label`, `stdout`, backend/process/timing metadata, or nested semantic `result` wrappers are reintroduced.
- [x] Changed-path naming converges on `kind`, `execution_id`, `output`, `state`, `code`, and `message` without keeping stale aliases beside them unnecessarily.
- [x] No repo-wide terminology cleanup, TrackedTasks connector fix, raw-evidence feature, bootstrap overhaul, or new streaming/event framework is pulled into this ticket.
- [ ] A live MCP completed canary shows the minimal completed shape and no accumulated `print()` output.
- [ ] A live Task canary confirms immediate task outcome and later `task(get)` use the same outcome vocabulary and retained completion semantics.
- [ ] A live failure canary confirms the compact error shape.
- [x] Relevant runtime/spec documentation is synchronized only where the implemented contract would otherwise be stale.
- [x] The full relevant regression suite passes and ADR 0004 invariants remain intact.

> Live blocker: the system `gpt-dive-tunnel.service` process predates the 01–04 source changes. A completed canary against that pre-reload process still returned stale `label`, nested `result`, and accumulated `stdout`; rerun all three canaries after the service is reloaded.
