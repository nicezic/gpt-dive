# Code Mode Surface and Fixed Deadlines

## Purpose and Decision Boundary

This plan turns two related findings into one buildable change:

```text
observed operational failure
└─ a long-lived MCP session became unusable before GPT Dive logged request entry

verified local design gaps
├─ foreground Code Mode has no application-owned outer deadline
└─ the model sees overlapping execution/command lifecycle surfaces

this change
├─ bounds foreground and detached Code Mode lifetimes
└─ removes redundant model-visible command paths
```

The purpose is to make GPT Dive’s model-facing execution contract smaller and ensure GPT Dive can end foreground work before the tunnel owns the first timeout.

This is **not** a claim that Code Mode, TrackedTasks, or a missing timeout caused the observed wedged session. The captured failure most likely occurred at the tunnel/session/stdio lifecycle boundary before the GPT Dive request handler. This plan removes a verified risk and improves failure containment while the original transport root cause remains a separate investigation.

## Incident Background

### 2026-08-27 session wedge

The investigation began after one long-lived ChatGPT/MCP session repeatedly failed GPT Dive tool calls.

```text
ChatGPT tool call
└─ ToolError / ExceptionGroup
   │
   ▼
tunnel-client
├─ returned 502 client_internal
├─ reported no upstream response
└─ did not forward the request to a logged GPT Dive handler entry
   │
   ▼
runtime state
├─ tunnel-client process still alive
├─ python -m gpt_dive process still alive
└─ no status-probe thread explosion observed
```

Restarting `gpt-dive-tunnel.service` restored operation for a different fresh ChatGPT session. The previously failing session retained stale/disabled resource-binding behavior. This makes a long-lived tunnel/MCP session lifecycle failure more plausible than a simple GPT Dive process crash.

### Relevant earlier incident

On 2026-08-19 the Web UI showed the same generic wrapper:

```text
ToolError: UNKNOWN
ExceptionGroup: unhandled errors in a TaskGroup
```

The journal then showed a concrete stdio failure:

```text
MCP connection TTL reached; stopping response forwarding
stdio MCP command failed; requesting tunnel-client shutdown
reason="stdio MCP command stdin write failed"
error="write |1: file already closed"
```

That incident proved that the `ExceptionGroup` text can be only a wrapper around a lower transport/lifecycle failure. It did not establish why the GPT Dive stdio pipe closed first.

## Key Logs and Observations

The following facts are preserved from the 2026-08-27 incident report.

```text
tools/call failure
├─ status_code: 502
├─ failure_source: client_internal
├─ transport_error_kind: unknown
├─ upstream_response_received: false
└─ rpc_method: tools/call
```

Process and application evidence:

```text
tunnel-client PID 131
└─ python -m gpt_dive PID 240

at failure time
├─ both processes alive
├─ no matching "MCP REQUEST START" entry
├─ no GPT Dive traceback identifying an inner application exception
└─ no evidence of runaway status-probe worker creation
```

Post-restart evidence:

```text
restart service
├─ new tunnel-client PID 102402
├─ new GPT Dive PID 102430
├─ normal GPT-DIVE PROCESS START
├─ fresh ChatGPT session works
└─ original ChatGPT session remains stale/disabled
```

`bootstrap` was also failing in the affected session. The TrackedTasks middleware explicitly excludes `bootstrap`, which weakens the hypothesis that concurrent `status_cmd` probes directly caused the whole-session failure.

## Analysis Result

### What the evidence supports

```text
request reaches GPT Dive handler?
├─ evidence says yes → inspect Code Mode / middleware / capability
└─ evidence says no  → inspect tunnel / binding / stdio session first
                         ▲
                         └─ 2026-08-27 evidence points here
```

The most defensible current analysis is:

1. The 502 was produced before a GPT Dive request-start record, so the first observed failing boundary is upstream of the application handler.
2. Both local processes remaining alive rules out a simple process crash at the captured moment.
3. Fresh-session recovery combined with continued failure in the old session is consistent with stale session/resource binding, although it does not prove the exact tunnel defect.
4. `ExceptionGroup` is not a root cause. The missing evidence is its inner transport/session exception and the lifecycle event that made the old binding unusable.
5. Recent TrackedTasks changes are temporally relevant but not causally established. `bootstrap` failing despite its middleware exclusion is contrary evidence against status probes as the direct universal cause.

### Separate verified architecture findings

The code review found two facts that do not depend on assigning the incident root cause:

