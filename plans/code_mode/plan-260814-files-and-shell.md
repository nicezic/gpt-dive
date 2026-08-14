# Code Mode Files + Shell

Date: 2026-08-14
Status: Implemented — live acceptance PASS

## Goal / Why

Give Web SOL first-class file and execution primitives inside GPT Dive `code_mode` by reusing the official Pydantic AI Harness implementations instead of continuing to route ordinary file work through shell commands.

The immediate problem is that `code_mode` is already the primary programmable WSL2 execution boundary, but routine reads/writes/edits still fall back to `local_exec`. Harness already provides tested FileSystem and Shell toolsets with useful safety, conflict, output, and process-lifecycle behavior. Reusing those primitives reduces custom surface area and lets Web SOL compose structured operations directly in Monty.

## Current State

- `code_mode` builds a per-run `CallableRegistry` from `_build_code_registry(default_cwd)`.
- Existing capabilities include `local_exec`, `subagent_call`, `bare`, `repo_search`, `council_emit`, and `gz64`.
- `repo_search` is already a Probe-backed local search capability using default BM25 ranking over AST-aware code blocks. Its current name and description are sufficient; this plan does not change it.
- Pydantic AI Harness `FileSystem` builds a `FileSystemToolset` whose bound async methods can be called directly without an Agent and can be registered in the Monty callable registry with their native signatures/docstrings.
- Harness FileSystem already provides root/symlink containment, allow/deny/protected patterns, binary detection, bounded reads/searches, and `expected_hash` optimistic-concurrency checks for writes/edits.
- Harness `Shell` provides synchronous and managed-background command tools. It will initially coexist with `local_exec` so actual Code Mode ergonomics and behavior can be compared before either surface is removed.

## Scope

### FileSystem tools

Expose the Harness FileSystem tool surface directly in Code Mode:

- `read_file`
- `write_file`
- `edit_file`
- `list_directory`
- `search_files`
- `find_files`
- `create_directory`
- `file_info`

The filesystem root follows the Code Mode `cwd`. When `cwd` is omitted, use the same effective default root that Code Mode currently exposes as `CWD` rather than introducing a second cwd policy.

### Shell tools

Expose the Harness Shell execution surface in Code Mode:

- `run_command`
- `start_command`
- `check_command`
- `stop_command`

Keep existing `local_exec` unchanged during this experiment. The new Shell surface is additive until evidence from real use shows which execution interface should remain or whether both have distinct value.

## Explicit Non-goals

- No rename or behavioral change to `repo_search`.
- No GBrain integration into the Code Mode registry. GBrain remains a separate indexed Pydantic retrieval layer.
- No RepoContext capability in this change. Existing bootstrap/Wiki orientation is sufficient for now.
- No Planning, Skills, Memory, ConversationSearch, StepPersistence, or other Harness capabilities.
- No custom reimplementation of Harness file or shell semantics merely to make a different API shape.
- No removal of `local_exec` in this patch.
- No ticket decomposition; this is one small sequential capability-surface change.

## Key Decisions

### 1. Reuse Harness FileSystem instead of creating GPT Dive file wrappers

- **Decision:** Register the existing Harness FileSystem toolset methods as Code Mode capabilities.
- **Reason:** The upstream implementation already solves containment, symlink authorization, protected paths, binary handling, result bounding, and stale-write detection. A custom copy would create another contract for Web SOL to learn and another implementation to maintain.
- **Rejected alternatives:** New `fs_read`/`fs_write` wrappers or continuing to use `cat`/`sed`/shell for ordinary file operations.
- **Consequences / tradeoffs:** Code Mode inherits Harness behavior and upstream API evolution. Errors may need only a minimal transport adapter if a Pydantic-specific exception cannot cross the Monty boundary cleanly; do not duplicate filesystem semantics in that adapter.

### 2. Scope FileSystem to Code Mode cwd

- **Decision:** FileSystem root is the effective Code Mode `cwd`.
- **Reason:** `local_exec`, `subagent_call`, and `repo_search` already inherit the Code Mode cwd. File tools should live in the same workspace model, and Harness containment then provides a meaningful repository boundary.
- **Rejected alternatives:** Rooting file tools at `/` or giving every file call an independent absolute-root parameter.
- **Consequences / tradeoffs:** Access outside the chosen workspace requires a Code Mode call with a different `cwd`, which is intentional.

### 3. Add all four Harness Shell tools while retaining local_exec

