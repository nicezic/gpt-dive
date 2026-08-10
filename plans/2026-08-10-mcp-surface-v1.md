# MCP Surface v1 Mini Spec

## Goal / Why

Freeze GPT Dive's Web-facing MCP shape before the next fresh ChatGPT session so later capability growth does not repeatedly require Web MCP metadata refreshes.

## Approved Surface

Exactly four top-level tools:

1. `bootstrap` — fresh-session trusted context.
2. `code_mode` — Pydantic Monty-backed programmable execution over an extensible local capability registry.
3. `wsl2_sync` — short synchronous WSL2 shell execution with immediate result.
4. `wsl2_async` — grouped durable job lifecycle dispatcher.

The server/app description keeps its existing meaning and appends exactly: `pls,`bootstrap`, first`.

`bootstrap` begins with: `Always call bootstrap first in a fresh ChatGPT Web session, before using any other @dive tool.`

## Key Decisions

### 1. Freeze Web surface, grow behind `code_mode`

**Decision:** `code_mode` is the primary execution root. Future reusable local capabilities and GPT workflow rules are added to its registry rather than as new top-level MCP tools whenever practical.

**Reason:** this makes GPT harnessable through one programmable boundary and avoids repeated ChatGPT Web discovery churn. It also allows policies such as capability shaping, parallel composition, and output reduction to happen naturally in the main path instead of depending on prompt discipline.

**Important boundary:** hard execution restrictions remain below the registry and apply to every shell path. For example, the existing `guard-bin` native-Python prohibition is preserved through `code_mode`, `wsl2_sync`, and `wsl2_async`; direct tools are not an escape from critical execution policy.

### 2. Group durable jobs under `wsl2_async`

**Decision:** replace separate `wsl2_start/status/result/cancel` tools with one dispatcher using `action: str` plus stable optional fields.

**Reason:** one stable schema groups one domain and can gain backend actions later without changing the MCP schema.

Initial actions: `start`, `status`, `result`, `cancel`.

### 3. Preserve one engine

`wsl2_async` and `code_mode` local job capabilities both delegate to the existing `JobManager`. No second async runtime is introduced.

### 4. Keep MCP Tasks optional

The existing Tasks extension remains internal and intercepts `wsl2_async(action="start")` when the client negotiates the Tasks extension. This does not add another top-level tool.

## `code_mode` Registry v1

- `local_exec`
- `local_start`
- `local_status`
- `local_result`
- `local_cancel`

Expose `CAPABILITIES` inside each Monty run for runtime discovery so the top-level tool description does not enumerate every capability.

## Failure Policy

- Unknown `wsl2_async.action` fails visibly with a supported-actions message.
- Required fields are validated per action in the backend; keep the external schema stable and permissive enough for future actions.
- Do not add bootstrap enforcement tokens/session state.

## Test Contract

1. Tool registry exposes exactly `bootstrap`, `code_mode`, `wsl2_sync`, `wsl2_async`.
2. `wsl2_sync` preserves former synchronous execution behavior and guard-bin policy.
3. `wsl2_async` routes start/status/result/cancel to `JobManager` with correct validation.
4. `code_mode` retains B1/B2 behavior and adds status/result/cancel plus `CAPABILITIES` discovery.
5. Registry-side multiple job results can be aggregated without surfacing raw output.
6. Tasks extension maps only `wsl2_async(action="start")` to standard Tasks when negotiated.
7. Full regression passes before backend reload.
8. After reload, final Web discovery/metadata acceptance occurs in one fresh ChatGPT session.

## Result

Implementation + local validation PASS; fresh-session Web MCP acceptance pending.

- Top-level local MCP discovery is exactly 4 tools: `bootstrap`, `code_mode`, `wsl2_sync`, `wsl2_async`.
- `code_mode` registry v1 includes `local_exec/start/status/result/cancel` and runtime `CAPABILITIES`.
- `wsl2_async` groups lifecycle actions and adds runtime `action="capabilities"` discovery while keeping a stable string action schema.
- MCP Tasks interception was moved from old `wsl2_start` to `wsl2_async(action="start")`.
- Full regression suite: 24 passed.
- `code_mode` is documented as the primary execution root; `wsl2_sync` / `wsl2_async` are lower-level direct-control paths.
- Core `guard-bin` policy is regression-tested across sync and async direct paths, including native `python` prohibition.
- Backend reload is being issued after local validation; fresh ChatGPT Web discovery acceptance remains.