```text
foreground code_mode
└─ directly awaits the Monty runtime
   └─ no enclosing GPT Dive timeout

model-visible execution choices
├─ code_mode foreground / Task
├─ four inner Shell lifecycle functions
└─ two direct WSL MCP tools
```

The tunnel command protocol supplies a finite response budget, observed here as approximately 120 seconds. Because foreground Code Mode has no shorter outer boundary, a sufficiently long call can leave the tunnel as the first component to time out. That is a real containment defect even if it did not cause this particular wedged session.

The command surfaces are likewise a verified interface problem: they expose distinct lifetime and cleanup models to a probabilistic caller and have already produced confusion about which “background” mechanism survives a Code Mode run.

## Evidence and Rationale

| Kind | Evidence | Resulting conclusion |
|---|---|---|
| Fact | Tunnel journal reported `502`, `client_internal`, `upstream_response_received=false` for `tools/call`. | Investigate the tunnel/session boundary before blaming an application capability. |
| Fact | No matching `MCP REQUEST START` was recorded during the failed call. | There is no evidence that this request entered GPT Dive’s handler. |
| Fact | Tunnel and GPT Dive processes were alive. | The observed state was wedged/unusable rather than a confirmed process crash. |
| Fact | A fresh session worked after restart while the old session stayed stale. | Session/resource binding is a leading area of investigation. |
| Fact | `bootstrap` failed even though TrackedTasks middleware excludes it. | Status probes are not a sufficient direct explanation for the whole-session symptom. |
| Fact | Foreground Code Mode currently has no enclosing application deadline. | Add a fixed deadline shorter than the observed tunnel response budget. |
| Fact | Detached Code Mode already launches through ExecutionManager with a hardcoded 600 seconds. | Preserve the behavior, replace the literal with named policy, and do not expose an input. |
| Fact | Direct Code Mode registers run/start/check/stop Shell functions and `gz64`; MCP also exposes two WSL tools. | The execution contract contains overlapping command lanes. |
| Decision | The user selected fixed `110` seconds for foreground and `600` seconds for Task execution. | GPT Dive application code applies constants based only on `task` presence. |
| Decision | The user selected a clean break for direct Code Mode Shell and hiding both WSL MCP tools. | Remove callable/discovery paths rather than relying on prompt instructions. |
| Constraint | A timeout wrapper is only reliable if cancellation and child cleanup are bounded. | Verify TERM/KILL/reap behavior before accepting the 110-second boundary. |

The causal boundary remains:

```text
this plan can establish
├─ foreground work cannot intentionally run unbounded
├─ fewer model-visible execution paths exist
└─ timeout failure is returned by GPT Dive when the handler receives the call

this plan cannot establish
├─ why the old tunnel session stopped forwarding requests
├─ why no inner tunnel exception was journaled
└─ whether TrackedTasks caused the original wedge
```

## Problem Statement

GPT Dive exposes too many overlapping command-execution concepts to an AI caller. The caller must currently distinguish a foreground Code Mode program, a detached Code Mode Task, four run-scoped Shell functions, and two direct WSL MCP tools. Similar words such as “run,” “start,” “async,” and “background” hide materially different lifetimes and result contracts.

```text
one user intent: do local work
        │
        ▼
current choices
├─ code_mode foreground
├─ code_mode Task
├─ run_command
├─ start/check/stop_command
├─ wsl2_sync
└─ wsl2_async
        │
        ▼
probabilistic routing + invented arguments + lifecycle errors
```

Foreground Code Mode also lacks an enclosing application deadline. A long capability call can therefore outlive the useful MCP request window and let the approximately 120-second tunnel response budget fail first. This is a verified risk of transport/tool failure rather than the established cause of the captured session wedge.

The user has chosen a clean break: direct Code Mode loses its general Shell capabilities; direct WSL tools disappear from MCP; foreground and detached Code Mode receive fixed application-owned deadlines.

## Solution

Expose one model-visible execution root and make its two lifetimes explicit through the existing `task` object.

```text
MCP
├─ bootstrap
└─ code_mode
   │
   ├─ task absent
   │  ├─ synchronous result
   │  └─ fixed 110-second deadline
   │
   └─ task present
      ├─ immediate Task/Execution identity
      └─ fixed 600-second detached execution deadline
```

Remove all general command execution from the direct Code Mode capability registry:

```text
remove
├─ run_command
├─ start_command
├─ check_command
├─ stop_command
└─ gz64
```

