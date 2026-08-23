# 04 — Peer-review Task canary

**What to build:** Convert the peer-review workflow into the first real Task-aware background consumer so the original blocking pain is proven solved end to end.

**Blocked by:** 03 — Automatic TrackedTasks and status display.

**Status:** ready-for-agent — Task-aware migration complete; live reviewer canary requires explicit reviewer/subagent permission.

- [x] Peer review launches through the existing background Code Mode Task-aware path with a clear human-readable label.
- [x] Launch returns immediately so Web SOL can continue independent foreground work instead of waiting synchronously.
- [x] A later ordinary tool call shows the peer-review Task automatically through TrackedTasks.
- [x] The completed review can be collected non-destructively and remains visible until acknowledgement.
- [x] Failure/cancellation uses the shared Task lifecycle rather than a peer-review-specific tracker or runner framework.
- [ ] Run one live lifecycle canary with the existing low-cost `claude-haiku-4-5` reviewer route after explicit reviewer/subagent permission; reviewer intelligence is not the acceptance target.
- [x] After acknowledgement the Task disappears from automatic awareness while normal execution result-retention behavior remains unchanged.

Local no-provider lifecycle canary passed: Task-aware launch returned immediately, refreshed to `completed`, collected a review-shaped result non-destructively, acknowledged it, and then disappeared from `task_list()`.
