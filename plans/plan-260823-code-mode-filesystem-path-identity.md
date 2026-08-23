## Problem Statement

Code Mode accepts relative, `~/...`, and absolute filesystem paths. GPT Dive resolves those inputs correctly to the actual host target, but the registered Harness filesystem adapter currently removes the leading `/` before dispatch.

```text
user input
~/xxx/xxx.md
      │
      ▼
GPT Dive path resolution
/home/nicezic/xxx/xxx.md        ✅ actual target
      │
      ▼
current Harness transport conversion
home/nicezic/xxx/xxx.md         ❌ target identity degraded
      │
      ▼
Harness error
File not found: home/nicezic/xxx/xxx.md
```

The filesystem lookup still targets the correct file because the Harness `FileSystem` is rooted at `/`. The defect is diagnostic identity: a GPT Dive internal transport representation leaks into the error and makes the path look corrupted.

This is a GPT Dive integration defect, not a Pydantic AI Harness bug. Harness reports the path GPT Dive supplies.

## Solution

Resolve the caller path once against the effective Code Mode cwd and carry that canonical absolute host target directly into the root-`/` Harness filesystem capability.

```text
raw path
├─ relative
├─ ~/...
└─ /absolute/...
      │
      ▼
expand user + cwd resolution
      │
      ▼
canonical resolved target
/home/nicezic/xxx/xxx.md
      │
      ├─ policy / search guard
      └─ Harness FileSystem(root="/")
              │
              ├─ filesystem operation
              └─ diagnostic
                  File not found: /home/nicezic/xxx/xxx.md ✅
```

The canonical resolved target is the authoritative path identity after the Code Mode input boundary. GPT Dive must not manufacture a second root-relative transport representation merely to call a Harness filesystem already rooted at `/`.

No diagnostic parser, result rewriter, path wrapper class, or upstream Harness change is needed.

## User Stories

1. As Web SOL, I want a failed filesystem capability to identify the actual resolved host target, so that I can distinguish a bad path from adapter corruption.
2. As Web SOL, I want relative paths to continue resolving from the effective Code Mode cwd.
3. As Web SOL, I want `~/...` paths to continue resolving through the user home directory.
4. As Web SOL, I want absolute paths to continue targeting the same host location.
5. As Web SOL, I want existing host-wide access, secret exclusions, and broad-search guards to remain unchanged.
6. As a maintainer, I want one resolved target representation after path resolution, so that internal transport details cannot leak into diagnostics.
7. As a maintainer, I want regression coverage at the public `code_mode()` seam rather than private helper tests.

## Implementation Decisions

- GPT Dive owns caller-path resolution for registered Code Mode filesystem capabilities.
- After resolution, the canonical absolute host target is passed directly to the Harness `FileSystem` rooted at `/`.
- Remove the root-relative conversion that strips the leading `/`; it no longer carries useful information under the current single root-`/` filesystem design.
- Prefer one simple filesystem dispatch path. Do not introduce a new path type, display-path layer, exception parser, compatibility wrapper, or other abstraction.
- Preserve existing capability names, signatures, return types, cwd semantics, host-wide filesystem policy, credential/secret deny policy, stale-write behavior, OS permission behavior, and broad recursive-search guards.
- Do not modify Pydantic AI Harness for this issue. Its current behavior is sufficient when GPT Dive supplies the correct target identity.
- Harness walker result formatting is not part of this defect and is not redesigned here.

## Testing Decisions

- Test the bug at the highest existing seam: public `code_mode()` invoking a registered filesystem capability.
- Add one focused regression case for a missing path whose input requires Code Mode resolution, and assert that the raised diagnostic contains the canonical resolved absolute target including its leading `/`.
- The regression should prove the externally meaningful failure behavior, not helper structure or the presence/absence of a particular `Path` operation.
- Existing tests remain the breadth coverage for successful read/write operations, cwd-relative behavior, host-wide access, credential/secret blocking, broad-search guards, and the complete filesystem capability surface.
- Do not add a per-capability or per-path-form matrix for this change.
- Run the focused Code Mode runtime tests first, then the normal project test suite once after implementation.

## Out of Scope

- Changing `search_files`, `find_files`, or `list_directory` result-path formatting.
- Guaranteeing that walker output can be fed back as a capability input.
- Preserving the caller's exact lexical spelling such as `~/x` in diagnostics; the chosen diagnostic identity is the resolved target.
- Changing filesystem permissions or security policy.
- Changing Pydantic AI Harness implementation or error-formatting policy.
- Adding new filesystem abstractions, fallback paths, or compatibility layers.
- Exhaustive path-format or per-capability regression tests.

## Further Notes

The accepted Code Mode host-filesystem ADR remains authoritative: registered Harness filesystem capabilities and Monty direct filesystem primitives operate across the host filesystem subject to explicit credential/secret exclusions and normal OS permissions.

Git history shows the root-relative conversion came from an earlier adapter shape that selected among different filesystem roots. Code Mode now uses a host-wide Harness root of `/`, so stripping the leading slash is legacy transport work that degrades diagnostic identity without changing the actual target.