Stop registering `wsl2_sync` and `wsl2_async` as MCP tools. Their internal runtime implementations may remain temporarily, but no model-facing schema or instruction may advertise them.

The deadlines are constants in GPT Dive application code. The AI supplies no timeout value. The application performs a deterministic branch on whether `task` is present.

## User Stories

1. AI는 `bootstrap`과 `code_mode`만 보고, `task` 유무로 foreground/백그라운드만 선택한다.
2. Foreground는 110초 안에 구조화된 결과를 반환하고, Task 실행은 600초로 제한된다.
3. 제거된 Shell/WSL 경로는 live schema와 `CAPABILITIES` 어디에도 남지 않는다.

## Implementation Decisions

- Public MCP tools: exactly `bootstrap`, `code_mode`.
- Direct Code Mode capabilities: remove `run_command`, `start_command`, `check_command`, `stop_command`, `gz64`; no aliases.
- Fixed application policy: foreground `110s`, detached Task `600s`; no model-facing timeout input.
- Foreground timeout: normal MCP tool result with stable `code_mode_timeout`, not an uncaught `TimeoutError`.
- `wsl2_sync`/`wsl2_async`: remove MCP registration and package exports; retain private runtime code only if a live internal owner remains.
- Preserve Runtime Task/Execution/TrackedTasks. Remove only the native Tasks extension path that exists solely for `wsl2_async start`.
- Subagent worker Shell is out of scope; this change removes only the direct Code Mode Shell surface.
- Accept ADR only after focused tests, full tests, service restart, and fresh-session schema verification.

## File-by-file Implementation Guide

Line numbers below describe the 2026-08-27 tree. Use the named symbols as the stable anchors if edits move lines.

### 1. `src/gpt_dive/app.py` — MCP surface and timeout owner

#### Current problems

```text
top-level imports / MCP construction
├─ imports `_run_command`
├─ constructs `TasksExtension`
└─ advertises run_command + wsl2_sync + wsl2_async in server prose

code_mode()
├─ foreground branch (around 675-687) directly awaits code_runtime.run
└─ detached branch calls executions.start(..., 600.0) at `_start_background_code_mode`

MCP decorators
├─ wsl2_sync around 444-484
└─ wsl2_async around 807-918
```

#### Required edit

1. Add private constants near the runtime singletons:

```python
_FOREGROUND_CODE_MODE_TIMEOUT_SECONDS = 110.0
_FOREGROUND_CODE_MODE_CLEANUP_SECONDS = 10.0
_BACKGROUND_CODE_MODE_TIMEOUT_SECONDS = 600.0
```

2. Replace the detached literal:

```python
executions.start(command, cwd, _BACKGROUND_CODE_MODE_TIMEOUT_SECONDS)
```

3. Wrap only the foreground launch branch. Do not add an MCP parameter. The observable timeout result is fixed:

```python
{
    "ok": False,
    "error": {
        "code": "code_mode_timeout",
        "message": "Foreground Code Mode reached its 100-second execution cutoff within the fixed 110-second response deadline; relaunch with task.",
        "timeout_seconds": 110.0,
        "execution_cutoff_seconds": 100.0,
        "retry_as_task": True,
        "cleanup_status": "complete",  # or "failed" / "pending"
    },
}
```

Use an internal helper such as `_run_foreground_code_mode(...)` so the timeout/cancellation behavior has one test seam. The helper must:

```text
start the absolute response clock before registry construction
→ create registry and start code_runtime.run as a Task
→ cancel at the 100-second execution cutoff
→ spend at most 10 seconds on cleanup
→ complete: consume the task result/exception
→ pending: retain runtime ownership until its done callback consumes the result
→ return code_mode_timeout with cleanup_status
```

Do not auto-launch a detached Task after timeout; that can duplicate side effects.

4. Remove `run_command=_run_command` from the foreground registry builder call.
5. Remove Shell/WSL routing text from `MCPServer.description`, `MCPServer.instructions`, `code_mode` field descriptions, and `_mcp_code_mode` description. `payload` must no longer be described as a shell-script carrier.
6. Remove both `@mcp.tool` decorators for WSL functions. If their implementations still have internal callers, rename them `_wsl2_sync_internal` and `_wsl2_async_internal`; otherwise delete them in the same patch after `rg` proves zero owners.
7. Remove `TasksExtension` import, singleton, and `extensions=[tasks_extension]` because its intercept only owns the now-hidden `wsl2_async start` route. Do **not** remove GPT Dive’s `TaskStore`, `TaskRuntime`, or TrackedTasks middleware.
8. Remove `_DIRECT_WSL_PERMISSION` and `_required_execution_id` if the private WSL functions are deleted; otherwise keep them private with those functions.

