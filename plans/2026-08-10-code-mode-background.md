# code_mode Background Execution

## Goal
Enable SOL to detach long-running Monty programs and continue reasoning/planning/discussion while they execute.

## Non-goal
- Autonomous orchestration framework
- Streaming output
- Resource limits/scheduler
- Job discovery API (deferred)
- Auto-retry/recovery
- File locking

## Current State
- `code_mode(code, cwd)` blocks until Monty completion
- Internal async (`asyncio.gather`) works fine
- Registry v1: `local_exec/start/status/result/cancel` exists
- `JobManager` handles durable jobs (systemd-backed, 5-day retention)

## Design

### API
```python
# Execution
code_mode(code: str, background: bool = False, cwd: str | None = None)
# Returns: {"result": ..., "stdout": ...} | {"job_id": "..."}

# Lifecycle
code_mode(action: Literal["status", "result", "cancel"], job_id: str)
# Returns: {"status": ...} | {"result": ..., "stdout": ...} | {"cancelled": True}
```

### Validation
- `code` XOR `(action + job_id)`
- `background` only with `code`
- `action` requires `job_id`

### Behavior
**Foreground (default)**:
- Execute Monty, wait for completion
- Return structured result + stdout
- Same as current behavior

**Background**:
- Start Monty execution via JobManager
- Return `job_id` immediately
- SOL polls via `action="status/result"`

## Files Affected
- `gpt_dive.py` — MCP tool signature, validation, lifecycle routing
- `code_runtime.py` — foreground Monty runtime; shared result contract
- `code_mode_worker.py` — **new small worker entry point** for detached Monty execution
- `job_manager.py` — lifecycle backend reuse; **prefer unchanged**
- tests — background/lifecycle/regression coverage

## Implementation Steps

1. **Add `background` parameter to MCP tool**
   - Update `@mcp.tool` signature
   - Add validation logic

2. **Launch a fresh Code Mode worker through JobManager**
   - `JobManager` is a durable **shell/process lifecycle manager**, not a coroutine executor.
   - `background=True` launches a small `code_mode_worker.py` process through `JobManager.start()`.
   - Pass serializable inputs only: `code` + `cwd` (and explicit future config if needed).
   - The worker creates a fresh Monty runtime and **rebuilds the registry inside the child process**.
   - Do **not** serialize or snapshot `CallableRegistry`; it contains live Python callables.

3. **Implement lifecycle actions**
   - `action="status"` → `JobManager.status(job_id)`
   - `action="result"` → `JobManager.result(job_id)` + parse worker structured envelope
   - `action="cancel"` → `JobManager.cancel(job_id)`
   - Preserve JobManager's existing process lifecycle instead of creating a second async engine.

4. **Handle Monty result serialization**
   - Worker emits one machine-readable JSON envelope to its captured stdout.
   - Envelope carries the existing Code Mode result (`result`, optional `stdout`) or structured error.
   - [ ] Check: Can representative `MontyComplete.output` values serialize to JSON directly?
   - [ ] If not: define the smallest explicit conversion/error contract.
   - Avoid changing JobManager storage unless this proves insufficient.

5. **Error handling**
   - JobManager marks a job `completed` when an exit marker exists, even if `exit_code != 0`.
   - `failed` mainly means the runner disappeared without an exit marker.
   - Therefore Code Mode result handling must inspect **both** JobManager lifecycle state and `exit_code` / worker envelope.
   - Background Monty exception → worker emits structured error and exits non-zero.
   - `action="result"` normalizes that into a clear Code Mode error result.

## Validation

### Test Contract
1. Background job returns `job_id`, not result
2. `status` shows "running" → "completed"
3. `result` returns Monty output + stdout
4. `cancel` stops running job
5. Background Monty exception returns a structured error even though JobManager may report terminal `completed` with non-zero `exit_code`
6. Concurrent background jobs work, including internal `asyncio.gather()` inside a detached Monty program
7. Foreground behavior unchanged (regression)
8. MCP top-level surface remains exactly 4 tools

### Manual Check
```python
# Background
code_mode(code="import time; time.sleep(2); 1+2", background=True)
# → {"job_id": "..."}

# Poll
code_mode(action="status", job_id="...")
# → {"status": "running"}

# Wait, then
code_mode(action="result", job_id="...")
# → {"result": 3, "stdout": ""}
```

## Failure Behavior
- Invalid `job_id` → clear error message
- Job not complete → `status` shows "running", `result` fails
- Background exception → worker exits non-zero with structured error; Code Mode `result` interprets it correctly
- Connection drop during launch → SOL loses `job_id` (accepted edge case)

## Compatibility
- **Breaking change**: None (new optional parameter)
- **MCP schema**: Add `background: bool`, `action: str`, `job_id: str`
- **Existing calls**: `code_mode(code="...")` works unchanged

## Deferred
- Job discovery (list all jobs)
- Max concurrent jobs limit
- Progress/streaming updates
- Resource quotas
- Job priority/scheduling

## Decision
Approved by Design Council 2026-08-10 (SOL + Opus-5 + User).

## Reason
- SOL workflow pain: blocked during long execution
- Web SOL quota abundant: use for parallel thinking
- Platform constraint: no MCP Tasks → polling required
- Minimal addition: reuse JobManager, no new framework
- API improved through review: `background=True` > `sync/start`

## Open Items for Implementation
- [ ] `MontyComplete.output` serialization format across the worker process boundary
- [x] JobManager failure contract verified: normal exit marker → terminal `completed` + `exit_code`; missing marker → `failed`
- [x] Job state storage verified: `~/.local/state/gpt-dive/jobs/{job_id}/`

## SOL Live-Code Correction
Opus plan skeleton은 유지한다. 단, implementation boundary 하나를 live code 기준으로 교정했다:

> **Registry snapshot → worker-side registry rebuild**

`JobManager.start()`는 arbitrary Python coroutine을 직접 durable하게 실행하지 않는다. Shell/process를 durable하게 관리한다. 따라서 background Code Mode는 serializable input만 child worker에 넘기고, worker가 fresh Monty runtime + registry를 재구성하는 방식으로 구현한다.

## Council Final Verification

2026-08-10 Opus-5가 SOL의 live-code correction을 재검토했고 **implementation 가능**으로 승인했다.

- `JobManager = process lifecycle manager` 해석 ✅
- worker process에서 registry rebuild ✅
- `exit_code` + structured envelope 동시 확인 ✅
- 기존 JobManager internals를 가능한 한 변경하지 않는 방향 ✅

따라서 architecture/plan discussion은 종료하고 implementation으로 handoff한다.
