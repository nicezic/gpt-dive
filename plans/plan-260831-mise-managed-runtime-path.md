# Mise-Managed Runtime PATH

## Problem Statement

GPT Dive now has a user-owned canonical Toolchain policy centered on `mise`: Node.js 24 LTS, Python 3.14, `pnpm`, and `uv` / `uvx` belong under one dev-tool manager so versions, activation, PATH, and task execution are consistent across sessions and projects.

The runtime implementation does not currently honor that policy. The shared PATH builder used by GPT Dive execution surfaces still hard-codes legacy user-bin locations for `pnpm` and Bun, while the normal Code Mode `run_command()` surface runs with a sanitized PATH that does not include mise shims. As a result, direct WSL execution can resolve the mise-selected Node.js runtime while `run_command()` cannot resolve `node` unless the caller explicitly wraps the command in `mise exec -- ...`.

This is more than a convenience issue. `run_command()` is the normal foreground shell primitive for Web SOL, so requiring the model to remember a wrapper for every tool invocation moves environment correctness out of the runtime and into prompt adherence. That recreates the exact instruction-fade and default-behavior risk the GPT Dive harness is designed to reduce.

The mismatch is also broader than `run_command()`. Repository exploration with Probe located one shared PATH policy, and CodeGraph found that the shared builder has fourteen callers spanning command execution, execution workers, repository search, model/subagent runtimes, and related surfaces. A local workaround in `run_command()` would therefore leave sibling execution surfaces with a different toolchain view and create another source of drift.

The previous command-surface simplification decision explicitly preserved GPT Dive's guard-bin PATH behavior. The desired change must therefore retain guard-bin precedence and all existing sanitization/security semantics while replacing ecosystem-specific PATH assumptions with the canonical mise-managed toolchain layer.

### Why this matters

```text
USER_RULES canonical toolchain
          │
          ▼
         mise
   ┌──────┼──────┬──────┐
 Node   Python   pnpm   uv/uvx
          │
          │ should be the same environment contract
          ▼
GPT Dive execution surfaces
          │
          ├─ run_command
          ├─ execution workers
          └─ model/subagent runtimes
```

If the canonical policy says mise owns the toolchain but the runtime still injects legacy `pnpm`/Bun paths, documentation and implementation disagree. The runtime should make the correct environment the default so the model can issue the natural command (`node`, `pnpm`, `uv`, and so on) instead of carrying environment-repair syntax in every call.

## Solution

Make mise the canonical dev-tool activation layer for GPT Dive execution surfaces while preserving guard-bin as the highest-precedence command-policy layer.

The shared runtime PATH policy will resolve in this conceptual order:

```text
GPT Dive runtime PATH
├─ guard-bin                 # GPT Dive policy remains first
├─ mise shims                # canonical managed toolchain
├─ stable user utility bins  # non-toolchain utilities still allowed
└─ inherited/system PATH
```

Before relying on that runtime behavior, canonicalize the operator-owned mise configuration so the declared Toolchain is actually available through mise: Node.js 24 LTS, Python 3.14, `pnpm`, and `uv` / `uvx`. Migration order matters because the current machine only has Node.js registered in mise; the existing `pnpm` and Python/uv installations are currently external to mise.

Once the canonical tools are managed by mise, remove legacy JavaScript-package-manager assumptions from the shared runtime PATH policy rather than retaining parallel `pnpm`/Bun compatibility paths. Keep unrelated stable utility paths only where they remain independently required.

The normal `run_command()` experience should then be direct:

```text
Web SOL
  ↓
run_command("pnpm ...")
  ↓
guard-bin
  ↓
mise shim
  ↓
mise-selected Node.js / pnpm
```

Explicit `mise exec -- ...` remains useful for deliberate version overrides or shells that intentionally do not expose mise, but it must not be required to repair GPT Dive's normal runtime environment.

## User Stories

