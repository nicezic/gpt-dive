# 03 — Automatic TrackedTasks and status display

**What to build:** Make ordinary GPT Dive tool traffic automatically remind Web SOL about outstanding Tasks without changing the original tool result contract, and add thin optional status decoration such as `TODOS 3/9`.

**Blocked by:** 02 — Task lifecycle controls.

**Status:** resolved

- [x] Ordinary successful GPT Dive tool results preserve their existing structured result/content and append a compact TrackedTasks `TextContent` block.
- [x] Automatic awareness uses local bounded refresh only and may cap rendered items without changing persisted Task state.
- [x] Awareness refresh/render failure preserves the primary tool result and emits at most a small explicit unavailable message.
- [x] Compact rows include label, lifecycle state, and elapsed time derived from timestamps rather than a persisted duration field.
- [x] Optional `status_cmd` uses the existing bounded local command seam; usable stdout such as `TODOS 3/9` decorates a visible working Task.
- [x] If `status_cmd` is absent, fails, times out, or returns no usable text, static `status` is used when present; otherwise status decoration is omitted.
- [x] Status decoration never changes Task lifecycle state and `status_label` is derived rather than persisted.
- [x] Explicit `task_list()` remains the structured inspection surface; unrelated tool `structuredContent` is not merged with Task objects.
