# OpenAI Codex Provider Compatibility Patch

**Date:** 2026-08-14
**Status:** completed

## Goal

Move GPT Dive off the stale Pydantic AI PR #6433 dependency pin while preserving subscription-backed OpenAI Codex execution.

GPT Dive should become a normal consumer of the latest official stable `pydantic-ai-slim`. Codex subscription-specific behavior lives as an optional local compatibility layer inside `~/gpt-dive`.

## Why

The current dependency points at PR #6433 (`feat/codex-subscription-auth`, reference commit `af055625bf67217a5839d6255900475d9576aa13`), whose effective base is around Pydantic AI v2.25 while upstream stable has advanced to v2.30.0.

The patch is needed only for subscription-backed OpenAI Codex execution. Ordinary Pydantic AI use must remain independent of this compatibility layer.

## Architecture Decision

Use **local runtime compatibility**, not a downstream Pydantic AI fork.

```text
GPT Dive
   |
   +-- official pydantic-ai-slim stable
   |
   +-- gpt_dive Codex compatibility layer
          |
          +-- auth / credential refresh
          +-- OpenAI Codex provider adaptation
          +-- Codex transport / SSE compatibility
          +-- ordinary Agent.run() compatibility
```

Preferred implementation order:

1. public Pydantic AI extension APIs
2. subclass / wrapper
3. narrow compatibility adapter
4. monkey patch only as a last resort

The official Pydantic package itself must not be modified in-place.

## Required Documentation

The implementation must carry documentation next to the patch code:

- `README.md` — architecture, purpose, invariants, optional-degradation behavior
- `README.patch.openai.provider.md` — maintenance SSOT for the Pydantic AI/OpenAI provider compatibility patch

`README.patch.openai.provider.md` must record:

- PR #6433 as the behavioral/reference source, not as code that must be preserved verbatim
- reference commit `af055625bf67217a5839d6255900475d9576aa13`
- current official Pydantic AI base/version
- GPT Dive assumptions and execution model
- exact upstream seams/classes/functions the compatibility layer depends on
- differences from #6433
- upgrade procedure for future Pydantic AI versions
- compatibility history
- PASS gates

## Invariants

- `from pydantic_ai import Agent` and ordinary official Pydantic AI functionality work without the Codex compatibility layer.
- Anthropic and ordinary OpenAI API-key providers do not depend on the local Codex patch.
- SOL/TERRA/LUNA subscription-backed Codex aliases may depend on the patch.
- Ordinary `Agent.run()` remains supported for Codex subscription execution; users must not be forced to switch to `run_stream()` solely because of the compatibility layer.
- Python 3.14 remains supported.
- When upstream ships equivalent official Codex subscription support, the local compatibility layer can be deleted cleanly.

## Reference Facts

- Upstream stable observed: Pydantic AI v2.30.0, commit `c24a9008a`.
- PR #6433 reference HEAD: `af055625bf67217a5839d6255900475d9576aa13`.
- A non-mutating trial port onto v2.30.0 found conflicts in docs/lock plus runtime-relevant areas around `models/openai.py`, `profiles/openai.py`, and `pydantic_ai_slim/pyproject.toml`.
- YA OAuth/provider was rejected as the primary route because its current package set excludes Python 3.14 and its Codex provider does not support ordinary `Agent.run()`.

## Tickets

1. `issues/01-local-codex-compat-layer.md`
2. `issues/02-route-gpt-dive-through-local-codex.md`
3. `issues/03-cut-over-to-official-pydantic.md`

The sequence is expand -> migrate -> contract. Do not remove the current PR pin until the local compatibility path is proven in GPT Dive.

## Completion — 2026-08-14

- Local compatibility layer added under `src/gpt_dive/openai_codex/`.
- SOL/TERRA/LUNA routing moved to the local layer while the PR pin was still installed and live-accepted.
- Dependency then cut over to official `pydantic-ai-slim==2.30.0` / `pydantic-graph==2.30.0`; PR #6433 Git source pin removed.
- Live PASS: ordinary `Agent.run()`, one tool-call round trip, `bare(sol)`, `subagent_call(sol)`, OAuth refresh, and post-refresh Codex request.
- Final regression: `83 passed`; Ruff PASS; Pyright `0 errors`; `git diff --check` PASS.
- Maintenance/retirement SSOT: `README.patch.openai.provider.md`.