#### Tests owning this edit

- `tests/test_surface.py`
- `tests/test_code_runtime.py`
- `tests/test_code_mode_cancellation.py`
- `tests/test_task_object_detachment.py`

### 2. `src/gpt_dive/code_capabilities.py` — delete direct Code Mode Shell

#### Current problems

```text
build_code_registry(..., run_command=...)
├─ constructs Harness Shell around 135-157
├─ defines gz64 around 279-283
├─ wraps/registers run/start/check/stop around 310-320
└─ registers Shell cleanup around 322
```

#### Required edit

1. Remove `RunCommandFn` and the `run_command` parameter from `build_code_registry`.
2. Delete direct Shell construction, environment filtering, output adapter, four registrations, and Shell cleanup registration.
3. Delete `gz64` and its registry entry. Keeping it would leave arbitrary command execution available under an encoded name.
4. Remove imports made dead by those deletions: `base64`, `fnmatch`, `functools`, `gzip`, `os`, `Shell`, `truncate_tail`, `LLM_API_KEY_ENV_PATTERNS`, and `build_runtime_path`.
5. Keep FileSystem, agent/model, repository, council, and Task capabilities unchanged.

Expected live registry after the edit:

```text
FileSystem
├─ read/write/edit/list/search/find/create/info

Agent/Search
├─ agy_worker
├─ subagent_call
├─ peer_review
├─ m3_evidence
└─ council_emit

Task
├─ task_list
├─ task_collect
├─ task_cancel
└─ task_ack
```

### 3. `src/gpt_dive/code_mode_worker.py` — update detached registry assembly

#### Current problem

The worker imports `command_runtime.run_command` and injects it into `build_code_registry` around lines 10-12 and 70-75.

#### Required edit

- Delete the command runner import.
- Change the builder call to `build_code_registry(cwd, **_tracked_task_ops())`.
- Preserve `background=True`; that flag describes the actual outer execution mode.
- Do not add a second timeout here. ExecutionManager already owns the fixed 600-second worker lifetime.

### 4. `src/gpt_dive/worker_subprocess.py` — make the 110-second boundary real

#### Current problem

`_terminate_and_reap()` sends SIGTERM and then awaits `communicate_task` without a deadline at line 70. A worker ignoring SIGTERM can therefore keep foreground Code Mode inside cancellation cleanup indefinitely.

#### Required edit

```text
cancel/timeout
→ SIGTERM process group
→ wait 4 seconds (grace_seconds)
→ still alive: SIGKILL process group
→ wait 4 seconds for communicate/reap
→ bounded communicate cancellation + proc.wait drain
→ return partial output and explicit reaped state
```

- Use the worker-owned 4-second TERM and 4-second KILL windows so cleanup fits inside the outer 10-second window.
- Use bounded waits after SIGTERM and SIGKILL.
- On expiry, send SIGKILL to the same process group and perform one final bounded reap.
- Never synthesize an exit code. `WorkerOutcome` carries `returncode: int | None` and `reaped: bool`; caller cancellation raises an explicit cleanup error if reap cannot be confirmed.
- Any waiter that ignores cancellation remains in an owned cleanup-task set until its result or exception is consumed.
- Log TERM, KILL, and cleanup completion to stderr logging only.

### 5. `src/gpt_dive/__init__.py` — remove obsolete public exports

#### Current problem

`__all__` and TYPE_CHECKING exports still publish `wsl2_sync` and `wsl2_async`.

#### Required edit

```python
__all__ = ["code_mode", "executions", "mcp"]
```

Remove both WSL names from the TYPE_CHECKING import. This does not remove `ExecutionManager`; it removes obsolete package-level entry points.

### 6. `src/gpt_dive/tasks_extension.py` — remove dead native extension

#### Current problem

`TasksExtension.intercept_tool_call()` is specialized to `wsl2_async` with `action="start"`. Once that MCP tool is hidden, the extension has no advertised launch path.

#### Required edit

- After removing its app registration, confirm there are no remaining imports.
- Delete the module and `tests/test_tasks_extension.py` if `rg` shows zero production owners.
- Preserve Runtime Tasks implemented by `TaskStore`/`TaskRuntime`; they are a separate mechanism.