- **Decision:** Add `run_command`, `start_command`, `check_command`, and `stop_command`; retain `local_exec` for comparison.
- **Reason:** The Harness Shell surface includes command policy, output handling, environment controls, managed background processes, and cleanup behavior that are worth evaluating as a possible replacement or complement to GPT Dive's custom execution primitive.
- **Rejected alternatives:** Add only `run_command`, or replace `local_exec` immediately without real-use evidence.
- **Consequences / tradeoffs:** The registry temporarily has overlapping execution APIs. This is deliberate experimentation, not the desired permanent duplication.

### 4. Leave repo_search alone

- **Decision:** Keep `repo_search` and its existing description unchanged.
- **Reason:** Its description already states that it uses Probe with BM25 ranking and AST-aware blocks, which is enough for discovery through `CAPABILITIES`.
- **Rejected alternatives:** Rename it to `bm25_ast` or advertise Probe in bootstrap.
- **Consequences / tradeoffs:** The name remains engine-neutral enough for a future Probe reranker change while the live description carries the current implementation detail.

## Implementation Direction

- Construct FileSystem and Shell toolsets when building the per-Code-Mode registry so they inherit the run's effective workspace.
- Register the native async tool methods under their Harness names and preserve their useful signatures/docstrings in `CAPABILITIES`.
- Keep adapters as thin as possible. An adapter is justified only for a runtime-boundary concern such as serialization, exception translation, environment wiring, or lifecycle cleanup, not for recreating Harness behavior.
- Preserve Shell lifecycle semantics for managed background processes. Direct registry use does not automatically inherit an Agent's `AsyncExitStack`, so implementation must explicitly verify and preserve required cleanup behavior rather than assuming it occurs.
- Preserve GPT Dive's existing credential/environment safety intent when configuring Harness Shell. Do not silently broaden provider-secret exposure merely because upstream Shell defaults inherit the host environment.
- Do not disturb unrelated dirty work in the repository.

## Failure Policy

- File traversal outside the configured root, protected writes, stale `expected_hash`, invalid file operations, and other Harness-defined recoverable failures should surface clearly to the Monty caller; do not silently fall back to shell execution.
- Shell command rejection, timeout, non-zero exit, and background lifecycle failures should preserve enough structured or labelled evidence for Web SOL to diagnose the result.
- If a Harness return type cannot cross the Monty boundary, convert only the transport representation to a Monty-compatible primitive. Do not fork the underlying capability logic.
- If Shell cleanup cannot be made correct within the Code Mode lifecycle, fail the Shell portion visibly rather than introducing leaked background processes as an accepted behavior.

## Test Contract

At minimum prove:

1. `CAPABILITIES` exposes all 8 FileSystem names with meaningful native signatures/descriptions.
2. `read_file` can read a file under Code Mode `cwd` and returns bounded, line-numbered content.
3. FileSystem rejects a path resolving outside its root.
4. `write_file`/`edit_file` support `expected_hash` and reject a stale hash without modifying the file.
5. `list_directory`, `search_files`, `find_files`, `create_directory`, and `file_info` execute through Monty at least once at the public Code Mode seam.
6. `CAPABILITIES` exposes all 4 Shell names with meaningful signatures/descriptions.
7. `run_command` executes in the Code Mode workspace and reports success/non-zero results in the Harness-defined form.
8. `start_command` returns an id; `check_command` observes it; `stop_command` terminates it and returns final evidence.
9. A Code Mode run does not leak a managed Harness background process after the owning lifecycle ends.
10. Existing `local_exec`, `repo_search`, `subagent_call`, background Code Mode, and current public MCP surface remain regression-green.

Tests should use temporary workspaces/processes and avoid real credentials, network dependencies, destructive commands, or long-lived daemons.

## Acceptance / Validation

- Targeted Code Mode capability tests PASS.
- Existing FileSystem/Shell integration tests added for this patch PASS.
- Full GPT Dive test suite PASS.
- Ruff PASS.
- `git diff --check` PASS.
- Fresh Code Mode probe shows the new file and shell capabilities in live `CAPABILITIES` after MCP reload/schema refresh where needed.
- Inspect the actual diff and preserve unrelated worktree changes.

## Result

Implementation and fresh-session live capability acceptance are complete.

- Registered all 8 Harness FileSystem methods directly in Code Mode with native signatures/docstrings and Code Mode `cwd` as the filesystem root.
- Registered all 4 Harness Shell methods while retaining `local_exec`. Shell uses the same guard-bin PATH and provider-credential stripping intent as subagent workers.
- Added registry-owned async cleanup so Harness background processes are terminated when the owning Monty run ends, including error paths.
- Direct bound Shell methods bypass Harness `call_tool()` output limiting, so Code Mode applies Harness's own `truncate_tail` helper as a thin transport adapter while preserving native signatures/docstrings via `functools.wraps`.
- GBrain structural retrieval located `FileSystemToolset` and `ShellToolset`; authoritative Harness source under `~/ref/pydantic-ai-harness` was then opened to verify native APIs, recoverable-error behavior, environment policy, output limiting, and lifecycle cleanup.

