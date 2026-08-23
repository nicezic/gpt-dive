# 02 — Task lifecycle controls

**What to build:** Complete the Task control lifecycle over the existing background execution runtime so Web SOL can collect, cancel, acknowledge, and truthfully observe completed, failed, cancelled, or lost work through one Task surface.

**Blocked by:** 01 — Task-aware background Code Mode.

**Status:** ready-for-agent

- [ ] Add `task_collect`, `task_cancel`, and `task_ack`; do not add `task_get`.
- [ ] Task refresh preserves the existing background Code Mode worker/result interpretation instead of blindly copying low-level process status.
- [ ] Working work remains `working`; truthful success/failure/cancellation becomes `completed`/`failed`/`cancelled`.
- [ ] Missing required backing execution/result evidence becomes `lost` with no recovery, reconstruction, provider polling, or automatic retry.
- [ ] `task_collect` is non-destructive and reports not-ready for working Tasks, retained result/evidence for terminal Tasks when available, and unavailable for lost Tasks.
- [ ] `task_cancel` forwards cancellation while working and repeated cancellation is harmless.
- [ ] `task_ack` rejects working Tasks and removes terminal/lost Task awareness without altering execution result retention.
- [ ] A terminal Task can later become `lost` if normal execution retention removes the needed result before acknowledgement.
