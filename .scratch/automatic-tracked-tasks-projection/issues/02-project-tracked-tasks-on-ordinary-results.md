# 02 — Project TrackedTasks on ordinary results

**What to build:** Make every successful ordinary GPT Dive work result carry an always-present top-level `tracked_tasks` snapshot in both its advertised MCP output schema and actual model-visible structured result, so background completion is rediscovered through ordinary activity without remembered polling.

**Blocked by:** 01 — Restore distinct Task awareness contracts.

**Status:** completed

- [x] Ordinary work-tool output schemas advertise a required top-level `tracked_tasks` list while preserving each tool's existing primary result shape and strictness.
- [x] Actual model-visible structured results contain the same top-level sibling `tracked_tasks`; no outstanding Task produces `tracked_tasks: []`, and unchanged snapshots are still present.
- [x] Automatic items contain `execution_id`, `label`, `state`, `reason`, and derived `elapsed_seconds`, while excluding detailed timestamps, backend, and process metadata.
- [x] Code Mode keeps its primary discriminated outcome directly at top level; awareness is not nested inside program `output` and does not reintroduce an outer `result` wrapper.
- [x] Other ordinary work results keep their existing primary fields and gain only the additive awareness sibling.
- [x] Running and terminal published-undismissed Tasks are reflected from the existing SQLite authority, with terminal Tasks remaining visible until explicit dismissal.
- [x] Model-visible change-only/revision suppression and the old contract-critical appended `content[]` TrackedTasks carrier are removed from awareness semantics; each successful ordinary response is self-contained.
- [x] Projection-read failure is distinguishable from a successful empty Task list and is not hidden by a fallback awareness store or secondary protocol.
- [x] Public tests cover advertised schemas and actual structured results for empty, unchanged, elapsed-advanced, state-changed, dismissed, and projection-failure cases while preserving primary output contracts.