### 7. Internal file disposition

```text
src/gpt_dive/command_runtime.py
└─ delete after status probing is removed and `rg` confirms zero production owners

src/gpt_dive/execution_manager.py
└─ keep; owns detached Code Mode execution and its 600-second enforcement

src/gpt_dive/task_runtime.py
src/gpt_dive/task_store.py
└─ keep; own Task/TrackedTasks behavior. The legacy SQLite `status_cmd` column may
   remain inert for schema compatibility, but Python records and capability output
   must not expose it.

src/gpt_dive/subagent_worker.py
└─ keep its child-agent Harness Shell; not the direct Code Mode surface
```

Do not globally delete every Python function named `run_command`; delete the **model-callable direct Code Mode capability**. The internal command primitive has different owners.

### 8. Test files — exact migration

#### `tests/test_surface.py`

- Rename the four-tool assertion and expect exactly `{bootstrap, code_mode}`.
- Remove all tests from `test_wsl2_async_capabilities_are_runtime_discoverable` through the WSL sync/async guard-policy cases.
- Remove assertions that server prose recommends `run_command`, `wsl2_sync`, or `wsl2_async`.
- Add negative assertions that none of those names appear in live tool discovery or server instructions.
- Assert `code_mode` schema contains no timeout field.

#### `tests/test_code_runtime.py`

Delete tests whose contract is being removed:

```text
test_run_command_works_and_preserves_guard_bin
test_run_command_allows_normal_cleanup_commands
test_run_command_strips_provider_keys
test_code_mode_payload_can_carry_multiline_shell
test_run_command_calls_can_overlap
test_run_command_output_is_bounded
test_gz64_capability_round_trip
test_harness_shell_run_command_uses_workspace_guard_and_strips_provider_keys
test_harness_shell_background_start_check_stop
test_harness_shell_background_is_cleaned_at_code_mode_end
test_harness_shell_direct_registry_preserves_output_cap
test_code_mode_result_passthrough_for_raw_shell_execution
```

Update `test_capabilities_are_runtime_discoverable` to assert the five removed names are absent. Keep representative FileSystem, agent, repository search, and Task names present.

Replace background-test timing helpers such as:

```python
await run_command("sleep 0.15")
```

with runtime-native waits:

```python
await asyncio.sleep(0.15)
```

Add:

- foreground success below deadline;
- foreground controlled timeout using monkeypatched internal timeout constant;
- cancellation cleanup invoked on timeout;
- detached launch passes exactly `600.0` to the fake ExecutionManager;
- removed capability names fail static validation.

#### `tests/test_task_object_detachment.py`

- Remove the three `wsl2_async` contract tests.
- Preserve Code Mode Task lifecycle tests.
- Replace their inner `run_command("sleep ...")` with `asyncio.sleep(...)`.

#### `tests/test_conduit.py`

- Replace the Code Mode fixture’s `run_command("sleep 0.3")` with `asyncio.sleep(0.3)`.
- Preserve the shared Runtime Task domain assertions.

#### `tests/test_code_mode_cancellation.py`

- Keep existing outer-cancellation coverage.
- Add a worker that ignores SIGTERM and prove SIGKILL escalation plus bounded reap.
- Prove cleanup beyond the response deadline returns `cleanup_status=pending` and remains runtime-owned.
- Prove an uncooperative `proc.wait()` is retained, then removed when it completes, with no unowned task.
- After forced timeout/cancellation, run a normal foreground Code Mode call to prove the runtime remains usable.

#### `tests/test_subagent_worker_capabilities.py`

- Do not change the Shell assertions. They cover the child-agent bundle, which is explicitly out of scope.

### 9. Documentation files — remove stale instructions

Update current-state docs in the implementation commit:

```text
README.md
docs/runtime/architecture.md
docs/runtime/operations.md
docs/pydantic/architecture.md
docs/pydantic/code-mode.md
```

Required content changes:

- MCP surface diagrams show only `bootstrap` and `code_mode`.
- Direct Code Mode capability lists contain no Shell or `gz64`.
- Long work guidance says `code_mode(task={...})`.
- Timeout ownership is stated as deterministic GPT Dive constants, never “AI/server decides.”
- Historical plans remain unchanged; add a superseded pointer where readers could mistake them for current state.

## Testing Decisions

