# B2 Mini Spec — `run_code` durable job launch

## Goal / Why

Extend the B1 `run_code` code-mode path so one MCP round-trip can launch multiple independent long-running WSL2 commands without keeping the `run_code` call open until those commands finish.

## Current State

- B1 is FULL PASS: `run_code` exposes async `local_exec` for short concurrent commands and sandbox-side aggregation.
- Durable asynchronous execution already exists in `JobManager.start()` and is exposed separately as `wsl2_start`.
- The callable registry currently exposes only `local_exec`.

## Scope

- Add async `local_start(command, cwd=None, timeout=600)` to the `run_code` callable registry.
- Reuse the existing global `JobManager` and its `start()` semantics.
- Update `run_code` documentation/README to advertise the new capability.
- Prove parallel launch and compatibility with existing `wsl2_status` / `wsl2_result`.

Non-goals for B2:

- No `local_status`, `local_result`, or `local_cancel` inside `run_code`.
- No new async backend, orchestration layer, plugin system, or MCP Tasks work.
- No lifecycle/output-control expansion beyond the demonstrated need.

## Key Decision

**Decision:** expose only `local_start` as a thin registry adapter over `JobManager.start()`.

**Reason:** it closes the demonstrated long-job round-trip gap while preserving the small-core/extensible-registry design and reusing the already-verified Async Core.

**Rejected alternatives:** expose the full job lifecycle inside `run_code` now; create a second async runtime; keep using only repeated top-level `wsl2_start` calls.

**Consequences:** launch batching becomes possible immediately. Status/result/cancel remain top-level MCP calls until a later phase demonstrates value in aggregating them inside `run_code`.

## Failure Policy

`local_start` inherits validation and launch failures from `JobManager.start()`. Do not add fallback backends or recovery behavior in this adapter; those remain owned by the existing Async Core.

## Test Contract

1. `run_code` can call `local_start` and receive the `JobManager.start()` result.
2. Two `local_start` calls can be issued with `asyncio.gather` and return two job IDs without waiting for job completion.
3. Default `cwd` from `run_code(cwd=...)` is inherited when a call omits `cwd`.
4. Existing B1 `local_exec` behavior and broader tests remain green.
5. Live acceptance launches two short durable jobs through actual MCP `run_code`, then verifies completion through existing top-level job lifecycle tools.

## Result

PASS on 2026-08-10.

- Added async `local_start(command, cwd=None, timeout=600)` to the `run_code` callable registry as a thin adapter over the existing `jobs.start()`.
- Kept `local_status`, `local_result`, and `local_cancel` out of B2.
- Targeted code-runtime tests: 6 passed.
- Full regression suite: 13 passed.
- Backend service reload: exit 0.
- Live MCP acceptance: one `run_code` call launched two durable jobs and immediately returned two independent job IDs; both later completed with exit code 0 and expected outputs `B2_A_OK` / `B2_B_OK` through existing `wsl2_status` + `wsl2_result`.
- Initial direct `pytest` invocation failed at collection because the project root was not on `sys.path`; rerunning through `uv run --python 3.14 python -m pytest` passed and showed no product regression.
