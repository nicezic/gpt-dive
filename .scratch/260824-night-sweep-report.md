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

**Update (user decision, still awake):** ADR §18+§19 split executed — implementation order + acceptance checklist now live in `plans/runtime/2026-08-24-task-execution-awareness-v1.md`; the ADR keeps the decision body with a pointer section. Behavior change in "Deliberate behavior changes" #1 was reviewed and approved by the user.
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


## Addendum — user-directed session (still awake)

User approved B-depth rename and requested provider verification. New commits:

- `7ef1596` S1: `worker_subprocess.run_bounded_worker` — one bounded detached-process lifecycle (shield+grace, SIGTERM on timeout with partial output, cancel-safe group termination) adopted by agy/bare/subagent. Fixes real leak: only agy previously survived caller cancellation.
- `f75831f` S2: bare → `model_call` primitive + `peer_review` capability; lane renamed; mechanical, no behavior change.
- `a2f9557` S3: `PROVIDER_ROUTES` SSOT; adding an Anthropic-compatible provider is now one dict entry (+creds key), no alias sacrifice.
- `436424a` S4: exact peer models soft-verified via provider `/v1/models` inside the credentialed worker (host-side check impossible: creds inject keys per-spawn by design). Unknown id → fail-fast with real `available_models`; listing failure never blocks.

Live evidence: wrong model on aiapiflow returns clean error with 17-model catalog; correct haiku passes verification and returns S4_OK. Wiki synced (`f39684b`). Final gates: 228 tests / ruff / pyright / diff --check green.

> Note: S4's SHA above (`436424a`) predates the rebase; it is now `f78fa45`.

## Addendum 2 — post-report commits (recorded 2026-08-25)

Two commits landed after this report was last updated, found by the morning `/code-review`. Kept per user decision; recorded here so the branch report matches reality.

- `d463b38` S5: per-provider default models — `PROVIDER_ROUTES` entries carry `default_model`; omitting `model` resolves to the provider default and passes the same explicit-model verification. A resolved default without `output_tokens_limit` metadata now falls back to `_PEER_DEFAULT_OUTPUT_TOKENS_LIMIT = 8_192` instead of failing fast. Behavior change vs S4's strict path; no test asserted the old variant.
- `904af71` S6: Task `status_cmd` probes run concurrently (max 8 threads) through one shared `probe_status_labels` helper used by both `@dive` awareness and `@c` snapshots — wall time ≈ one probe instead of N × 1s while background work runs. Each probe keeps its own 1s bound.

Final gates after both: **232 tests** / ruff / pyright / diff --check green.

## Addendum 3 — review-cleanup commits (2026-08-25)

Morning `/code-review` findings (Standards axis) cleaned on this same branch per user decision; one commit per finding, full gates green at every step. #4 (data-clump typing across signatures) deliberately deferred; #5/#8 accepted as-is.

- `672277c` C1 (#6): `stderr_tail` becomes the single stderr-cap owner — unused `limit` kwarg dropped, raw `stderr[-2000:]` slices replaced in model_call / subagent_runtime / agy_worker / task_runtime. stdout caps untouched.
- `054b946` C2 (#7): `_run_worker` result identity (model/provider/mode) resolved once instead of four `peer_review` ternaries.
- `9ef8c44` C3 (#2): `WorkerOutcome(NamedTuple)` replaces the string-keyed envelope dict from `run_bounded_worker`; callers use attribute access so typos fail in pyright, not as distant runtime KeyErrors. Timeout test fake now mirrors real asyncio by setting returncode after SIGTERM reap.
- `fd6ccb4` C4 (#1): `worker_failure()` owns timeout/nonzero-exit detection and message wording for all three lanes; lane payloads stay with each caller per the documented envelope policy. Additive change: timeout error payloads across lanes now carry `timed_out: true` (agy already did); no test asserted old wording.
- `2df3f7f` C5 (#3): empty-prompt message shared via `_EMPTY_PROMPT_ERROR`; the `_run_worker` recheck is kept explicitly as a process-boundary defense line with a comment (host-side gate remains the primary validator).

Final gates after C5: **232 tests** / ruff / pyright green.
