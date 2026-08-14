# 02 — Route GPT Dive Codex execution through the local layer

**Blocked by:** 01 — Add the local Codex compatibility layer

**Status:** completed

## What to build

Change GPT Dive's subscription-backed OpenAI Codex execution path so SOL/TERRA/LUNA use the new local compatibility layer instead of relying on PR #6433's provider implementation being supplied by the installed Pydantic AI fork.

Keep the current PR-pinned dependency during this migration ticket. The purpose is to prove GPT Dive's runtime wiring independently before changing the underlying dependency source.

Non-Codex providers must continue to use ordinary Pydantic AI paths and must not import or initialize the local Codex compatibility layer unnecessarily.

## Acceptance criteria

- [x] SOL/TERRA/LUNA resolve through the local Codex compatibility implementation.
- [x] `bare(sol)` succeeds through the local path.
- [x] `subagent_call(sol)` succeeds through the local path.
- [x] Ordinary `Agent.run()` succeeds for subscription-backed Codex execution.
- [x] At least one tool-call round trip succeeds through the local path.
- [x] Authentication/credential refresh behavior needed by GPT Dive is verified.
- [x] Anthropic and ordinary OpenAI API-key paths remain independent of the local Codex layer.
- [x] Failure when the Codex-specific layer is unavailable is scoped to subscription-backed Codex aliases and produces a clear error rather than breaking base Pydantic AI imports.
- [x] Relevant focused tests, typechecking, and linting pass.
- [x] Patch documentation is updated if implementation reveals additional Pydantic AI seams or GPT Dive invariants.

## Result

Routing was switched while PR #6433 remained installed. Before dependency cut-over, live `Agent.run()`, tool-call, `bare(sol)`, and `subagent_call(sol)` all passed through `gpt_dive.openai_codex`; non-Codex registry use was verified not to import the local layer.