- Primary seams: MCP `list_tools`/public `code_mode`, then live `CAPABILITIES`/Monty static validation.
- Do not sleep 110 seconds in tests; monkeypatch the private constant and use a controlled blocking awaitable.
- Test behavior, not decorator/private-dict details: exact tool names, removed capability rejection, timeout result, cancellation, fixed detached deadline, Task lifecycle.
- Exact test-file edits are specified in the file guide above.

Focused command:

```bash
uv run --python 3.14 pytest -q \
  tests/test_surface.py \
  tests/test_code_runtime.py \
  tests/test_code_mode_cancellation.py \
  tests/test_task_object_detachment.py \
  tests/test_task_runtime.py \
  tests/test_execution_manager.py \
  tests/test_conduit.py
```

Final local verification:

```bash
uv run --python 3.14 ruff check src tests
uv run --python 3.14 ruff format --check src tests
uv run --python 3.14 pyright src
uv run --python 3.14 pytest -q
```

## Implementation Plan

1. Harden `worker_subprocess` cleanup first; otherwise the 110-second wrapper is not trustworthy.
2. Apply `app.py` deadlines and hide WSL MCP registrations; update `__init__` and remove the dead Tasks extension.
3. Remove Shell/gz64 from `code_capabilities`, then update both foreground and worker registry callers.
4. Apply the exact test migration above; run focused, then full verification commands.
5. Update current docs, restart the service, validate a fresh-session schema, record evidence, and accept ADR 0003.

## Acceptance Checklist

```text
[x] MCP list_tools == {bootstrap, code_mode}
[x] MCP prose contains no wsl2_sync/wsl2_async routing
[x] Code Mode CAPABILITIES contains no Shell/gz64 command path
[x] removed Monty names fail static validation before dispatch
[x] foreground success remains synchronous
[x] foreground expiry returns code_mode_timeout at fixed 110 seconds
[x] no model-facing timeout input exists
[x] detached Code Mode launches with fixed 600 seconds
[x] Task/TrackedTasks lifecycle remains green
[x] foreground cancellation cleanup is bounded and pending cleanup remains owned
[x] focused tests pass
[x] full tests pass
[x] service restarts cleanly
[ ] fresh-session schema shows exactly two tools (pending external ChatGPT session live check)
[ ] ADR status changed to accepted (pending external ChatGPT session live check)
```

## Out of Scope

- Adding a replacement general CLI capability to direct Code Mode.
- Preserving compatibility aliases for any removed command capability.
- Automatically translating Shell snippets into structured filesystem or repository operations.
- Removing Shell from delegated subagent/coding-worker bundles; those are separate child-agent contracts.
- Deleting ExecutionManager, TaskStore, TrackedTasks, or background Code Mode.
- Redesigning `peer_review`, `subagent_call`, `agy_worker`, or `m3_evidence` timeout parameters.
- Changing the 600-second Task policy to user-configurable input.
- Adding automatic foreground-to-Task promotion or retry.
- Proving or fixing the upstream tunnel/session wedge independently of bounding GPT Dive’s foreground work.
- Rewriting historical ADRs and plans to erase the command surfaces that existed when they were authored.

## Further Notes

“The application selects the timeout” must not be documented as “the server decides” or “the AI chooses.” The exact rule is a deterministic branch in GPT Dive code:

```text
task absent  → fixed 110 seconds
task present → fixed 600 seconds
```

Because direct `run_command` is removed, the previously discussed 100-second foreground and 540-second detached command limits are superseded and require no implementation.

The highest-risk integration detail is cancellation, not the numeric constant. A nominal 110-second wrapper is insufficient if a child worker can ignore cancellation and cleanup can wait indefinitely. Completion therefore requires bounded termination and reap behavior for every remaining cancellable worker reachable from foreground Code Mode.

ADR authority: `docs/runtime/adr/0003-single-code-mode-command-surface-and-fixed-deadlines.md`.

Incident and lifecycle references:

- `docs/runtime/mcp-stdio-lifecycle.md`
  - Operational SSOT for the tunnel-client → GPT Dive stdio boundary and the rule that `ExceptionGroup` is only a wrapper until its leaf exception is known.
- `plans/plan-260819-mcp-stdio-cancellation-debug.md`
  - Earlier cancellation investigation and evidence that active host capability cleanup needed an explicit runtime boundary.
- OpenAI tunnel protocol documentation
  - Defines the command-level response timeout supplied by the tunnel and motivates an application deadline below it.
