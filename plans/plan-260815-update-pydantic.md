# Pydantic Stack Update Automation

## Problem Statement

GPT Dive depends on fast-moving Pydantic AI Core and `pydantic-ai-harness`, while also carrying a local OpenAI Codex subscription compatibility layer. Updating these dependencies manually risks missing the current/runtime/reference/upstream version comparison, overlooking the Codex patch retirement gate, or improvising recovery when dependency or compatibility checks fail.

The local `~/ref` Pydantic checkouts are intentionally not part of routine updates because refreshing their GBrain embeddings has a real token cost. They remain reference snapshots and may lag runtime/upstream by design.

## Solution

Add a lightweight Web skill as the decision layer and a deterministic shell script as the execution layer.

The Web skill will:

1. Report the installed GPT Dive versions, the intentionally pinned `~/ref` versions, and the latest official upstream stable versions.
2. Treat `~/ref` lag as informational, never as a reason to fetch, checkout, re-index, or re-embed.
3. Review relevant upstream release changes and the local OpenAI Codex compatibility SSOT before choosing exact target versions.
4. Check whether the official released Pydantic AI now provides equivalent ChatGPT subscription-backed Codex auth/provider behavior. If equivalence is plausible or ambiguous, stop and resolve that question before changing dependencies.
5. Invoke the deterministic update script with exact Core and Harness versions only after the target is decided.
6. If the script or compatibility checks fail, stop rather than attempting fallback/rollback. Enter `/grill-me` with the user to resolve the failure, then improve the skill and/or script when the failure exposes a reusable maintenance lesson.

The shell script will accept exact Core and Harness versions, update only GPT Dive dependency declarations/lock state, run the agreed basic validation set, and return immediately on failure.

## User Stories

1. As the GPT Dive maintainer, I want to see runtime, reference, and upstream Pydantic versions together so that update decisions use explicit evidence.
2. As the GPT Dive maintainer, I want `~/ref` to remain untouched during routine updates so that GBrain embedding costs are not triggered accidentally.
3. As the GPT Dive maintainer, I want upstream release changes reviewed before dependency mutation so that compatibility risks are understood first.
4. As the GPT Dive maintainer, I want the OpenAI Codex compatibility layer checked on every Core update so that it can be retained safely or deliberately retired when upstream truly replaces it.
5. As the GPT Dive maintainer, I want the script to accept exact versions rather than discover latest versions itself so that decision logic stays in the Web skill.
6. As the GPT Dive maintainer, I want dependency update commands to preserve unrelated working-tree changes so that concurrent local work is not overwritten.
7. As the GPT Dive maintainer, I want focused compatibility tests, import smoke checks, Ruff, and Pyright to run automatically so that common regressions fail early.
8. As the GPT Dive maintainer, I want failures to stop immediately with raw evidence so that automation does not hide the real problem behind fallback behavior.
9. As the GPT Dive maintainer, I want reusable failure lessons fed back into the skill/script after `/grill-me` so that repeated maintenance becomes safer without making the script complicated.
10. As the GPT Dive maintainer, I do not want scheduled or unattended Pydantic upgrades so that dependency changes remain deliberate.

## Implementation Decisions

- The automation is GPT Dive-specific rather than a generic dependency updater.
- The Web skill is the "head": evidence gathering, release interpretation, Codex retirement decision, target selection, user-facing reporting, and failure escalation.
- The shell script is the "hand": exact version application and deterministic validation only.
- The shell script must not query latest versions, fetch `~/ref`, manipulate GBrain, choose alternative versions, roll back automatically, or perform recovery branches.
- Runtime dependency targets are official stable releases from the package registry/upstream tags.
- `~/ref/pydantic-ai` and `~/ref/pydantic-ai-harness` are display-only reference snapshots for this workflow.
- Reference lag is reported as `INFO`, not warning/failure.
- The local OpenAI Codex compatibility SSOT remains authoritative for the seams and retirement condition checked on each Core upgrade.
- Ambiguous or unexpected states stop the workflow and return control to Web SOL/user rather than triggering fallback behavior.
- A reusable failure discovered during `/grill-me` should lead to the smallest useful skill/script improvement after user agreement.
- No recurring scheduler or condition watch is part of this work.

## Testing Decisions

- Test the update script at the repository-maintenance seam rather than unit-testing shell implementation details.
- Basic validation after dependency resolution:
  - focused OpenAI Codex compatibility tests;
  - relevant Harness/CodeMode tests that exercise the local integration surface;
  - base Pydantic/GPT Dive import smoke including non-Codex lazy-import isolation where practical;
  - Ruff;
  - Pyright.
- Full pytest and live credential/model acceptance are not automatic script defaults. Web SOL may run them when release scope or failures justify the extra cost/risk.
- The script must use fail-fast shell behavior and preserve command output on failure.
- The implementation must be safe on a working tree containing unrelated changes; it must not reset, checkout, stash, or discard them.

## Out of Scope

- Updating or fetching `~/ref` Pydantic repositories.
- GBrain sync, migration, re-index, or embedding.
- Scheduled/automatic dependency upgrades.
- Automatic fallback to older/newer package versions.
- Automatic rollback.
- Automatic OpenAI Codex patch deletion or adaptation.
- Live credential refresh or live paid model calls as default script validation.
- General-purpose dependency management for non-Pydantic packages.

## Further Notes

Initial agreed target for the first run is Pydantic AI Core `2.31.0` and `pydantic-ai-harness` `0.21.0`, subject to one final live upstream-stable check immediately before application.

The current GPT Dive working tree already contains unrelated changes, including Playwright dependency removal. The updater must preserve those changes while modifying the Pydantic dependency lines and regenerating the lockfile.
