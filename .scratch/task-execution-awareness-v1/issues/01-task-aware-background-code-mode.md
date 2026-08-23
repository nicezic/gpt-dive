# 01 — Task-aware background Code Mode

**What to build:** Make labeled background Code Mode launches create durable Tasks while preserving existing raw background behavior for unlabeled callers. The completed slice must let Web SOL launch work, receive a Task identity immediately, list it structurally, and rediscover it after reopening the Task store.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] A labeled background Code Mode launch returns immediately with distinct `task_id` and backing execution identity plus label/state.
- [ ] Task awareness is stored durably in a small SQLite TaskStore and survives reopening without conversation memory.
- [ ] TaskStore owns only Task awareness fields; execution logs/results/process metadata remain in the existing execution runtime.
- [ ] `task_list()` returns complete structured outstanding Task objects.
- [ ] Unlabeled `code_mode(background=True)` preserves the current raw background lifecycle contract during rollout.
- [ ] If execution starts but Task persistence fails, start fails and best-effort cancellation is attempted without adding an orphan-recovery subsystem.
- [ ] Existing raw background Code Mode tests remain green.