1. As Web SOL, I want `run_command()` to see the canonical mise-managed toolchain automatically, so that normal development commands do not require environment-repair wrappers.
2. As Web SOL, I want `node` invoked through GPT Dive to resolve the same mise-selected version as the user's normal WSL environment, so that behavior does not change depending on execution surface.
3. As Web SOL, I want `pnpm` to run against the mise-selected Node.js runtime, so that JavaScript package operations are reproducible and do not depend on a separately injected legacy PATH.
4. As Web SOL, I want Python 3.14 and `uv` / `uvx` to participate in the same canonical toolchain policy, so that Python tooling follows the same environment ownership model as Node.js tooling.
5. As Web SOL, I want to issue natural commands such as `node`, `pnpm`, and `uv`, so that tool usage depends on runtime configuration rather than remembered prompt instructions.
6. As Web SOL, I want `mise exec -- ...` to be optional for explicit overrides rather than mandatory for ordinary non-interactive execution, so that the default shell contract stays simple.
7. As a maintainer, I want one shared PATH policy to represent the canonical toolchain, so that command execution, workers, repository search, and model runtimes cannot drift independently.
8. As a maintainer, I want guard-bin to remain the first PATH entry, so that adopting mise does not bypass GPT Dive's command-policy wrappers.
9. As a maintainer, I want provider-secret environment filtering to remain unchanged, so that toolchain alignment does not weaken credential boundaries.
10. As a maintainer, I want timeout, output-spooling, process cleanup, and cwd behavior to remain unchanged, so that a PATH migration does not become a command-runtime redesign.
11. As a maintainer, I want legacy package-manager-specific PATH entries removed once mise owns those tools, so that the implementation reflects one canonical source of tool versions.
12. As a maintainer, I want the migration to verify current mise ownership before legacy paths are removed, so that the transition cannot make currently working commands disappear.
13. As a maintainer, I want the shared PATH builder to remain deduplicated and deterministic, so that inherited shell state cannot reorder or duplicate canonical entries.
14. As a maintainer, I want focused regression tests around the public command behavior and shared PATH policy, so that future runtime refactors cannot silently drop mise activation.
15. As a maintainer, I want CodeGraph blast-radius evidence considered during implementation, so that all callers of the shared PATH policy are verified rather than treating the change as `run_command()`-only.
16. As a maintainer, I want Probe to remain the fast location/evidence tool and CodeGraph to remain the caller/impact tool, so that future runtime changes use the appropriate search lane instead of broad manual inspection.
17. As a user, I want USER_RULES and GPT Dive runtime behavior to express the same Toolchain ownership, so that documentation is an accurate operational contract rather than a workaround guide.
18. As a user, I want project-local mise configuration to take precedence over global defaults where present, so that repository-specific tool versions remain reproducible.
19. As a user, I want live mise/project state checked before installation or migration, so that fixed documentation does not overwrite a more specific project toolchain decision.
20. As a maintainer, I want this plan to be the local SSOT for the migration, so that implementation does not split into ad-hoc shell fixes and unrelated tool installation changes.

## Implementation Decisions

- Treat mise as the canonical dev-tool manager for the declared Toolchain: Node.js 24 LTS, Python 3.14, `pnpm`, and `uv` / `uvx`.
- Migrate operator-owned mise configuration before removing legacy PATH support. The migration is complete only when live mise state can resolve each canonical tool that GPT Dive expects to expose.
- Keep project-local mise configuration authoritative over global defaults. The runtime must consume mise's resolution semantics rather than encode project versions itself.
- Keep the shared runtime PATH builder as the single owner of PATH composition for GPT Dive execution surfaces. Do not add a `run_command()`-only PATH patch.
- Preserve guard-bin as the first PATH entry. Mise shims belong immediately after policy prefixes and before ordinary user/system PATH entries.
- Remove direct `pnpm` and Bun toolchain paths from the canonical shared PATH once mise owns the required JavaScript tools. Do not retain parallel compatibility paths solely as fallback.
- Preserve independently useful non-toolchain user paths only when they serve tools not intentionally migrated under mise; do not broaden this change into a complete home-directory PATH redesign.
- Preserve environment sanitization, provider-secret filtering, execution deadlines, output bounds, process-group cleanup, cwd behavior, and command result contracts unchanged.
- Keep this as a GPT Dive integration policy. Do not modify Pydantic AI Harness upstream defaults or require upstream consumers to adopt mise.
- Update user-facing runtime/toolchain documentation after the runtime contract changes so it describes the default behavior rather than requiring `mise exec -- ...` as a routine repair step.
- Explicit `mise exec` remains valid for deliberate version overrides, ad-hoc tool selection, or execution contexts that intentionally bypass the normal GPT Dive PATH contract.
- Use live project configuration and `mise` state for installation decisions; do not encode volatile patch versions in runtime code.

