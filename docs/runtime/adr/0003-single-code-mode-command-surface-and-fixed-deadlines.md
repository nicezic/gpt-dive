---
title: ADR - Single Code Mode Surface and Fixed Execution Deadlines
created: 2026-08-27
updated: 2026-08-27
type: decision
status: proposed
---

# ADR 0003 - Single Code Mode Surface and Fixed Execution Deadlines

## Decision summary

GPT Dive will expose one programmable execution tool to the model and remove the overlapping model-visible command lanes.

```text
Model-visible MCP surface
├─ bootstrap
└─ code_mode
   ├─ foreground: fixed 110-second deadline
   └─ task launch: fixed 600-second execution deadline
```

The following Shell capabilities are removed completely from the direct Code Mode registry, not merely omitted from documentation:

```text
removed from Code Mode
├─ run_command
├─ start_command
├─ check_command
├─ stop_command
└─ gz64                # command-execution bypass; removed with the Shell surface
```

The following direct WSL functions stop being MCP tools:

```text
hidden from MCP
├─ wsl2_sync
└─ wsl2_async
```

They may remain as internal Python/runtime functions during this change. They must not appear in MCP tool discovery, MCP instructions, or model-facing schemas. Their internal process primitive may continue to serve runtime-owned work such as bounded Task status probes.

The fixed deadlines are selected by deterministic GPT Dive application code. No AI chooses, infers, or supplies these values.

```text
code_mode request
│
├─ task is absent
│  └─ GPT Dive applies 110 seconds
│
└─ task is present
   └─ GPT Dive starts an Execution with 600 seconds
```

There is no model-facing `code_mode.timeout` parameter.

---

## Problem

GPT Dive currently presents multiple ways to express command execution and two unrelated meanings of background work:

```text
current model-visible concepts
│
├─ code_mode(task=None)       foreground Monty program
├─ code_mode(task={...})      durable detached Monty program
│
├─ run_command               wait for one Shell command
├─ start_command             temporary process inside one Monty run
├─ check_command             inspect that temporary process
├─ stop_command              stop that temporary process
│
├─ wsl2_sync                 direct foreground WSL command
└─ wsl2_async                direct durable WSL command lifecycle
```

`start_command` backgrounding is scoped to one Code Mode registry and is cleaned up when that run ends. `code_mode(task=...)` backgrounding is a durable Execution and Task. Similar words therefore describe different lifetimes, identifiers, result contracts, and cleanup rules.

This complexity is paid by a probabilistic caller. It increases invented arguments, incorrect lifecycle calls, stale command IDs, timeout races, and tool errors. Documentation reminders do not remove the ambiguous choices.

The motivating transport constraint is a tunnel command response budget observed at approximately 120 seconds. Foreground Code Mode currently has no enclosing application deadline, so a long inner capability can occupy the request until the tunnel fails first. The caller then sees a transport-level failure instead of a bounded GPT Dive outcome.

---

## Current reality

As of 2026-08-27:

```text
MCP list_tools
├─ bootstrap
├─ code_mode
├─ wsl2_sync
└─ wsl2_async

Code Mode CAPABILITIES
├─ FileSystem operations
├─ run/start/check/stop command operations
├─ model/agent operations
├─ repository search
└─ Task operations
```

- Foreground `code_mode` directly awaits the Monty runtime without an enclosing deadline.
- Detached `code_mode(task=...)` starts a durable Execution with a hardcoded 600-second timeout.
- Direct Code Mode constructs a Harness `Shell` with a 60-second default command timeout and exposes its four command methods.
- `gz64` decodes an opaque payload and invokes the internal command runner, so leaving it registered would preserve a second model-visible Shell path after removing the four named methods.
- Harness Shell inside a delegated subagent is a separate child-agent contract. This decision does not remove that worker-internal tool bundle.
- `command_runtime.run_command` was initially retained as an internal primitive, then deleted after removal of `status_cmd` probing left it with no production owner.

The distinction is intentional:

```text
removed completely from direct Code Mode
└─ every model-callable path from Monty to a general local shell

retained internally when still owned by runtime code
└─ non-MCP process mechanics not reachable as a Code Mode capability
```

---

## Decision

### 1. One model-visible execution root

The normal MCP surface becomes exactly:

```text
bootstrap
code_mode
```

`code_mode` remains responsible for:

- filesystem operations through registered structured capabilities;
- repository search;
- explicit agent/model capabilities;
- Task-aware detachment through its `task` object;
- lifecycle actions for its own detached executions.

It no longer offers a general local CLI.

### 2. No direct Shell capability in Code Mode

The direct Code Mode registry must not construct or register Harness Shell. `run_command`, `start_command`, `check_command`, and `stop_command` disappear from:

- live `CAPABILITIES` discovery;
- static type-check stubs;
- MCP descriptions and instructions;
- Code Mode documentation and examples;
- direct Code Mode regression tests.

There is no compatibility alias, deprecated stub, automatic translation, or special error suggesting an old function still exists. Old Monty programs using these names fail static validation as unknown capabilities.

`gz64` is removed from the direct registry at the same time because it is an encoded general-command escape hatch and would violate the new no-Shell invariant.

### 3. Direct WSL functions are internal, not MCP tools

`wsl2_sync` and `wsl2_async` stop being registered with the MCP server. Hiding means all of the following:

```text
list_tools                → names absent
MCP input schemas         → absent
server description        → no routing guidance to them
server instructions       → no routing guidance to them
Tasks extension intercept → no dependency on an advertised wsl2_async tool
```

The underlying Python functions and ExecutionManager may remain for internal operation or a later cleanup. This ADR does not promise them as public Python APIs.

### 4. Fixed foreground deadline

Foreground Code Mode has one application-owned response deadline, split into an execution cutoff and a cleanup window:

```text
response deadline = 110 seconds
├─ execution cutoff = 100 seconds
└─ cleanup window   = 10 seconds
```

The spelling of the implementation constants is not contractual; the values and ownership are. Timing starts before registry construction, so the response deadline encloses registry construction, the Monty run, validation, capability calls, result production, and cancellation cleanup.

The model cannot supply or override the value. At the execution cutoff GPT Dive cancels the run and spends the remaining response budget on bounded cleanup rather than allowing the tunnel to become the first timeout boundary. Cleanup that exceeds the response deadline is retained by the runtime until completion; it is never abandoned as an unowned asyncio task.

The result must identify:

- stable error code `code_mode_timeout`;
- fixed deadline `110`;
- execution cutoff `100`;
- `cleanup_status` of `complete`, `failed`, or `pending`;
- that callers should use `task={...}` for work that may exceed the foreground budget.

`pending` is an explicit transfer of cleanup ownership to the runtime, not a claim that cleanup completed. Worker cleanup likewise never invents an exit code: an un-reaped process is reported with `reaped=false` and `returncode=null`.

### 5. Fixed detached Task deadline

Detached Code Mode retains one fixed runtime-owned deadline:

```text
BACKGROUND_CODE_MODE_TIMEOUT_SECONDS = 600
```

Supplying `task={label, ...}` selects the detached branch. It is not a timeout input and does not cause AI-controlled timeout calculation. The MCP request returns the Task/Execution identity promptly; the durable worker is then bounded by ExecutionManager at 600 seconds.

No automatic promotion occurs when a foreground program appears long-running. Automatic promotion would change the return type from a Code Mode result to a Task identity and break program semantics. The caller must choose `task` at launch.

### 6. Earlier `run_command` deadline proposals are superseded

The earlier proposed values of 100 seconds in foreground and 540 seconds in a Task are not part of the resulting interface because `run_command` is removed from direct Code Mode.

```text
no direct Code Mode run_command
└─ no direct Code Mode run_command timeout policy
```

Internal process owners continue to define their own bounded deadlines. They must not infer them from an AI-generated argument.

### 7. Long agent/model work uses the existing Task branch

Agent/model capabilities remain normal awaited functions inside a Monty program. The lifetime rule is applied to the outer program:

```text
short composition
└─ code_mode(task absent) → at most 110 seconds

possibly long composition
└─ code_mode(task present) → detached, at most 600 seconds
   └─ peer_review/subagent/etc. are awaited inside that worker
```

Individual worker timeouts remain separate child-process safety limits for now. Redesigning those capability signatures is not part of this decision.

---

## Timeout ownership

“GPT Dive applies the timeout” means ordinary deterministic program control:

```text
ChatGPT / AI
└─ supplies code, payload, cwd, and optional task object
   │
   ▼
GPT Dive application
├─ sees task is absent  → 100s execution cutoff + 10s cleanup window
└─ sees task is present → starts fixed 600-second Execution
   │
   ▼
Operating system / ExecutionManager
└─ enforces process cancellation and cleanup
```

The AI does not see a menu of timeout values, choose a mode-specific number, or repair an excessive value. There is no clamp because there is no timeout input.

---

## Consequences

### Positive

- The public MCP surface drops from four tools to two.
- Code Mode has one meaning of background work: its durable `task` branch.
- Temporary Shell command IDs and their check/stop lifecycle disappear from model reasoning.
- A foreground request is bounded before the observed tunnel response budget.
- Long work has one explicit route: launch the whole Code Mode program as a Task.
- Static discovery and static checking agree that direct CLI execution is unavailable.

### Costs

- Direct Code Mode can no longer run local CLIs, tests, package managers, Git commands, servers, watchers, or arbitrary shell scripts.
- Existing prompts and saved Monty programs using any removed command capability break without compatibility support.
- Hiding direct WSL MCP tools removes the model-visible emergency shell lane as well.
- Some workflows must move into structured capabilities, delegated workers, or explicit human/operator execution.
- A 110-second foreground limit assumes the observed approximately 120-second tunnel budget remains valid and leaves a narrow transport margin.

These costs are accepted in exchange for a smaller and less error-prone model contract.

---

## Rejected alternatives

### Keep only `run_command`

Rejected by the final user decision. Although simpler than four Shell methods, it still leaves a general CLI language nested inside Monty and retains timeout/quoting/exit-shape decisions for the model.

### Hide Shell names from documentation but keep them callable

Rejected because live capability discovery and old prompts would continue to invoke them. The ambiguity would remain executable.

### Keep `gz64` as emergency recovery

Rejected because it is functionally a general command lane with an encoded transport. It would make “Code Mode has no Shell” false.

### Let the model supply timeouts

Rejected because the transport budget is an application/runtime constraint, not task content. Variable caller values recreate invalid combinations and tunnel races.

### Automatically detach work at the foreground deadline

Rejected because detachment changes return semantics and can duplicate side effects after the caller has already started a foreground program.

### Delete ExecutionManager and Task tracking with `wsl2_async`

Rejected because those are runtime mechanisms used by background Code Mode and TrackedTasks. Only the redundant MCP entry point is hidden.

---

## Acceptance conditions

```text
MCP discovery
└─ exactly bootstrap + code_mode

Code Mode discovery
└─ no run_command/start_command/check_command/stop_command/gz64

Foreground lifetime
└─ fixed 110-second application deadline; no timeout input

Detached lifetime
└─ task launch uses fixed 600-second Execution deadline

Failure behavior
├─ foreground deadline returns a stable bounded timeout result
├─ result reports cleanup_status=complete|failed|pending
└─ un-reaped workers retain returncode=null and report reaped=false

Documentation
└─ no current-state guidance routes the model to removed/hidden surfaces
```

This ADR moves to `accepted` only after implementation, focused regression tests, full-suite validation, service restart, and fresh-session live schema verification.

---

## References

- `docs/runtime/adr/0001-task-execution-and-trackedtasks-runtime-model.md`
  - Owns the Task, Execution, and TrackedTasks concepts retained by this decision.
- `docs/runtime/adr/0002-task-object-detachment.md`
  - Established `task` as the explicit durable detachment contract; this ADR removes the parallel direct-WSL MCP lane described there.
- `docs/pydantic/code-mode.md`
  - Current Code Mode contract that must be rewritten when this decision is implemented.
- `docs/pydantic/architecture.md`
  - Current integration history and ownership boundary; Shell and four-tool surface sections become historical after implementation.
- `plans/plan-260822-command-surface-simplification.md`
  - Earlier decision to keep `run_command`; superseded for the direct Code Mode command surface by this ADR.
- `src/gpt_dive/app.py`
  - Current authority for MCP registration, Code Mode foreground execution, and the hardcoded detached deadline.
- `src/gpt_dive/code_capabilities.py`
  - Current authority for direct Code Mode capability registration.
- [OpenAI tunnel protocol](https://github.com/openai/tunnel-client/blob/master/docs/protocol.md)
  - Defines the command-level response timeout that motivates an application deadline shorter than the tunnel budget.
