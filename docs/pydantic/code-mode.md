# Code Mode × Pydantic Monty

> Repository implementation guide. Runtime lifecycle and deadline ownership are canonical in `docs/runtime/`; Web SOL operating guidance belongs in the Wiki.

## Purpose

Code Mode is GPT Dive's programmable local execution root. It keeps the public MCP surface small while giving one Monty program direct access to a typed, discoverable capability registry.

```text
code_mode(label, code, payload?, cwd?, delivery?, dedupe_key?)
        │
        ▼
always-durable Execution
        │
        ▼
code_mode_worker
        │
        ▼
fresh Monty runtime + fresh CallableRegistry
        │
        ▼
15 capabilities
```

Durability and Task publication are outside Monty. There are no Task lifecycle capabilities inside the registry.

## Construction

`build_code_registry(default_cwd, *, record)` constructs one registry per Execution. The small typed runtime record carries only the artifact boundary and live remaining work deadline inherited by child capabilities.

```python
effective_cwd = (
    Path(default_cwd).expanduser().resolve()
    if default_cwd is not None
    else Path.home().resolve()
)
```

`code_mode_worker.py` reconstructs this registry after the generic Execution Worker has won the `accepted → running` claim. The MCP server and Worker do not serialize live Python callables across the process boundary.

## Model-facing contract

```text
direct capability exists  → call it
dependent operations      → sequential await
independent operations    → asyncio.gather(...)
short direct CLI need     → await run_command(...)
deep delegated work       → subagent_call / agy_worker / peer_review
immediate public awareness→ outer code_mode delivery="task"
Task lifecycle            → outer task MCP tool
```

The Monty environment receives:

- `CWD`: resolved default working directory;
- `CAPABILITIES`: live signature and docstring metadata, not a callable mapping;
- `PAYLOAD`: only when the outer call supplied a string payload.

`BACKGROUND` is intentionally absent. Every Execution is durable; response delivery is not an execution mode.

## Capability registry

```text
FileSystem 8
├─ read_file / write_file / edit_file
├─ list_directory / search_files / find_files
└─ create_directory / file_info

Agent and model 3
├─ agy_worker(task, model?, cwd?, conversation_id?)
├─ subagent_call(alias, task, output_tokens_limit?, cwd?)
└─ peer_review(alias, prompt, cwd?)

Other 4
├─ council_emit(council_dir, message, expected_head?)
├─ run_command(command)
├─ gz64(payload)
└─ deadline_remaining()
```

The three agent/model capabilities keep separate semantic contracts. Only their common deadline ownership changed: model-supplied `timeout` arguments were removed, and Runtime passes each underlying worker an effective budget.

## Model-facing contract and static checking

`CallableRegistry` owns one generated capability definition per registered callable. The same definition feeds the outer pre-call catalog, Monty type-check stubs, host validation, and runtime `CAPABILITIES` reflection.

```text
registered callable + typed return
        │
        ├─ outer generated catalog → first-call contract
        ├─ Monty stubs             → static enforcement
        ├─ host validation         → runtime backstop
        └─ CAPABILITIES            → reflection / fallback
```

The outer catalog is visible before the model writes `code`, so discovery-only calls are not the normal correctness path. Runtime stubs preserve the real Python positional/keyword signature even when the model-facing catalog renders structured arguments as named parameters.

There are no argument aliases, silent repair, or unchecked fallback. An invented argument or invalid typed result is a visible typing/validation error rather than a silently dropped field.

## Filesystem boundary

GPT Dive binds the upstream Harness FileSystem toolset and resolves relative paths from `CWD`.

```text
READ / WRITE
├─ path allowed by OS permissions
├─ credential/secret deny pattern → reject
├─ recursive root `/` or `/mnt/c` → search operation rejects as too broad
└─ read_file contract (ADR 0011)
   ├─ line_numbers=False (default) → pure raw text (safe for json.loads, AST, edit_file)
   └─ line_numbers=True (raw=False) → inspection formatting with headers and line numbers
```

Monty's direct `Path` operations use the same host-backed policy, so bypassing the registered FileSystem names does not bypass secret-path authorization. `read_file` returns raw file text by default (`line_numbers=False`), preventing impedance mismatches when passing read content to `json.loads` or `edit_file(old_text=...)`. Harness optimistic `expected_hash` checks remain intact for writes and edits.

## Direct command capability

`run_command` is a narrow local capability, not the four-tool Harness Shell bundle.

```text
await run_command(command)
├─ cwd = Execution CWD
├─ PATH = guard-bin first
├─ provider/API secret environment removed
├─ timeout = Runtime-owned remaining budget
├─ process = isolated session/process group
├─ raw stdout/stderr = private /tmp spool, ≤ 8 MiB each
├─ terminal = SQLite evidence 저장 시도
└─ return = exit_code / stdout / stderr / duration_ms / truncated
```

The command has no caller timeout and no start/check/stop action. Stdout and stderr are not stripped. Model-visible output is capped at 8,000 characters. Raw evidence stays private; SQLite persistence failure does not replace the original `run_command` result, and no private evidence path is returned.

An explicit `systemd-run --user` sibling handoff is permitted only when the caller intentionally leaves GPT Dive Runtime and accepts the loss of Execution/Task/deadline guarantees. `setsid` is not an escape contract.

## Payload boundary

Use outer `payload=` for multiline or quoting-sensitive opaque data so `code=` stays executable logic:

```python
packet = PAYLOAD
result = await peer_review(alias="micu", prompt=packet)
result
```

Payload is optional. It must be a string when present; structured data should be serialized by the caller and parsed inside Monty.

## Subagent workspace bundle

`subagent_call` launches a separate local coding-agent slot. Its child worker still uses the Harness bundle:

```text
FileSystem(root_dir=workspace)
Shell(cwd=workspace, guard-bin, max_output_chars=50_000)
RepoContext(workspace_dir=workspace, nested_traversal=True)
ToolOutputLimits(spill then truncate)
```

This bundle is distinct from the direct Code Mode registry. Both share lower security intent, but a change to one does not mechanically alter the other.

## Task and deadline boundary

```text
outer Runtime
├─ 100s inline wait
├─ 110s MCP response deadline
├─ 43190s work cutoff (12h - 10s)
└─ 43200s absolute lifetime (12h)

inner Monty
├─ cannot choose or extend these clocks
├─ reads deadline_remaining()
└─ child calls inherit min(policy, remaining work budget)
```

When inline delivery ends first, Runtime publishes a Task for the same `execution_id`; it does not cancel or replay the Monty program.

## Validation contract

Changes to Code Mode should prove:

1. the registry exposes exactly the intended fifteen names and current signatures;
2. `BACKGROUND`, inner `task_*`, caller `timeout`, and removed command lifecycle names stay absent;
3. representative FileSystem and `run_command` calls work with their policy boundaries;
4. static invalid arguments fail before host dispatch;
5. child budgets come from the owning Execution record;
6. output bounding, cancellation, and process reap are verified;
7. inline completion, Task publication, non-destructive get, and explicit dismissal pass through the public runtime;
8. the fresh-session MCP schema is accepted after service reload.

## References

- `src/gpt_dive/code_runtime.py`, `src/gpt_dive/code_capabilities.py`
  - Callable registry, Monty execution, and live signature authority.
- `src/gpt_dive/command_runtime.py`
  - Awaited shell, environment, budget, spool, and return contract.
- `docs/runtime/architecture.md`, `docs/runtime/timeouts.md`
  - Outer Execution, Task, and deadline ownership that Monty inherits.
- `docs/pydantic/tool-output-limits.md`
  - Separate output-boundary detail for subagent Harness tools.
