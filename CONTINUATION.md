# CONTINUATION — GPT Dive

> Updated: 2026-08-10 11:39 KST
> Repo: `~/gpt-dive`
> Namespace: `@dive`
> Purpose: fresh-session handoff / temporary SSOT
>
> This file is a session-continuity document. It intentionally combines the approved ADR direction, implementation log, live status, and exact next acceptance step. Do not treat volatile runtime/Git state here as permanently durable architecture documentation.

---

## 1. Project purpose

`gpt-dive` is an MCP runtime that lets ChatGPT Web SOL dive directly into the user's local WSL2 environment for:

- quick local shell execution;
- non-blocking durable async jobs;
- Monty-backed CodeMode for parallel local exploration;
- sandbox-side filtering / transformation / aggregation to reduce model-context bloat;
- future registry-based MCP / agent / reviewer / worker orchestration when useful.

Core philosophy:

> **Dive deep locally, surface only what the model needs.**

Architecture principle:

> **Small core, extensible registry, no feature-specific hard coding.**

---

## 2. VERIFIED SSOT — do not re-check from scratch

### Async Core — PASS ✅

Currently verified MCP tools before CodeMode rollout:

- `wsl2_exec`
- `wsl2_start`
- `wsl2_status`
- `wsl2_result`
- `wsl2_cancel`
- `bootstrap`

Verified actual async flow:

```text
wsl2_start
  → status: running
  → job_id
  → backend: systemd
  → poll_interval_ms: 1000
  → retention_days: 5

wsl2_status
  → completed / exit_code 0

wsl2_result
  → expected stdout
```

Actual acceptance command already passed:

```bash
sleep 2; printf 'GPT_DIVE_ASYNC_OK\n'
```

Sync compatibility also passed:

```bash
printf 'GPT_DIVE_SYNC_OK\n'
```

### Async implementation

Long-running work uses:

```text
wsl2_start → wsl2_status → wsl2_result
```

`wsl2_exec` is for quick commands or immediate results only.

Async jobs:

- primary backend: transient `systemd --user` service;
- survive MCP server restart;
- durable state/log storage;
- terminal job/log retention: 5 days;
- cancel supported;
- PID reuse safety and orphan recovery implemented;
- guarded Popen fallback if user systemd is unavailable.

Runtime state:

```text
~/.local/state/gpt-dive/jobs/
```

### Existing command guard policy

Keep unchanged:

- direct native `python`, `python3`, `python3.14` execution blocked;
- `pip`, `pip3` blocked;
- `npm`, `npx`, `yarn` blocked;
- Python should use `uv run --python 3.14 ...`;
- other local WSL2 shell access is intentionally unrestricted.

### MCP Tasks — HOLD

Server-side extension exists for:

```text
io.modelcontextprotocol/tasks
protocol: 2026-07-28
```

But actual ChatGPT Web acceptance returned the fallback `job_id` object instead of a standard MCP Task handle.

Current verdict:

> **Server implementation present / ChatGPT Web client capability not negotiated.**

This does not block Async Core. Do not repeatedly investigate MCP Tasks unless the Web client capability changes.

---

## 3. Tunnel / connector state

Existing Secure MCP Tunnel/profile is preserved.

Profile:

```text
~/.config/tunnel-client/wsl2-exec.yaml
```

Current local backend command:

```text
/home/nicezic/gpt-dive/.venv/bin/python /home/nicezic/gpt-dive/gpt_dive.py
```

User systemd service:

```text
chatgpt-wsl2-mcp.service
```

Current service state at handoff creation:

```text
active
```

Connector namespace/title used by ChatGPT:

```text
@dive
```

---

# 4. ADR — Why GPT Dive exists

## Background

`gpt-dive` was started as a new repo instead of merely extending the older `chatgpt-wsl2-mcp` because repeated ChatGPT Web → local WSL2 work exposed three structural bottlenecks.

1. synchronous `wsl2_exec` blocks the ChatGPT turn for the full duration of long commands;
2. sequential file/search/tool calls create excessive MCP round-trips and slow exploration;
3. large raw tool outputs enter model context even when only a small derived result is needed, wasting token/context budget.

Therefore the design direction is:

