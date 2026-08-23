# 02 — Task lifecycle controls

**What to build:** Complete the Task control lifecycle over the existing background execution runtime so Web SOL can collect, cancel, acknowledge, and truthfully observe completed, failed, cancelled, or lost work through one Task surface.

**Blocked by:** 01 — Task-aware background Code Mode.

**Status:** resolved

- [x] Add `task_collect`, `task_cancel`, and `task_ack`; do not add `task_get`.
- [x] Task refresh preserves the existing background Code Mode worker/result interpretation instead of blindly copying low-level process status.
- [x] Working work remains `working`; truthful success/failure/cancellation becomes `completed`/`failed`/`cancelled`.
- [x] Missing required backing execution/result evidence becomes `lost` with no recovery, reconstruction, provider polling, or automatic retry.
- [x] `task_collect` is non-destructive and reports not-ready for working Tasks, retained result/evidence for terminal Tasks when available, and unavailable for lost Tasks.
- [x] `task_cancel` forwards cancellation while working and repeated cancellation is harmless.
- [x] `task_ack` rejects working Tasks and removes terminal/lost Task awareness without altering execution result retention.
- [x] A terminal Task can later become `lost` if normal execution retention removes the needed result before acknowledgement.