Validation:

- `uv run pytest -q tests/test_code_runtime.py` -> **30 passed**.
- `uv run pytest -q` -> **78 passed**.
- `uv run ruff check src/gpt_dive/code_runtime.py src/gpt_dive/app.py tests/test_code_runtime.py` -> PASS.
- `uv run ruff format --check src/gpt_dive/code_runtime.py tests/test_code_runtime.py` -> PASS.
- `git diff --check` -> PASS.
- Repository-wide Ruff lint/format are not clean because of pre-existing unrelated dirty work (`experiments/council_web_sol_e2e/edge_bridge.py` lint; bootstrap/description and other unrelated formatting hunks). Those files/hunks were deliberately not modified for this change.

Fresh-session live acceptance (2026-08-14):

- The active MCP/tunnel service was confirmed restarted at **2026-08-14 06:36:42 KST** (`MainPID=1357599` at acceptance time). The earlier 05:28 process state was stale historical evidence, not the current runtime.
- Live `CAPABILITIES` exposes all 12 new names: 8 FileSystem tools and 4 Shell tools, with native signatures/descriptions.
- `read_file` returned bounded line-numbered content; `run_command` executed in the Code Mode workspace and demonstrated the 50k Shell output cap.
- Stale `expected_hash` values were rejected by both `write_file` and `edit_file`, and the file remained unchanged.
- `start_command -> check_command -> stop_command` completed successfully, and a separate run-owned background process was confirmed dead after its owning Code Mode call ended (`CLEAN:<pid>`).
- Live acceptance is **PASS**. No additional MCP restart is required for this capability rollout.


## Follow-up — trusted read roots + repo_search cwd (2026-08-14)

A real cross-repository GBrain task exposed an ergonomics gap in Decision 2 above: `cwd=~/gbrain` correctly contained Harness FileSystem access, but normal reference work also needed `~/ref` without changing the primary workspace. A second live probe showed `repo_search(path="src")` resolved from the wrong base instead of Code Mode `cwd`.

### Decision

- Keep `cwd` as the only primary **read/write** workspace.
- Do **not** widen the writable FileSystem root to `~/`.
- Add explicit read-side dispatch for existing trusted home-level roots: `~/ref`, `~/wiki`, `~/gpt-dive`, `~/gbrain`, `~/monsoon`, `~/labs`.
- Only `read_file`, `list_directory`, `search_files`, `find_files`, and `file_info` may use those external roots, and only through explicit absolute/`~/...` paths.
- Keep `write_file`, `edit_file`, and `create_directory` bound directly to the primary workspace FileSystem.
- Relative `../` traversal never switches roots.
- Make relative `repo_search(path=...)` resolve from the Code Mode workspace; absolute/`~/` paths stay explicit.

This supersedes only the earlier consequence that outside-workspace reads always require a different Code Mode `cwd`. It preserves the earlier reason for a meaningful writable repository boundary.

### Why

Harness FileSystem is intentionally single-root and already implements canonical/symlink containment. GPT Dive can preserve that behavior by constructing separate upstream FileSystem toolsets per trusted root and dispatching only read methods, rather than creating a broad `FileSystem(root_dir=~)` or duplicating filesystem authorization semantics.

### Additional test contract

- explicit trusted absolute read/list/search/find/info: PASS
- trusted external write: rejected and target unchanged
- unlisted absolute root read: rejected
- symlink inside trusted root escaping outside it: rejected by Harness containment
- relative `repo_search(path="src")`: resolves to `<cwd>/src`
- existing FileSystem/Shell capability tests remain green

Local acceptance:

- `uv run ruff format --check src/gpt_dive/app.py tests/test_code_runtime.py` -> PASS
- `uv run ruff check src/gpt_dive/app.py tests/test_code_runtime.py` -> PASS
- `uv run pytest -q tests/test_code_runtime.py` -> **34 passed**
- `uv run pytest -q` -> **87 passed**
- `uv run ruff check src/gpt_dive/app.py tests/test_code_runtime.py tests/test_surface.py` -> PASS
- `uv run pyright src/gpt_dive/app.py` -> **0 errors**
- direct source-runtime probe: `cwd=~/gbrain -> read_file(~/ref/pydantic-ai/pyproject.toml)` PASS; `repo_search(path="src")` resolved to `/home/nicezic/gpt-dive/src`.

A service reload is required before the active MCP process exposes this follow-up behavior; fresh-session live acceptance should re-check the model-facing capability descriptions and one real `cwd=~/gbrain -> ~/ref` read after reload.