- quick, immediate work → direct `wsl2_exec`;
- long work → durable async jobs;
- independent local operations → Monty `run_code` with parallel execution where useful;
- when the final answer does not require full tool output, filter / transform / aggregate inside Monty and return only the necessary result;
- unrestricted shell remains available through `wsl2_exec` when Monty is not the right surface.

## Extensibility decision

`gpt-dive` must not become a fixed collection of feature-specific hard-coded tools.

Monty-visible host capabilities should be registered through a **callable registry** so the core runtime can remain small while capabilities expand gradually.

Initial direction:

```text
Registry
└─ local_exec()
```

Expected future shape, only when actually needed:

```text
Registry
├─ Local
│  ├─ exec()
│  └─ jobs()
├─ MCP
│  ├─ call()
│  └─ discover()
└─ AI
   ├─ agent()
   ├─ review()
   └─ ask()
```

The future tree is architectural intent, not current implementation scope.

The important boundary is:

> `run_code` should evolve as a generic Python orchestration surface over registered capabilities, not as a WSL-shell-specific one-off feature.

## Consequence

Implementation details such as exact Monty API usage, persistent state, sandbox policies, callable names, MCP bridging, and agent orchestration may change after experiments.

The durable architectural intent is the small core + extensible registry boundary.

---

# 5. Phase B1 — approved scope

Goal:

> **`run_code + Monty + local exec` minimal MVP**

Approved boundaries:

- direct `pydantic-monty` use;
- do not pull the full Pydantic AI Harness into `gpt-dive`;
- one new MCP tool: `run_code(code, cwd=None)`;
- one initial registered host callable: `local_exec(...)`;
- local filesystem available read-write through Monty;
- independent calls can use `asyncio.gather`;
- `local_exec` reuses the existing guarded command execution path;
- `run_code` is stateless across MCP calls for B1;
- no persistent REPL/session lifecycle yet;
- no MCP registry integration yet;
- no agents/subagents/Orchestra implementation yet;
- `wsl2_exec` remains the unrestricted shell escape hatch.

Architecture after B1 implementation:

```text
ChatGPT Web
    │
    ▼
 run_code
    │
    ▼
 Monty
    │
    ▼
 CallableRegistry
    │
    └─ local_exec
           │
           ▼
       _run_command
           │
           ▼
        guard-bin
```

---

# 6. Phase B1 implementation log

## Implemented

New file:

```text
code_runtime.py
```

It contains:

- `CallableRegistry`
- `MontyCodeRuntime`

`gpt_dive.py` now includes:

- `MontyCodeRuntime` instance;
- `_build_code_registry(...)`;
- async registered `local_exec(...)`;
- MCP `run_code(...)` tool.

`run_code` behavior:

- executes Monty Python;
- mounts WSL2 `/` as read-write;
- exposes `CWD`;
- exposes async `local_exec(command=..., cwd=..., timeout=...)`;
- encourages sandbox-side filtering/aggregation;
- creates a fresh Monty session per `run_code` call.

`local_exec`:

- delegates to the existing `_run_command()`;
- uses `asyncio.to_thread(...)` so multiple calls can overlap;
- inherits the existing `guard-bin` command policy.

README was minimally updated to describe `run_code`, filesystem access, and the registry direction.

## Dependency

`pyproject.toml` declares:

```text
pydantic-monty>=0.0.19
```

Current `uv.lock` resolved:

```text
pydantic-monty 0.0.21
```

`uv lock --check` passed.

---

# 7. Phase B1 Test Contract — PASS ✅

Targeted contract:

1. `run_code("1 + 2")` returns `3`;
2. Monty can read/write the actual local WSL2 filesystem;
3. `local_exec` works and preserves `guard-bin` blocking policy;
4. two independent `local_exec` calls via `asyncio.gather` actually overlap;
5. a 120 KB raw shell result can be processed inside Monty and return only a compact aggregate without leaking raw content.

Targeted result:

```text
5 passed in 1.30s
```

Full current suite:

```text
12 passed in 1.89s
```

No Async Core regression was observed.

---

# 8. Current live status

## Local backend registry — NEW tool present ✅

Direct local inspection after implementation shows:

