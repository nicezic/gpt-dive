# Command Surface Simplification

## Problem Statement

Code Mode was simplified from two overlapping foreground shell paths to one Pydantic `run_command()` path. That simplification is correct, but the migration exposed two policy mismatches that now make the command surface inconsistent.

First, direct WSL execution is supposed to require an explicit model-facing permission declaration. `wsl2_sync` enforces that declaration, while `wsl2_async start` can currently launch the same class of direct WSL command without it. The sync and async entry points therefore express different intent requirements for equivalent execution authority.

Second, replacing the old Dive shell execution path with the Harness `run_command()` also inherited Harness's default destructive-command denylist. That upstream default is intentional for Harness, but it was not an intended policy change for GPT Dive. Ordinary development commands such as `rm` are therefore rejected even though the migration goal was interface simplification rather than introduction of a new shell-command policy.

The desired result is one clear normal Code Mode shell with the same practical shell semantics as before, plus explicit permission parity across direct WSL launch paths.

## Solution

```text
Normal local work
code_mode → FileSystem / [Pydantic] run_command()
             │
             └─ normal host shell semantics
                no accidental upstream command denylist

Exceptional direct WSL execution
shared direct-WSL permission declaration
             │
             ├─ wsl2_sync       → permission required
             └─ wsl2_async
                  └─ start      → permission required
                     status/result/cancel → no permission required

OpenAI tunnel transport failure
[Dive] gz64() → last-resort command transport

Future task awareness
MCP result middleware → TrackedTasks[]
```

Keep Pydantic `run_command()` as the single normal foreground shell interface. Configure its Harness Shell explicitly so the upstream default destructive-command denylist is not inherited accidentally by GPT Dive. This restores the intended migration semantics without recreating the removed Dive shell API.

Use one shared direct-WSL permission declaration for both synchronous execution and asynchronous job start. The declaration remains an intent signal for the model, not an OS security boundary. Async lifecycle reads and cancellation do not launch new shell work and therefore remain permission-free.

## User Stories

1. As Web SOL, I want one normal foreground shell primitive, so that I do not have to choose between overlapping Dive and Pydantic command interfaces.
2. As Web SOL, I want ordinary development shell commands to keep working after the `run_command()` migration, so that interface simplification does not silently change normal shell behavior.
3. As Web SOL, I want GPT Dive to opt into shell restrictions deliberately rather than inherit upstream defaults accidentally, so that policy changes are explicit and reviewable.
4. As Web SOL, I want direct synchronous WSL execution to require the exact intent declaration, so that exceptional host-level execution remains visibly deliberate.
5. As Web SOL, I want direct asynchronous WSL job start to require the same intent declaration, so that switching from sync to async cannot bypass the direct-execution policy.
6. As Web SOL, I want async `status`, `result`, and `cancel` to remain usable without repeating the permission declaration, so that observing or stopping an already-created job stays lightweight.
7. As Web SOL, I want `wsl2_async capabilities` to advertise the permission requirement for `start`, so that callers can discover the contract instead of relying on remembered documentation.
8. As Web SOL, I want the live MCP schema for direct WSL tools to expose the intended permission contract, so that fresh sessions receive the same rules the implementation enforces.
9. As a maintainer, I want one shared permission declaration rather than separate sync and async constants, so that the two execution paths cannot drift semantically.
10. As a maintainer, I want regression tests at the public command surfaces, so that future Harness upgrades or refactors cannot silently reintroduce the same behavior changes.
11. As a maintainer, I want upstream Harness behavior left unchanged, so that GPT Dive customization remains local and does not fork general Harness policy.
12. As a maintainer, I want the command migration plan to remain the single local SSOT, so that implementation and review do not have to reconcile competing plans for the same redesign.
13. As Web SOL, I want `/`, `/tmp`, `/mnt/c`, and concrete home paths to remain reachable when genuinely needed, so that normal maintenance remains possible without encouraging blind broad searches.
14. As Web SOL, I want broad-search guards to remain separate from shell command policy, so that preventing wasteful recursive search does not become a blanket filesystem or command restriction.
15. As Web SOL, I want tunnel recovery and TrackedTasks to remain separate concerns, so that fixing permission and shell semantics does not expand the scope of the command interface again.

