# Night Sweep Report — 2026-08-24

Branch: `improve/260824-night-sweep` (on top of `3f73998`, **not merged, not pushed**)
Executor: ox-alpha (opencode), autonomous per user grant: free commits / no push / full autonomy / service restart only if needed (never needed — all validation was offline + subprocess-level; the live MCP service was not touched).

## Why

User request: freely improve the project on a branch using `/improve-codebase-architecture` and `/code-review` judgment. Hot-spot scan pointed at last night's Task/Execution work (`4f7f30d..3f73998`) plus repo-wide gates.

## What changed (6 commits)

| Commit | Change |
|---|---|
| `7f5c104` | ruff UP017 fixes in `gbrain/tests/test-voyage-free-guard.py` (repo-wide `ruff check .` was red at baseline) |
| `947c0b6` | Background Code Mode envelope parsing/normalization unified into `task_runtime.read_execution_result`; deleted duplicated `_background_error` + parser block in `app.py`. Request ref/dir/cleanup helpers now single-owner in `task_runtime`. |
| `9ef7571` | Capability registry construction extracted to `code_capabilities.py` with injected deps (`run_command`, 4 task ops); `code_mode_worker` wires its own TaskStore/ExecutionManager instead of importing app.py. Shared `list_projected_tasks()` replaces triplicated listing composition. |
| `e30be44` | PEP 562 lazy package exports so `python -m gpt_dive.code_mode_worker` does not load the MCP server graph via `gpt_dive/__init__`. |
| `3dafcd3` | Live-contract docs updated to new layout: `docs/pydantic/code-mode.md`, `architecture.md`, `peer-review.md`, runtime source-layout tree. |
| `7fa7758` | `CONTINUATION.md` refreshed: Task/Execution v1 completion pointers + this branch record. |

Net: `app.py` 1262 → ~950 lines; one canonical owner each for result normalization and registry building.

## Deliberate behavior changes

1. `code_mode(action="result", execution_id=X)` where X is a raw shell execution now returns the honest raw shell result instead of a misleading `worker_protocol_error`. Aligns with the shared-normalizer design note in ADR 0001 §5.1 ("Execution이 두 종류를 모두 받을 수 있다").
2. Finer-grained worker protocol error messages collapsed into the shared normalizer wording ("produced no valid result envelope"). No test asserted the old variants.
3. Worker processes build their own default-path TaskStore/ExecutionManager for task capabilities. This matches pre-refactor reality (worker always saw default paths, never test-swapped ones).

## Evidence

- Full suite: **224 passed** (baseline 223 + new passthrough regression test), ruff clean, pyright 0/0, `git diff --check` clean — re-run green at every commit.
- Worker import weight: before 1986 modules with `mcp` loaded → after **1763 modules, `mcp` absent**.
- Live canary A PASS: Task-aware background launch (`label`) → real worker subprocess (new wiring) → `subagent_call(model='m3')` returned exactly `CANARY_A_OK` → `collect_task` normalized result ✓
- Live canary B PASS: `bare(provider='aiapiflow', model='claude-haiku-4-5-20251001', cwd=...)` returned exactly `HAIKU_B_OK` (per user's cheap-model permission).

## Bugs caught during the work

- First version of the delegating wrapper treated normalized success dicts as "still running" because they lack a `ready` key; fixed to trigger only on explicit `ready is False` (matches existing `result.get("ready", True)` convention). Regression test added.

## Candidates considered, deferred (for daylight decision)

- `docs/runtime/adr/0001-...md` is 800 lines but structurally sound; per `/docs` it should be judged by information value. User recently reorganized docs themselves — did not rewrite overnight. Possible future split: acceptance evidence → plans/.
- `ExecutionManager.cleanup()` runs O(n) dir scans on every start/status/result/cancel. Fine at current scale; revisit only if execution dirs grow.
- Conduit snapshot hardcodes limit 8 (mirrors `render_tracked_tasks` default). Consistent with design intent; a shared constant would be cosmetic.

## Morning checklist

```bash
cd ~/gpt-dive
git checkout improve/260824-night-sweep   # already checked out
uv run --python 3.14 python -m pytest -q
uv run --python 3.14 ruff check .
uv run --python 3.14 pyright
git log main..HEAD --oneline              # 6 commits to review
```

Merge decision is yours; nothing was pushed or merged.
