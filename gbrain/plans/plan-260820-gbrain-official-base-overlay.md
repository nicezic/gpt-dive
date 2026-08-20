# GBrain Official Base + GPT Dive Overlay

## Problem Statement

The current GBrain installation is a customized source checkout that mixes upstream code, local runtime changes, local maintenance docs, helper scripts, tests, and a long local commit stack in one repository. Upgrades therefore require rebasing local commits onto every new upstream stable release, and local schema migrations share GBrain's migration-number space. The recent v131 collision demonstrated that this ownership model can make an otherwise routine upstream upgrade require manual schema-version repair.

The desired state is to make upstream GBrain replaceable and inspectable as upstream, while GPT Dive owns every local customization and can reapply it deterministically after an official upgrade.

## Solution

Use the official Bun global GBrain package as the runtime base, maintain a separate clean upstream reference checkout for compatibility inspection, and move all user-owned GBrain customization into GPT Dive as an explicit integration/overlay.

Before changing the live runtime, update the clean reference to the target stable release and test the GPT Dive overlay against that target. If the overlay no longer applies cleanly, an upstream feature appears to supersede a local customization, or official and local policy conflict, stop and discuss the decision with the user rather than resolving it automatically.

Only after the reference preflight passes should the official Bun global package be refreshed and the same validated overlay applied to the live package. Official GBrain schema migrations remain exclusively owned by GBrain; GPT Dive-specific schema extensions use their own migration identity and ledger. Final acceptance verifies the runtime, quota guard, database health, and retrieval behavior before the upgrade is considered complete.

## User Stories

1. As the operator, I want GBrain to use the official Bun global distribution as its base so that normal upstream releases do not require maintaining a downstream source branch.
2. As the operator, I want a clean upstream reference checkout so that new releases can be inspected and tested without touching the live runtime.
3. As the operator, I want GPT Dive to own all local GBrain customization so that upstream and local responsibilities are obvious.
4. As the operator, I want local GBrain documentation to live next to the customization it describes so that reconstruction and maintenance instructions cannot be lost when the upstream package is replaced.
5. As the operator, I want historical GBrain plans kept with the GPT Dive GBrain integration so that past decisions remain available without polluting the upstream checkout.
6. As the operator, I want source-level local changes represented as deterministic overlays so that applicability can be checked before mutating the runtime.
7. As the operator, I want overlay compatibility tested against the clean target release first so that a broken upgrade is detected before replacing the working runtime.
8. As the operator, I want an overlay conflict to stop the upgrade and be discussed with me so that the system never invents a conflict resolution.
9. As the operator, I want upstream changes checked for equivalent functionality so that obsolete local customizations can be deliberately retired instead of being carried forever.
10. As the operator, I want official GBrain migrations to remain in GBrain's migration namespace so that future upstream migration numbers cannot collide with GPT Dive extensions.
11. As the operator, I want GPT Dive-specific schema changes tracked independently so that official GBrain schema version reporting remains truthful.
12. As the operator, I want the Voyage quota guard preserved across upgrades so that new corpus embedding remains fail-closed when quota cannot be verified.
13. As the operator, I want named Pydantic source-group behavior preserved across upgrades so that normal retrieval continues to search the intended Core/Harness/Monty corpus.
14. As the operator, I want eval provenance behavior preserved across upgrades so that captured evidence remains attributable to exact source revisions/chunks.
15. As the operator, I want Stable Index filtering and refresh behavior owned by GPT Dive so that index policy is independent of the GBrain distribution.
16. As the operator, I want automatic self-upgrade prevented from silently replacing an overlaid runtime so that local customization cannot disappear between maintenance runs.
17. As the operator, I want upgrade notifications and explicit update requests to enter one local upgrade workflow so that the same safety gates always apply.
18. As the operator, I want the official upgrade skill and the local reconstruction policy both consulted so that upstream guidance is retained while local constraints are enforced.
19. As the operator, I want any conflict between official guidance and local policy surfaced to me so that policy priority is never guessed.
20. As the operator, I want the previous customized checkout retired only after the new runtime passes acceptance so that migration to the new ownership model remains reversible until proven.
21. As the operator, I want final health and retrieval checks to use the real production brain so that success means the installed runtime actually works, not merely that a patch applied.
22. As the operator, I want upgrade completion recorded only after tests and acceptance pass so that documentation never claims a version is operational prematurely.

## Implementation Decisions

- Treat the upstream GBrain distribution and GPT Dive customization as separate ownership planes. Upstream owns the base package; GPT Dive owns local policy, overlay logic, local helpers, local tests, and local schema extensions.
- Keep a permanently clean upstream reference checkout. It is inspection and compatibility-test material, not the live runtime and not a place for local commits.
- Use the official Bun global GitHub install as the live base distribution. Reinstalling/upgrading the base is intentionally allowed to erase the previous overlay; the validated GPT Dive overlay is reapplied afterward.
- Model the effective runtime as “official base + GPT Dive overlay”, not as a pure official runtime.
- Store source modifications as functionally separated overlay units with deterministic ordering and an applicability preflight. Do not resolve failed hunks automatically.
- Keep helper programs that do not need to modify GBrain internals as GPT Dive-owned implementation rather than embedding them in the upstream package.
- Before a live upgrade, apply/check the overlay against an isolated copy of the target upstream reference and run the focused compatibility suite there.
- Detect whether upstream has absorbed a local feature during every upgrade. Retirement of a local customization is a deliberate user decision, not an automatic deletion.
- Keep official GBrain schema migration identity untouched. GPT Dive schema extensions use an independent version/ledger and must not advance or repair GBrain's official schema version.
- Preserve data/config independently from package replacement. The production brain remains outside the Bun global package and must not be recreated merely because the program package changes.
- Keep GBrain self-upgrade in notification mode rather than automatic mode while a local overlay exists. Actual upgrade mutation is owned by the local update workflow.
- Route explicit update requests and GBrain update-available signals through one local update workflow. That workflow reads both the current official GBrain upgrade skill and the GPT Dive reconstruction policy before acting.
- When official guidance and local policy conflict or are ambiguous, stop and discuss with the user.
- Retire the old customized source checkout only after the new base+overlay runtime has passed full production acceptance and required history/docs/helpers have been migrated.
- Keep current reconstruction instructions concise and current-state focused. Historical upgrade narratives belong in plan/history records rather than accumulating in the reconstruction procedure.