## Implementation Decisions

- Keep `run_command(command, *, timeout_seconds=None) -> str` upstream-shaped. Do not add Dive-specific compatibility parameters or restore the removed shell API.
- Configure the GPT Dive Harness Shell with an explicit empty command denylist. The purpose is to prevent Harness's default destructive-command policy from becoming an accidental GPT Dive policy.
- Do not change Harness upstream defaults. This is a GPT Dive integration decision only.
- Preserve the existing Dive Shell configuration for guard-bin PATH behavior, provider-secret environment filtering, timeout handling, output bounds, process cleanup, and current working-directory behavior.
- Introduce one shared direct-WSL permission declaration and use it for both synchronous direct execution and asynchronous job start.
- Keep synchronous direct execution's permission required in the MCP input schema and validate the exact declaration at runtime.
- Add a permission field to the asynchronous action-based interface. Because the interface multiplexes multiple actions, the field may be optional at the top-level schema, but `start` must reject missing or mismatched permission before launching a job.
- Update asynchronous capability discovery so `start` declares both `command` and `permission` as required inputs; `cwd` and `timeout` remain optional.
- Do not require permission for asynchronous `status`, `result`, or `cancel`; those actions do not create new direct shell execution.
- Keep the permission declaration as a model-facing intent signal rather than an OS security mechanism. Do not add broad command parsing or recursive-search policing to the direct execution layer as part of this change.
- Keep normal Code Mode broad-search misuse guards separate: broad `/` and `/mnt/c` search roots remain rejected by search capabilities while concrete paths and intentional direct WSL maintenance remain possible.
- Keep `gz64()` limited to transport recovery and keep TrackedTasks outside the command-surface redesign.
- Treat fresh-session MCP schema verification as part of completion because the Web session can retain an older tool schema after local server changes.

## Testing Decisions

- Prefer public behavior seams over internal helper tests. The primary seams are the MCP-visible direct WSL contracts and the registered Code Mode `run_command()` behavior.
- Verify synchronous direct execution rejects a wrong permission and exposes the permission as required in the live MCP schema.
- Verify asynchronous `start` rejects both missing and incorrect permission and launches successfully with the exact shared declaration.
- Verify asynchronous capability discovery reports `command` and `permission` as required for `start`.
- Verify asynchronous `status`, `result`, and `cancel` continue to work without a permission argument once a job exists.
- Preserve the existing async lifecycle routing and guard-bin behavior tests while updating start calls to satisfy the new contract.
- Add a Code Mode shell regression test that exercises an ordinary cleanup command through the registered `run_command()` capability. The test should prove the GPT Dive integration does not inherit Harness's default command denylist; it should not test Harness's private `_check_command()` implementation.
- Preserve existing tests for secret environment filtering, timeout/output bounds, process behavior, search-root guards, and transport recovery.
- Run the focused command-surface/runtime suite after implementation, then run the broader project suite if the focused tests pass.
- Verify a fresh ChatGPT Web session after server restart exposes the updated direct-WSL MCP schemas. Same-session schema state is not sufficient evidence.

## Out of Scope

- Reintroducing `local_exec()` or any compatibility wrapper for its old API.
- Changing Pydantic Harness's upstream Shell defaults for other consumers.
- Designing a new general-purpose shell security policy for GPT Dive.
- Treating the permission string as an OS security boundary.
- Requiring permission for async lifecycle observation or cancellation.
- Broad filesystem or dotfile policy changes; current home-path behavior is not part of this fix.
- TrackedTasks or task-lifecycle implementation.
- Tunnel transport redesign.
- Adding Dive-specific parameters or structured return types to Pydantic `run_command()`.

## Further Notes

The `rm` rejection is an integration regression, not a Harness defect: Harness intentionally ships a default destructive-command denylist, while GPT Dive unintentionally inherited that default when it migrated to `run_command()`. The fix should therefore be an explicit GPT Dive Shell configuration rather than an upstream Harness change.

The async permission gap was previously left as a separate decision. This spec resolves that decision: direct command launch must have permission parity across sync and async, while non-launch lifecycle actions remain permission-free.

The local implementation can be correct while the currently open ChatGPT session still advertises an older MCP schema. Final acceptance therefore includes validation from a fresh session after the updated server is loaded.
