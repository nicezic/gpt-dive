# 01 — Add the local Codex compatibility layer

**Blocked by:** None — can start immediately

**Status:** completed

## What to build

Add an optional GPT Dive-owned compatibility layer for subscription-backed OpenAI Codex execution while leaving the current PR-pinned Pydantic AI dependency in place.

The compatibility layer should preserve the behavior GPT Dive currently receives from Pydantic AI PR #6433, but it should be implemented against the current official Pydantic AI extension seams wherever possible rather than copying the PR mechanically.

The patch code belongs inside `~/gpt-dive`. Its exact module shape should follow the current repository architecture discovered at implementation time.

## Required documentation

Create documentation next to the compatibility code:

- `README.md` describing the local Codex architecture, purpose, boundaries, and optional-degradation behavior.
- `README.patch.openai.provider.md` as the maintenance SSOT.

The patch maintenance document must include:

- PR #6433 and reference commit `af055625bf67217a5839d6255900475d9576aa13`
- why #6433 is a behavioral reference rather than a frozen implementation template
- current official Pydantic AI base/version
- relevant Pydantic AI provider/model/profile/transport seams
- GPT Dive architecture assumptions, especially ordinary `Agent.run()`
- explicit non-goals and behavior that can be omitted from #6433 when GPT Dive does not need it
- upgrade checklist and compatibility history

## Acceptance criteria

- [x] Local Codex compatibility code exists entirely inside the GPT Dive repository.
- [x] Official Pydantic AI source files are not modified in-place.
- [x] Implementation prefers public extension points, then subclass/wrapper, then narrow adapter; any deeper/private coupling is explicitly documented.
- [x] Required OAuth/provider/transport semantics from #6433 are covered by focused tests.
- [x] Ordinary `Agent.run()` compatibility is represented in the tests or in an isolated acceptance harness.
- [x] `README.md` and `README.patch.openai.provider.md` explain enough for a fresh AI session to maintain the patch during a future Pydantic AI upgrade.
- [x] Existing GPT Dive production routing remains unchanged in this ticket, so rollback is trivial.

## Result

Completed via `src/gpt_dive/openai_codex/`. Security-sensitive auth/OAuth/store behavior was adapted from PR #6433 while provider/model integration was reduced to official Pydantic extension seams plus a narrow `OpenAIResponsesModel` subclass. Focused compatibility tests PASS.