## Testing Decisions

- The primary pre-mutation seam is the clean target upstream reference plus an isolated overlay application. A good test proves that the target release accepts the overlay and that the externally required customized behavior still works; it should not merely assert patch file contents.
- The overlay applicability gate must fail before live mutation when source context has drifted, an expected upstream API disappeared, or a customization cannot be applied exactly.
- Focused behavior tests cover the local seams that matter: Voyage quota enforcement, source-group selection/override behavior, eval provenance, Stable Index refresh/filter behavior, and any GPT Dive-owned schema extension.
- Schema tests prove two independent invariants: official GBrain migrations can advance without seeing GPT Dive migration identifiers, and GPT Dive extensions can be applied/idempotently verified without changing the official schema version.
- Runtime acceptance runs against the actual Bun-global overlaid package and the existing production brain. At minimum it checks installed version/identity, type/runtime sanity, quota guard status, brain health, stale-index state, and representative retrieval across Core, Harness, Monty, and cross-source queries.
- Upgrade workflow tests include a simulated overlay conflict and verify that the workflow stops rather than attempting an automatic merge.
- Upgrade workflow tests include an update where an upstream feature plausibly supersedes a local patch and verify that the workflow reports the decision instead of silently retaining or dropping it.
- Existing local GBrain tests are prior art and should be migrated/reused where they test behavior rather than the old checkout layout.

## Out of Scope

- Executing the runtime cutover as part of writing this spec.
- Rebuilding or re-embedding the Pydantic corpus unless a separately approved change actually requires it.
- Changing the current production corpus composition or embedding provider.
- Automatically resolving overlay conflicts.
- Automatically retiring local functionality because upstream looks similar.
- Turning GBrain self-upgrade back to unattended auto mode while the runtime depends on a GPT Dive overlay.
- Refactoring unrelated GPT Dive AGY/Code Mode work currently dirty in the repository.

## Further Notes

Chosen durable layout:

- `~/ref/gbrain/` — clean upstream reference checkout.
- `~/gpt-dive/gbrain/` — GPT Dive-owned GBrain integration/customization root.
- `~/gpt-dive/gbrain/docs/` — reconstruction and Stable Index policy documentation.
- `~/gpt-dive/gbrain/plans/` — current and historical GBrain plans.
- `~/gpt-dive/gbrain/patches/` — source overlays that must modify the official GBrain package.
- `~/gpt-dive/gbrain/scripts/` — deterministic apply/preflight/verification helpers.
- `~/gpt-dive/gbrain/tests/` — integration-specific acceptance tests where project-level tests are not the better seam.
- `~/gpt-dive/gbrain/migrations/` — GPT Dive-owned schema-extension migrations/ledger logic when needed.
- Bun global GBrain package — live official base onto which the validated overlay is applied.
- `~/.gbrain/` — persistent GBrain configuration/data plane, independent from package replacement.

The three pre-existing GBrain plans are retained under the new GBrain plans directory as historical decision records.

## Result

Implemented and accepted on 2026-08-20.

- Runtime base is now the official Bun-global GBrain `0.46.24.0`; `~/.bun/bin/gbrain` resolves to `~/.bun/install/global/node_modules/gbrain/src/cli.ts` rather than the old source checkout.
- Clean upstream reference is `~/ref/gbrain` at `v0.46.24.0` / `7e3ce95bbf4c2e4902c8a35ff6a1f79bdbd54081`.
- GPT Dive owns the local integration under `~/gpt-dive/gbrain/`, including docs, plans, 8 ordered source overlays, helpers, tests, and the independent schema-extension runner.
- Clean-ref overlay acceptance passed `git apply --check`, `git diff --check`, TypeScript typecheck, and 109 focused Bun tests with 0 failures.
- Local schema extension `001-eval-candidate-chunk-hashes` now uses `~/.gbrain/gpt-dive/migrations.jsonl`; official GBrain schema remains `132`. Production's historical local `133` stamp was evidence-gated and normalized once to official `132` without changing data.
- Bun global install blocked its postinstall hook, so official migrations were run explicitly; `gbrain apply-migrations --yes` reports all migrations current and doctor reports schema `132 (latest: 132)`, 1,568 pages, and 100% embedding coverage.
- Voyage guard PASS (`reauthRequired=false`), stale embedding dry-run is 0, Stable Index self-test passed 19 include + 17 exclude fixtures, and both Voyage helper suites passed 8/8.
- Production retrieval canaries passed for Core, Harness, Monty, and cross-source `pydantic` group retrieval.
- Added `/update-gbrain` local wrapper routing official upgrade guidance through the local overlay/reconstruction policy; conflicts or plausible upstream replacement of local behavior return to the user.
- Old customized source checkout was restored to a clean `41de343f` snapshot and archived at `~/.local/state/gpt-dive/retired/gbrain-source-20260820` after runtime acceptance.

Implementation deviation from the initial sketch: the Bun-global package does not contain the development TypeScript toolchain required for reliable `tsc` validation, so typecheck/tests are owned by clean-reference preflight. Live application stages the installed package, applies the already-validated overlays, verifies runtime invariants, then atomically swaps the completed stage into place.