```text
bootstrap
run_code
wsl2_cancel
wsl2_exec
wsl2_result
wsl2_start
wsl2_status
```

So the backend itself has **7 tools including `run_code`**.

## Backend reload — PASS ✅

`chatgpt-wsl2-mcp.service` was restarted after B1 implementation.

After reload:

```text
service: active
existing @dive wsl2_exec: working
```

## Current ChatGPT session discovery — stale metadata ⚠️

This current browser/chat session still exposes the old 6-tool metadata and does **not** surface `run_code` as an invokable tool.

The backend is updated; the current ChatGPT session discovery cache is stale.

Therefore B1 status is:

> **Implementation + local tests PASS / live MCP E2E awaiting fresh-session acceptance.**

Do not debug the implementation again merely because this old session lacks `run_code`.

---

# 9. Git status at handoff

Repository:

```text
~/gpt-dive
```

Branch/status:

```text
## No commits yet on main
```

Current files remain untracked because the repository has not received its first commit yet:

```text
?? .gitignore
?? README.md
?? code_runtime.py
?? gpt_dive.py
?? guard-bin/
?? job_manager.py
?? pyproject.toml
?? tasks_extension.py
?? tests/
?? uv.lock
```

No commit/push was performed in this phase.

Do not interpret the untracked state as B1 failure; it is simply the current repo lifecycle state.

---

# 10. Exact next step — fresh-session B1 acceptance

In a **new ChatGPT Web session**, use `@dive` and this file as continuation context.

Do not re-test Async Core or MCP Tasks.

### Step 1 — discovery

Confirm the fresh session exposes:

```text
run_code
wsl2_exec
wsl2_start
wsl2_status
wsl2_result
wsl2_cancel
bootstrap
```

Expected: **7 tools**.

### Step 2 — trivial live `run_code`

Invoke actual MCP `run_code` with:

```python
1 + 2
```

Expected compact result:

```text
3
```

### Step 3 — live registry + aggregation check

Invoke actual MCP `run_code` with a small example equivalent to:

```python
import asyncio

a, b = await asyncio.gather(
    local_exec(command="printf 'alpha\\n'"),
    local_exec(command="printf 'beta\\n'"),
)

{
    "a": a["stdout"].strip(),
    "b": b["stdout"].strip(),
}
```

Expected:

```json
{"a": "alpha", "b": "beta"}
```

The exact wrapper shape may include `result`; judge the actual MCP payload, not this prose example.

### Acceptance verdict

If fresh-session discovery exposes `run_code` and both live calls succeed:

> **Phase B1 = FULL PASS ✅**

Then stop and decide the next small phase before expanding scope.

---

# 11. Working rules for the next session

- Treat this document plus direct live evidence as continuation SSOT.
- Do not repeat already-PASSed Async Core investigation.
- MCP Tasks remains HOLD unless client capability changes.
- trivial inspection → `wsl2_exec`;
- builds/tests/waits/network/long commands → `wsl2_start`;
- prefer parallel independent reads/searches;
- do not surface large raw output when the final result can be computed locally;
- preserve guard-bin policy;
- do not implement Orchestra yet;
- grow the callable registry only one demonstrated capability at a time;
- maintain **small core, extensible registry**;
- repo changes should be tested directly;
- do not create/finalize trusted Wiki/standalone ADR documents merely from this handoff without user + SOL deciding promotion is worthwhile.

---

# 12. Immediate next-development direction after B1

Not yet approved as an implementation phase.

After B1 E2E closes, consult before choosing the next increment. Candidate directions may include improving the callable registry, exposing selected async-job operations inside `run_code`, context/output controls, or lifecycle ergonomics.

Do **not** jump directly to agents, reviewer/worker orchestration, external MCP federation, or a large plugin system merely because the registry permits them.

Build upward from demonstrated need.

---

# 13. MCP Surface v1 — approved and implemented locally

User + SOL approved the Web-facing MCP shape after B1/B2 acceptance.

## Frozen top-level surface

```text
bootstrap
code_mode
wsl2_sync
wsl2_async
```

Exactly **4 tools**.

### `bootstrap`

