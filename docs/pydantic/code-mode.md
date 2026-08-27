# Code Mode × Pydantic Harness

> Repository implementation guide for GPT Dive `code_mode`. Web SOL operating guidance lives in `~/wiki/workflow/pydantic-ai/code-mode.md`.

## Construction

`build_code_registry(default_cwd, *, task_list, task_collect, task_cancel, task_ack)` in `src/gpt_dive/code_capabilities.py` constructs one `CallableRegistry` per Code Mode run. `src/gpt_dive/app.py` injects the MCP-side singletons; the background worker (`code_mode_worker.py`) injects its own wiring and imports this module instead of the MCP server.

The effective workspace is:

```python
workspace = (
    Path(default_cwd).expanduser().resolve()
    if default_cwd is not None
    else Path.home().resolve()
)
```

That workspace drives the primary read/write Harness FileSystem root. Additional trusted reference trees are exposed only through read-side dispatch.

## Model-facing programming contract

`code_mode` is a Monty/Python orchestration surface, not a shell launcher. Prefer the smallest matching primitive:

```text
direct capability available → call it directly
dependent operations        → sequential await
independent operations      → asyncio.gather(...)
long-running background job → pass task={label, ...}
delegated deep execution    → subagent_call(...) or agy_worker(...)
```

Code Mode enforces fixed execution deadlines:

- **Foreground:** fixed 110.0s response deadline: 100s execution cutoff plus a 10s cleanup window. Timeout returns `{ok: false, error: {code: "code_mode_timeout", cleanup_status: "complete" | "failed" | "pending", ...}}`; pending cleanup remains runtime-owned.
- **Detached background (`task` object provided):** fixed 600.0s deadline tracked in SQLite TaskStore.

Canonical deadline, cleanup, and nested-worker boundaries: `docs/runtime/timeouts.md`.

## Direct Harness FileSystem

GPT Dive constructs:

```python
FileSystem(root_dir=workspace).get_toolset()
```

and registers the bound async methods directly:

- `read_file`
- `write_file`
- `edit_file`
- `list_directory`
- `search_files`
- `find_files`
- `create_directory`
- `file_info`

This intentionally reuses upstream Harness semantics rather than wrapping or reimplementing them.

Important inherited behavior includes bounded reads/searches, binary detection, and optimistic `expected_hash` checks for writes/edits. GPT Dive supplies the host filesystem authorization policy around those Harness operations.

### Host filesystem boundary

Code Mode uses one simple local policy:

```text
READ  -> host filesystem `/`, except credential/secret paths
WRITE -> host filesystem `/`, except credential/secret paths and normal OS permission failures
```

Relative paths resolve from the effective `cwd`. Absolute and `~/...` reads or writes may target any host path allowed by the OS unless it matches the shared credential/secret deny policy. `write_file`, `edit_file`, and `create_directory` therefore support `/tmp` and other writable host paths without separate root exceptions.

The same policy also applies to direct Monty filesystem primitives such as `Path.read_text()` and `Path.write_text()` through GPT Dive's host-backed Monty OS adapter, so direct Python code cannot bypass the FileSystem capability boundary. Ordinary writable `.git` metadata and repository files are writable wherever the OS permits; explicit secret paths remain denied.

Architecture decision and rejected alternatives: `adr/0004-code-mode-host-filesystem-policy.md`.

## Removal of direct Harness Shell capabilities

Direct Shell capabilities (`run_command`, `start_command`, `check_command`, `stop_command`, `gz64`) are completely removed from the direct Code Mode surface.

- Prevents dual-transport redundancy and confusing model execution paths.
- Code Mode remains focused on Python/Monty orchestration and registered domain capabilities.
- When shell execution is strictly required, delegate via `subagent_call` (which retains the Harness workspace coding bundle with `guard-bin` protection) or `agy_worker`.

## CAPABILITIES contract

The Monty environment receives `CAPABILITIES` as discovery metadata containing signature + description. It is not a callable mapping.

Registered capability functions are inserted as top-level async names and are called directly:

```python
content = await read_file("README.md")
entries = await list_directory(".")
```

This boundary matters because the outer MCP input schema cannot validate arbitrary inner Monty capability calls. Model-facing signatures/descriptions are part of the executable interface and require live acceptance when changed.

### Static type-check boundary

Direct Code Mode statically checks each generated Monty program before capability dispatch. `CallableRegistry` renders type-check stubs mechanically from the same live Python callables used to populate `CAPABILITIES`, so discovery and enforcement share one signature source rather than a second hand-maintained contract. Runtime globals (`CWD`, `CAPABILITIES`, and `PAYLOAD` when present) are declared in the same checker environment.

This layer exists because model-side contract adherence is probabilistic even when the correct signature is already visible. For example, if the live contract is `search_files(pattern=...)`, generated `search_files(query=...)` code is rejected by Monty with a typing error before the host capability executes. There is deliberately no argument aliasing, automatic repair, or unchecked fallback; runtime/Harness validation remains the backstop for errors that cannot be proven statically.

Implementation history and acceptance: `plans/code_mode/plan-260814-static-type-check.md`.

### Async concurrency

Code Mode pre-imports `asyncio` into each Monty program, so generated code can use `await asyncio.gather(...)` without spending a line on a repeated import. Use this for independent awaitable capability calls; dependent work should remain sequential `await` calls.

The concurrency prelude is part of the model-facing Code Mode contract and is also stated in the MCP `code_mode` tool description. Regression coverage proves concurrent calls still overlap when the generated Monty code contains no explicit `import asyncio`.

## Payload boundary

Outer `payload=` is exposed to Monty as `PAYLOAD`. It is the preferred transport for multiline/quoted payloads so `code=` stays small executable logic and does not accumulate shell/JSON/Markdown quoting hazards.

## Subagent workspace bundle

`subagent_call` is a separate registered primitive. Workspace-enabled children are created in `src/gpt_dive/subagent_worker.py` with:

```text
FileSystem(root_dir=workspace)
Shell(cwd=workspace, ..., max_output_chars=50_000)
RepoContext(workspace_dir=workspace, nested_traversal=True)
_build_tool_output_limits()  # Spill >= 8K, TTL 48h
```

The direct Code Mode registry and child-agent capability bundle intentionally share the same lower execution-policy intent but are separate constructions and need separate tests. Detailed output-boundary design lives in `tool-output-limits.md`.

## Search integration

`repo_search` is GPT Dive's Probe-backed repository retrieval capability. Relative `path` values resolve from the Code Mode workspace; absolute/`~/` paths remain explicit. `search_files`, `find_files`, and `repo_search` reject `/` and `/mnt/c` as broad search roots without blocking direct host access.

## Validation contract

When changing the model-facing Code Mode capability surface, prove at minimum:

1. registry discovery exposes the intended native signatures/descriptions (18 capabilities, no direct shell capabilities);
2. representative FileSystem calls work at the public Code Mode seam;
3. containment and protected/stale-write failures remain explicit;
4. detached background executions enforce fixed deadlines (600s) and Task tracking;
5. foreground Code Mode enforces its 100s execution cutoff plus 10s cleanup window and reports complete/failed/pending cleanup without unowned tasks;
6. `subagent_call`, background Code Mode, and the public MCP surface (`bootstrap`, `code_mode`) remain regression-green;
7. statically invalid inner capability calls are rejected before host dispatch while representative valid calls still execute;
8. fresh-session live schema and `CAPABILITIES` discovery pass after service restart.

Completed Files + Shell acceptance: `plans/code_mode/plan-260814-files-and-shell.md`.
