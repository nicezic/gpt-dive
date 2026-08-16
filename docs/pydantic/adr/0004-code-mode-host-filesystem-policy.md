---
title: ADR — Code Mode Host Filesystem Policy
created: 2026-08-14
updated: 2026-08-16
type: decision
status: accepted
---

# ADR — Code Mode Host Filesystem Policy

## Decision

Code Mode uses a broad local filesystem boundary with explicit secret exclusions:

```text
READ  -> host filesystem `/`, except credential/secret paths
WRITE -> host filesystem `/`, except credential/secret paths and normal OS permission failures
```

Relative paths continue to resolve from the effective `cwd`.

The same policy applies to both registered Harness FileSystem capabilities and Monty direct filesystem primitives such as `Path.read_text()` / `Path.write_text()`. GPT Dive owns a small host-backed Monty OS adapter so direct Python filesystem calls cannot bypass the FileSystem policy.

Credential/secret paths are denied explicitly, including common `.env`, private key, SSH/GPG/keyring, cloud credential, and similar local secret stores. Harness default `.git` write protection is disabled for Code Mode because Git metadata is a normal development target; the explicit secret deny list and the local OS identity/permissions are the deterministic boundaries.

## Why

The earlier curated-root model allowed reads only from a small list of project/reference trees and allowed external FileSystem writes only under `/tmp`. In normal local engineering work that repeatedly blocked legitimate cross-project reads and Wiki/repository edits, forcing unnecessary fallback paths and extra tool calls.

GPT Dive runs on the user's own WSL2 machine. The useful deterministic boundaries are therefore:

- prevent model-visible reads and writes of credential/secret material;
- let ordinary local engineering use writable host paths such as `/tmp` without artificial root exceptions;
- keep stale-write conflict detection;
- keep explicit toolchain guards for known bad execution paths such as old Python versions and direct pip/npm usage.

These guards target concrete failure modes instead of treating ordinary local files as untrusted by default.

## Consequences

- `/tmp`, `/etc`, `/usr`, and other host paths may be read or written when OS permissions allow and the path is not secret-blocked.
- Registered FileSystem capabilities and Monty direct filesystem primitives use the same host-wide write boundary.
- Reads and writes of blocked credential/secret paths fail regardless of location.
- Ordinary writable repository, Wiki, `.git`, cache, and temporary files are writable wherever the OS permits.
- `write_file` / `edit_file` retain `expected_hash` optimistic concurrency checks.
- Shell remains an OS-level execution surface governed separately by PATH guards, environment stripping, and the user's local OS permissions.

## Rejected alternatives

### Curated trusted read roots

Rejected because they caused repeated false-positive denials during ordinary cross-project work and required policy maintenance whenever a new local tree became relevant.

### Home-only writes

Rejected because they create false denials for legitimate local engineering paths such as `/tmp`, require special-case write roots, and do not meaningfully match the broader OS-level reach already available to Code Mode Shell.

### Secret reads allowed everywhere

Rejected because credential leakage is a concrete high-impact failure mode. Secret paths remain explicitly denied even though general host reads are broad.

## Related current-state docs

- `../code-mode.md` — current implementation and capability behavior.
- `../architecture.md` — overall GPT Dive × Pydantic integration.
- `../../../plans/code_mode/plan-260814-files-and-shell.md` — earlier implementation/acceptance history.