- Fresh ChatGPT Web session entry point.
- Tool description starts with:
  `Always call `bootstrap` first in a fresh ChatGPT Web session, before using any other `@dive` tool.`
- Server/App description preserves its original meaning and appends exactly:
  `pls,`bootstrap`, first`
- No token, global flag, or server-side bootstrap enforcement was added; SOL follows the description.

### `code_mode`

- Renamed from `run_code`.
- **Primary execution root after `bootstrap`.** Normal GPT work should prefer this path so GPT remains harnessed by the registered capability boundary.
- Pydantic Monty-backed programmable surface.
- MCP schema stays `code` + optional `cwd`.
- Tool description is generic and does not hard-code the capability list.
- Each Monty run receives `CWD` and runtime `CAPABILITIES`.
- Registry v1:
  - `local_exec`
  - `local_start`
  - `local_status`
  - `local_result`
  - `local_cancel`
- Registry adapters reuse existing `_run_command` / `JobManager`; no second execution engine.
- Critical execution rules remain below the harness and apply to all shell routes. Example: `guard-bin` continues to block direct native `python` execution whether reached through `code_mode`, `wsl2_sync`, or a durable async job.
- `wsl2_sync` / `wsl2_async` are lower-level direct-control paths, not the normal orchestration root.

### `wsl2_sync`

- Synchronous direct shell path, renamed from `wsl2_exec`.
- Intended for short commands needing immediate results.

### `wsl2_async`

- Groups former `wsl2_start/status/result/cancel` top-level tools behind one stable action-based schema.
- Schema intentionally uses `action: str` with optional `command`, `job_id`, `cwd`, and `timeout` so backend actions can grow without changing MCP discovery metadata.
- `action="capabilities"` returns the currently supported backend actions.
- Initial lifecycle actions: `start`, `status`, `result`, `cancel`.
- Existing MCP Tasks extension remains optional and intercepts only `wsl2_async(action="start")` when negotiated.

## Local validation before backend reload

- Local MCP discovery: exactly 4 tools — PASS.
- Full suite after surface + registry + Tasks + core-policy changes: **24 passed**.
- Large raw job output aggregation remains sandbox-side in `code_mode` tests.
- B1/B2 execution engine behavior remains reused, not reimplemented.

Implementation plan/result record:

`plans/2026-08-10-mcp-surface-v1.md`

Backend reload was issued after the 24-test local PASS. Fresh-session Web acceptance is the only remaining gate.

---

# 14. Exact next step — one fresh-session MCP Surface v1 acceptance

The next session should **not** repeat B1/B2 or Async Core investigation.

After the backend service has been restarted, open one fresh ChatGPT Web session and use `@dive`.

## Step 1 — discovery + descriptions

Confirm the fresh session exposes exactly:

```text
bootstrap
code_mode
wsl2_sync
wsl2_async
```

Confirm:

- total tools = 4;
- App/server description ends with `pls,`bootstrap`, first`;
- `bootstrap` description begins with the approved fresh-session-first rule;
- old top-level names (`run_code`, `wsl2_exec`, `wsl2_start`, `wsl2_status`, `wsl2_result`, `wsl2_cancel`) are absent.

## Step 2 — bootstrap first

Actually call `bootstrap` before the other tools and confirm trusted Wiki packet loads.

## Step 3 — `code_mode` runtime discovery

Call `code_mode` with:

```python
CAPABILITIES
```

Expected capability names include exactly the current registry v1:

```text
local_exec
local_start
local_status
local_result
local_cancel
```

Then call `code_mode` with `1 + 2`; expected result `3`.

## Step 4 — `wsl2_sync`

Run a trivial command such as:

```text
printf 'WSL2_SYNC_OK\n'
```

Expected exit 0 and matching stdout.

## Step 5 — `wsl2_async`

First call:

```text
action=capabilities
```

Confirm actions include start/status/result/cancel.

Then start one short durable job, retrieve status/result through the grouped tool, and confirm expected output.

## Acceptance verdict

If all five steps pass:

> **MCP Surface v1 = FULL PASS ✅**

Then stop. Future capability growth should prefer `code_mode` registry or `wsl2_async` backend actions without changing the four-tool MCP surface unless a demonstrated need justifies it.

