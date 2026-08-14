---
title: ADR — Code Mode Trusted Read-Only Roots
created: 2026-08-14
updated: 2026-08-14
type: decision
status: accepted
---

# ADR — Code Mode Trusted Read-Only Roots

## Decision

Keep Code Mode `cwd` as the primary read/write FileSystem workspace, and allow explicit absolute or `~/` paths under a curated set of trusted roots for **read-only** FileSystem operations.

Current trusted roots:

- `~/ref`
- `~/wiki`
- `~/gpt-dive`
- `~/gbrain`
- `~/monsoon`
- `~/labs`

Read-only access applies to `read_file`, `list_directory`, `search_files`, `find_files`, and `file_info`. `write_file`, `edit_file`, and `create_directory` remain scoped to the primary `cwd` FileSystem.

## Why

A single Harness `FileSystem(root_dir=cwd)` correctly prevents path and symlink escape, but common GPT Dive work often needs a project workspace and authoritative references in different trusted trees, such as `cwd=~/gbrain` while inspecting `~/ref/pydantic-ai`.

Switching `cwd` repeatedly makes multi-source investigation awkward. Widening the primary FileSystem root to the whole home directory would make far more files directly discoverable and writable than the task requires. A curated read-only layer preserves the useful Harness containment model while separating **reference authority** from **write authority**.

## Rejected alternatives

### Whole-home FileSystem root

Rejected as the default because `FileSystem(root_dir=~)` materially broadens recursive discovery and read exposure, while Harness protected patterns primarily protect writes rather than making sensitive files unreadable.

### Disable containment for absolute paths

Rejected because it discards the upstream canonical-path and symlink boundary that the integration is intentionally reusing.

### Separate capability names such as `read_external_file`

Rejected because the security distinction can be enforced by path routing without forcing Web SOL to learn a second parallel read API.

## Consequences

- Relative paths continue to mean `cwd` and preserve the existing R/W contract.
- Explicit absolute/`~/` paths are accepted only when they resolve inside a configured trusted read root.
- Each routed root still uses its own Harness FileSystem, preserving canonical path and symlink containment.
- Unlisted external paths remain rejected.
- Trusted read roots do not automatically grant write access or change Shell's OS-level reach.
- The curated root list is policy and should grow only when a repeated trusted-reference use case justifies it.

## Related current-state docs

- `../code-mode.md` — current implementation and capability behavior.
- `../architecture.md` — overall GPT Dive × Pydantic integration.
- `../../../plans/code_mode/plan-260814-files-and-shell.md` — implementation/acceptance history.
