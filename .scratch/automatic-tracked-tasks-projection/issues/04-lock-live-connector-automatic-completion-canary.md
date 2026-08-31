# 04 — Lock live connector automatic-completion canary

**What to build:** Prove the renewed TrackedTasks contract in a fresh ChatGPT connector session by launching background work, continuing ordinary tool activity, and automatically rediscovering its completion without calling `task(list)` to make discovery happen.

**Blocked by:** 02 — Project TrackedTasks on ordinary results; 03 — Align model guidance with automatic rediscovery.

**Status:** completed

- [x] Launch a deterministic short-lived Code Mode Task and continue ordinary tool activity rather than waiting for or polling it.
- [x] An ordinary model-visible result exposes the running Task through top-level `tracked_tasks`, including passive elapsed information, without an intervening `task(list)`.
- [x] A later ordinary result exposes the same Task in its terminal state without `task(list)` being required for discovery.
- [x] A separate explicit `task(list)` call shows the richer detailed Task inspection contract rather than the compact automatic projection.
- [x] Retrieve the terminal result non-destructively, explicitly dismiss it, and verify a later ordinary result no longer includes the dismissed Task.
- [x] Inspect both advertised MCP schema and actual ChatGPT-visible structured output during the canary; server-only `content[]` evidence is not sufficient for acceptance.
- [x] The canary confirms that automatic rediscovery works without changing ADR 0004 durability/lifecycle semantics or ADR 0005 program-output semantics.

## Live canary evidence

- Connector/runtime was restarted after Issue 02/03 so the live server loaded `2a5c057` and the connector resource was re-discovered before this canary.
- Formal canary Task: `hlUNjw` (`live automatic completion canary long`).
- Launch used `code_mode(mode="task")`; launch result already exposed top-level `tracked_tasks`.
- First ordinary call was `wsl_exec("git status --short")`, with no prior `task(list)`. Its model-visible result exposed `hlUNjw` as `running` with `elapsed_seconds: 5`.
- Next ordinary work was the full test suite, not a polling wait. Its model-visible result exposed the same `hlUNjw` as `completed` with `elapsed_seconds: 16`; the suite passed `156` tests.
- Only after automatic completion discovery, `task(list)` showed the richer detailed TaskView for `hlUNjw`, including `accepted_at`, `finished_at`, `published_at`, `updated_at`, and `elapsed_seconds`.
- `task(get, hlUNjw)` returned `LIVE_CANARY_LONG_DONE`. A later ordinary `wsl_exec` still exposed `hlUNjw` as completed, proving result pickup was non-destructive.
- `task(dismiss, hlUNjw)` returned `dismissed: true`; the next ordinary `wsl_exec` no longer contained `hlUNjw` in `tracked_tasks`.
- Restarted-server advertised output schemas were inspected during the canary: all `code_mode` variants require `tracked_tasks`; `wsl_exec` requires `tracked_tasks`; `TrackedTaskView` requires `execution_id`, `label`, `state`, `reason`, and `elapsed_seconds`.
- The actual ChatGPT-visible `code_mode` and `wsl_exec` tool results carried top-level structured `tracked_tasks`; acceptance did not rely on the old `content[]` text carrier.
- No runtime/code change was made in Issue 04. The canary only exercised the already-implemented ADR 0004 lifecycle, ADR 0005 primary program outcome, and ADR 0006 awareness projection.
- A first 6-second probe Task (`FMwNKw`) completed before its first ordinary follow-up could capture a running snapshot, so it was not used as acceptance evidence and was explicitly dismissed after the formal canary.
