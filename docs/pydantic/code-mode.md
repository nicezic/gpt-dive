# Code Mode × Pydantic Harness

> Repository implementation guide for GPT Dive `code_mode`. Web SOL operating guidance lives in `~/wiki/workflow/pydantic-ai/code-mode.md`.

## Construction

`_build_code_registry(default_cwd)` in `src/gpt_dive/app.py` constructs one `CallableRegistry` per Code Mode run.

The effective workspace is:

```python
workspace = (
    Path(default_cwd).expanduser().resolve()
    if default_cwd is not None
    else Path.home().resolve()
)
```

That workspace drives the primary read/write Harness FileSystem root and Harness Shell cwd. Additional trusted reference trees are exposed only through read-side dispatch.

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

Important inherited behavior includes canonical root/symlink containment, protected write patterns, bounded reads/searches, binary detection, and optimistic `expected_hash` checks for writes/edits.

### Trusted read roots

One Harness `FileSystem` remains single-root by design, so GPT Dive keeps the primary `FileSystem(root_dir=workspace)` for read/write semantics and creates separate Harness FileSystem toolsets for trusted reference roots that exist under the user's home:

```text
~/ref
~/wiki
~/gpt-dive
~/gbrain
~/monsoon
~/labs
```

Read-side wrappers (`read_file`, `list_directory`, `search_files`, `find_files`, `file_info`) keep relative paths anchored to the primary workspace. When the caller explicitly supplies an absolute or `~/...` path, GPT Dive dispatches only to the matching primary/trusted root and converts it back to a root-relative path before invoking the upstream Harness method.

Write-side methods (`write_file`, `edit_file`, `create_directory`) are still the primary workspace toolset methods directly, so trusted external roots gain no write authority. Relative `../` traversal does not trigger cross-root dispatch. Each selected upstream FileSystem still resolves canonical/symlink paths before authorization, preserving escape rejection.

Architecture decision and rejected alternatives: `adr/0004-code-mode-trusted-read-roots.md`.

## Direct Harness Shell

GPT Dive constructs `Shell(cwd=workspace, ...)` with repository-specific policy:

- `guard-bin` is prepended to `PATH`.
- provider credential environment patterns are stripped from spawned commands.
- default timeout is configured for GPT Dive's Code Mode use.
- output is bounded to the intended maximum.

The direct registry registers:

- `run_command`
- `start_command`
- `check_command`
- `stop_command`

Harness Shell command filtering is not treated as an OS sandbox. Hard local execution restrictions belong below the harness where possible.

### Direct-method output adapter

Calling bound Shell methods directly bypasses the normal Harness `call_tool()` layer that would apply output truncation. GPT Dive therefore wraps direct Shell registry calls with Harness `truncate_tail` while preserving the native signature/docstring through `functools.wraps`.

This adapter owns transport/lifecycle behavior only; it must not fork Harness command semantics.

## Registry lifecycle

Managed Harness background commands require cleanup even though Code Mode is not running inside a normal Pydantic Agent capability stack.

`CallableRegistry` therefore owns async cleanup callbacks. The Shell toolset exit hook is registered so run-owned managed background processes are terminated when the Monty run finishes, including error paths.

## CAPABILITIES contract

The Monty environment receives `CAPABILITIES` as discovery metadata containing signature + description. It is not a callable mapping.

Registered capability functions are inserted as top-level async names and are called directly:

```python
content = await read_file("README.md")
status = await run_command("git status --short")
```

This boundary matters because the outer MCP input schema cannot validate arbitrary inner Monty capability calls. Model-facing signatures/descriptions are part of the executable interface and require live acceptance when changed.

### Static type-check boundary

Direct Code Mode statically checks each generated Monty program before capability dispatch. `CallableRegistry` renders type-check stubs mechanically from the same live Python callables used to populate `CAPABILITIES`, so discovery and enforcement share one signature source rather than a second hand-maintained contract. Runtime globals (`CWD`, `CAPABILITIES`, and `INPUT` when present) are declared in the same checker environment.

This layer exists because model-side contract adherence is probabilistic even when the correct signature is already visible. For example, if the live contract is `search_files(pattern=...)`, generated `search_files(query=...)` code is rejected by Monty with a typing error before the host capability executes. There is deliberately no argument aliasing, automatic repair, or unchecked fallback; runtime/Harness validation remains the backstop for errors that cannot be proven statically.

Implementation history and acceptance: `plans/code_mode/plan-260814-static-type-check.md`.

## Payload boundary

Outer `input=` is exposed to Monty as `INPUT`. It is the preferred transport for multiline/quoted payloads so `code=` stays small executable logic and does not accumulate shell/JSON/Markdown quoting hazards.

## Subagent workspace bundle

`subagent_call` is a separate registered primitive. Workspace-enabled children are created in `src/gpt_dive/subagent_worker.py` with:

```text
FileSystem(root_dir=workspace)
Shell(cwd=workspace, ...)
RepoContext(workspace_dir=workspace, nested_traversal=True)
ToolOutputLimits()
```

The direct Code Mode registry and child-agent capability bundle intentionally share the same lower execution-policy intent but are separate constructions and need separate tests.

## Search integration

`repo_search` is GPT Dive's Probe-backed repository retrieval capability. It is not a Harness FileSystem method. Relative `path` values resolve from the Code Mode workspace; absolute/`~/` paths remain explicit. This fixes the earlier mismatch where `path="src"` could resolve from the process/home context instead of `cwd`.

## Validation contract

When changing the model-facing Code Mode capability surface, prove at minimum:

1. registry discovery exposes the intended native signatures/descriptions;
2. representative FileSystem and Shell calls work at the public Code Mode seam;
3. containment and protected/stale-write failures remain explicit;
4. managed background processes are cleaned up;
5. provider credentials are not inherited by ordinary Harness Shell subprocesses;
6. existing `local_exec`, `subagent_call`, background Code Mode, and public MCP surface remain regression-green;
7. statically invalid inner capability calls are rejected before host dispatch while representative valid calls still execute;
8. fresh-session live `CAPABILITIES` discovery passes after any required service/schema refresh.

Completed Files + Shell acceptance: `plans/code_mode/plan-260814-files-and-shell.md`.
