# 04 — Peer-review Task canary

**What to build:** Convert the peer-review workflow into the first real Task-aware background consumer so the original blocking pain is proven solved end to end.

**Blocked by:** 03 — Automatic TrackedTasks and status display.

**Status:** ready-for-agent

- [ ] Peer review launches through the existing background Code Mode Task-aware path with a clear human-readable label.
- [ ] Launch returns immediately so Web SOL can continue independent foreground work instead of waiting synchronously.
- [ ] A later ordinary tool call shows the peer-review Task automatically through TrackedTasks.
- [ ] The completed review can be collected non-destructively and remains visible until acknowledgement.
- [ ] Failure/cancellation uses the shared Task lifecycle rather than a peer-review-specific tracker or runner framework.
- [ ] The canary uses a cheap reviewer model suitable for lifecycle validation; reviewer intelligence is not the acceptance target.
- [ ] After acknowledgement the Task disappears from automatic awareness while normal execution result-retention behavior remains unchanged.
