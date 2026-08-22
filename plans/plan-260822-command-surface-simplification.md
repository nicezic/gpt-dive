# Command Surface Simplification

## Problem Statement

Code Mode has two overlapping foreground shell paths — `[Pydantic] run_command()` and `[Dive] local_exec()` — which creates unnecessary model choice, duplicated policy, and maintenance. The goal is not strict backward compatibility; it is a smaller harness that makes the correct path obvious.

Direct `/` and `/mnt/c` access must remain possible for real WSL/Windows maintenance. The failure mode to prevent is different: purposeless root-wide recursive scans that are slow, noisy, and often unnecessary.

## Solution

```text
Normal local work
code_mode → FileSystem / [Pydantic] run_command()

Exceptional WSL/Win11 maintenance
wsl2_sync(permission=...) → direct Bash, / and /mnt/c allowed

OpenAI tunnel transport failure
[Dive] gz64() → last-resort command transport

Future task awareness
MCP result middleware → TrackedTasks[]
```

Remove `local_exec()` without recreating its old API. Keep Pydantic `run_command()` upstream-shaped. Keep exceptional WSL access, tunnel recovery, and TrackedTasks as separate responsibilities rather than folding them into the normal command API.

## User Stories

1. Web SOL has one unambiguous normal foreground shell primitive.
2. `/`, `/tmp`, `/mnt/c`, and `~/...` remain reachable when genuinely needed without encouraging blind root scans.
3. Dive owns only Dive-specific policy; Pydantic owns normal Shell semantics.
4. TrackedTasks remains independent from command execution.

## Implementation Decisions

- Remove `local_exec()` from Code Mode; migrate active tests/docs to Pydantic `run_command()` or direct FileSystem capabilities.
- Do not preserve `local_exec`-only API: per-call `cwd`, `stdin`, structured `{stdout, stderr, returncode}`, or raw unbounded output.
- Keep `run_command(command, *, timeout_seconds=None) -> str` semantics; do not override it for compatibility.
- Retain existing Dive Shell configuration: guard-bin PATH, provider-secret filtering, timeout, output cap, and managed-process cleanup.
- Keep host access open. `/`, `/tmp`, `/mnt/c`, and specific `~/...` paths are not globally denied.
- Normal Code Mode search rejects `/` and `/mnt/c` as broad search roots; callers narrow the path. This is a misuse guard, not a filesystem sandbox.
- `wsl2_sync` is the exceptional direct-shell path and requires exact permission:
  `for-special-such-as-exceptional-wsl-win11-maintenance; no-stupid-blind-broad-recursive-search`
- The permission is a model-facing intent declaration, not a security boundary. Rare intentional broad system/Windows searches may be valid, so `wsl2_sync` must not hard-ban every recursive root scan.
- Keep `gz64()` only when the OpenAI tunnel/filtering path blocks normal command transport; remove stale `local_exec` references from its docs.
- TrackedTasks stays outside this redesign and remains additive MCP result metadata at the existing result-content middleware seam.

## Testing Decisions

- `CAPABILITIES` drops `local_exec` and retains upstream-shaped `run_command`.
- Preserve guard-bin, secret filtering, timeout/output bounds, and externally relevant concurrency behavior.
- Normal search rejects only broad `/` and `/mnt/c`; `/tmp`, `~/...`, and concrete `/mnt/c/...` subpaths work.
- `wsl2_sync` requires the exact permission while intentional `/` and `/mnt/c` maintenance remains possible.
- Migrate old `local_exec` tests and retain `gz64` transport-recovery coverage.
- Verify the refreshed Web MCP schema/CAPABILITIES in a fresh ChatGPT session; same-session tool schemas are cached.

## Out of Scope

- TrackedTasks/Task lifecycle implementation.
- Dive-specific `run_command` parameters/return types or `local_exec` compatibility wrappers.
- Treating the permission string as an OS security mechanism.
- `wsl2_async start` permission parity; decide separately if needed.

## Why This Shape

One normal command path reduces model hesitation and custom maintenance. Exceptional WSL maintenance and tunnel recovery still exist, but are explicit and rare. TrackedTasks remains at the MCP result seam where it can observe every ordinary tool result without coupling to Shell.