## Testing Decisions

Keep regression coverage deliberately small:

- One shared PATH test proves `guard-bin` stays first, mise shims come next, and legacy direct `pnpm` / Bun toolchain paths are no longer injected.
- One `run_command()` regression test uses a tiny controlled fake shim/tool and proves an ordinary command resolves through the mise layer without `mise exec -- ...`.
- Run only the directly affected existing test files plus these regressions. Do not add caller-by-caller coverage or require a broad-suite pass for this PATH hotfix.
- After automated checks pass, do one live smoke check that ordinary Code Mode commands resolve the expected mise-managed tools.

## Out of Scope

- Replacing mise with another tool manager.
- Redesigning the GPT Dive command API or adding new command parameters.
- Changing guard-bin command policy or bypassing guard wrappers through mise.
- Changing provider credential filtering or secret-handling rules.
- Changing process lifetime, timeout, cancellation, output-spooling, or Task lifecycle semantics.
- Refactoring unrelated PATH entries merely for aesthetic consistency.
- Maintaining Bun or direct package-manager PATH entries as speculative fallbacks after the canonical toolchain migration.
- Pinning every tool to a volatile patch version in GPT Dive source code.
- Modifying Pydantic AI Harness's general execution environment for other consumers.
- Turning this migration into a general dotfile or shell-startup redesign.

## Further Notes

### Why the runtime should own this instead of USER_RULES

A model-facing rule such as "use `mise exec -- ...` in non-interactive shells" can compensate for a missing PATH entry, but it is the wrong long-term ownership boundary for GPT Dive's primary shell. The model is expected to forget or generalize instructions over long sessions; the runtime is expected to provide deterministic execution semantics. If `run_command()` is the canonical shell, its environment must make the canonical toolchain available without requiring prompt-level ceremony.

This is the same architectural principle used elsewhere in GPT Dive: model instructions communicate intent, while the harness enforces stable mechanics. Guard-bin precedence, secret filtering, deadlines, and output limits are not left to the model to reconstruct per invocation. Toolchain activation should follow the same pattern.

### Probe and CodeGraph evidence

Probe was the correct first lane because the initial question was "where is PATH constructed and what current tests/decisions mention it?" It located the shared runtime environment builder, the direct command boundary, the existing PATH test, runtime documentation, and the earlier command-surface plan without requiring an index traversal.

CodeGraph was the correct second lane because the decision then became "what breaks or changes if the shared builder changes?" Its impact analysis identified thirty-eight affected symbols and fourteen callers across command execution, execution workers, repository search, model/subagent execution, and tests. That evidence is why this plan changes the shared policy rather than adding a local `run_command()` workaround.

### Migration ordering

Current live state matters: Node.js is already registered under mise, while `pnpm` and Python/uv currently resolve from external installation locations. The implementation must therefore canonicalize mise ownership first, validate it, and only then remove legacy direct toolchain paths from GPT Dive. This is a migration dependency, not a reason to preserve permanent fallbacks.

### Prior decision compatibility

The earlier command-surface simplification plan requires GPT Dive to preserve guard-bin PATH behavior and keep the `run_command()` integration local rather than altering Harness defaults. This plan extends that decision: guard-bin remains first, while mise becomes the dev-tool source immediately behind it. The two decisions are complementary rather than conflicting.
