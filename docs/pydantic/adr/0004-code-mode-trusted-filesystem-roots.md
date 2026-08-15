---
title: ADR — Code Mode Trusted Filesystem Roots
created: 2026-08-14
updated: 2026-08-15
type: decision
status: accepted
---

# ADR — Code Mode Trusted Filesystem Roots

## Decision

Keep Code Mode `cwd` as the primary read/write FileSystem workspace, and allow explicit absolute paths under a curated set of trusted external roots.

Trusted read roots:

- `~/ref`
- `~/wiki`
- `~/gpt-dive`
- `~/gbrain`
- `~/monsoon`
- `~/labs`
- `/tmp`

Trusted write roots outside `cwd`:

- `/tmp`

Read-side access applies to `read_file`, `list_directory`, `search_files`, `find_files`, and `file_info`. Write-side access through `write_file`, `edit_file`, and `create_directory` is allowed in the primary `cwd` and in `/tmp`; the home-level reference roots remain read-only when they are outside `cwd`.

## Why

A single Harness `FileSystem(root_dir=cwd)` correctly prevents path and symlink escape, but common GPT Dive work often needs a project workspace and authoritative references in different trusted trees, such as `cwd=~/gbrain` while inspecting `~/ref/pydantic-ai`.

Local tools also commonly place bounded logs, generated reports, spill files, and intermediate artifacts under `/tmp`. Code Mode should be able to inspect and deliberately create or update those temporary artifacts without changing `cwd` or falling back to Shell for ordinary filesystem work.

Widening the primary FileSystem root to the whole home directory would expose far more files than needed. Curated root routing preserves Harness containment while keeping reference trees read-only and granting external write authority only where the operating system already defines a temporary workspace.

## Rejected alternatives

### Whole-home FileSystem root

Rejected as the default because `FileSystem(root_dir=~)` materially broadens recursive discovery and read exposure, while Harness protected patterns primarily protect writes rather than making sensitive files unreadable.

### Disable containment for absolute paths

Rejected because it discards the upstream canonical-path and symlink boundary that the integration is intentionally reusing.

### Separate capability names such as `read_external_file` / `write_tmp_file`

Rejected because path routing can enforce the authority distinction while preserving one FileSystem API surface.

## Consequences

- Relative paths continue to mean `cwd` and preserve the existing R/W contract.
- Explicit absolute/`~/` reads are accepted only inside configured trusted read roots.
- Explicit writes outside `cwd` are accepted only inside configured trusted write roots; currently that is `/tmp`.
- Each routed root uses its own Harness FileSystem, preserving canonical path and symlink containment.
- Unlisted external paths remain rejected.
- Read permission on a trusted reference root does not imply write permission.
- Shell remains an OS-level execution surface and is not constrained by this FileSystem routing policy.
- The curated root lists are policy and should grow only when a repeated use case justifies them.

## Related current-state docs

- `../code-mode.md` — current implementation and capability behavior.
- `../architecture.md` — overall GPT Dive × Pydantic integration.
- `../../../plans/code_mode/plan-260814-files-and-shell.md` — implementation/acceptance history.
