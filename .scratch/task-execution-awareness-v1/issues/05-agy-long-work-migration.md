# 05 — AGY long-work Task migration

**What to build:** Move long unattended AGY workflows onto the same Task-aware background Code Mode path and reuse AGY-owned status artifacts for lightweight progress display instead of creating an AGY-specific task runtime.

**Blocked by:** 04 — live reviewer canary intentionally skipped by user decision; Task-aware runtime prerequisites are complete.

**Status:** resolved

- [x] Long AGY work launches through Task-aware background Code Mode and returns a Task identity immediately.
- [x] AGY keeps its worker-specific workflow/result semantics above the shared execution path; no AGY-specific Task manager or runner registry is introduced.
- [x] Existing AGY status artifacts can be exposed through `status_cmd`, producing compact display text such as `TODOS 3/9` without AGY writing Task lifecycle state directly.
- [x] Ordinary later GPT Dive activity surfaces the AGY Task through automatic TrackedTasks.
- [x] AGY result collection, cancellation, lost handling, and acknowledgement use the same Task controls proven by earlier tickets.
- [x] Existing guidance that teaches raw background Job handles for the migrated long-work path is updated to the Task-aware workflow.
- [x] Conduit migration and wide Job→Execution terminology cleanup remain out of scope for this ticket set.

Local no-provider AGY-style canary passed: a Task-aware background launch returned immediately, `status_cmd` read an AGY-formatted `status.md` into TrackedTasks, collection returned the retained result, acknowledgement removed Task awareness, and no AGY-specific Task runtime was introduced.
