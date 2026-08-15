---
title: ADR — Code Mode Host Filesystem Policy
created: 2026-08-14
updated: 2026-08-16
type: decision
status: accepted
---

# ADR — Code Mode Host Filesystem Policy

## Decision

Code Mode uses a broad local read boundary and a narrow mutation boundary:

```text
READ  -> host filesystem `/`, except credential/secret paths
WRITE -> user home `~/`, except credential/secret paths
```

Relative paths continue to resolve from the effective `cwd`.

The same policy applies to both registered Harness FileSystem capabilities and Monty direct filesystem primitives such as `Path.read_text()` / `Path.write_text()`. GPT Dive owns a small host-backed Monty OS adapter so direct Python filesystem calls cannot bypass the FileSystem policy.

Credential/secret paths are denied explicitly, including common `.env`, private key, SSH/GPG/keyring, cloud credential, and similar local secret stores. Harness default `.git` write protection is disabled for Code Mode because Git metadata under `~/` is a normal development target; the explicit secret deny list and home-only write boundary are the deterministic guards.

## Why

The earlier curated-root model allowed reads only from a small list of project/reference trees and allowed external FileSystem writes only under `/tmp`. In normal local engineering work that repeatedly blocked legitimate cross-project reads and Wiki/repository edits, forcing unnecessary fallback paths and extra tool calls.

GPT Dive runs on the user's own WSL2 machine. The useful deterministic boundaries are therefore:

- prevent model-visible reads of credential/secret material;
- prevent filesystem mutation outside the user's home tree;
- keep stale-write conflict detection;
- keep explicit toolchain guards for known bad execution paths such as old Python versions and direct pip/npm usage.

These guards target concrete failure modes instead of treating ordinary local files as untrusted by default.

## Consequences

- `/tmp`, `/etc`, `/usr`, and other host paths may be read when OS permissions allow and the path is not secret-blocked.
- FileSystem and Monty direct writes outside `~/` fail.
- Reads and writes of blocked credential/secret paths fail even inside `~/`.
- `.git` and ordinary repository/Wiki files under `~/` are writable.
- `write_file` / `edit_file` retain `expected_hash` optimistic concurrency checks.
- Shell remains an OS-level execution surface governed separately by PATH guards, environment stripping, and the user's local OS permissions.

## Rejected alternatives

### Curated trusted read roots

Rejected because they caused repeated false-positive denials during ordinary cross-project work and required policy maintenance whenever a new local tree became relevant.

### Whole-host writes

Rejected because normal project work has no need to mutate system paths. `~/` is the useful mutation boundary.

### Secret reads allowed everywhere

Rejected because credential leakage is a concrete high-impact failure mode. Secret paths remain explicitly denied even though general host reads are broad.

## Related current-state docs

- `../code-mode.md` — current implementation and capability behavior.
- `../architecture.md` — overall GPT Dive × Pydantic integration.
- `../../../plans/code_mode/plan-260814-files-and-shell.md` — earlier implementation/acceptance history.
