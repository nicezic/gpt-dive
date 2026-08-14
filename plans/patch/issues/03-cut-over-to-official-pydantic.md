# 03 — Cut over to official Pydantic AI stable

**Blocked by:** 02 — Route GPT Dive Codex execution through the local layer

**Status:** completed

## What to build

Replace GPT Dive's PR #6433 Git dependency pin with the latest official stable `pydantic-ai-slim` compatible with Python 3.14, then adapt only the local Codex compatibility layer as necessary.

This ticket is the contract phase: once the local path is proven, remove the stale fork dependency and verify that GPT Dive remains fully functional on official Pydantic AI.

Do not introduce a new downstream Pydantic AI fork merely to resolve compatibility differences. If official upstream changes require adaptation, keep those changes local to the GPT Dive compatibility layer and document the affected seams.

## Acceptance criteria

- [x] `pyproject.toml` no longer points `pydantic-ai-slim` at PR #6433 / `af055625...`.
- [x] The lockfile resolves official stable Pydantic AI compatible with Python 3.14.
- [x] Base Pydantic AI imports work without loading the local Codex patch.
- [x] Anthropic and ordinary OpenAI API-key provider paths pass their existing tests.
- [x] SOL/TERRA/LUNA subscription-backed Codex aliases pass through the local compatibility layer.
- [x] `bare(sol)` PASS.
- [x] `subagent_call(sol)` PASS.
- [x] Ordinary Codex `Agent.run()` PASS.
- [x] Codex tool-call round trip PASS.
- [x] OAuth refresh / credential handling needed by GPT Dive PASS.
- [x] Relevant focused tests, ruff, pyright, and the full GPT Dive pytest suite PASS.
- [x] `README.patch.openai.provider.md` records the final official Pydantic version, actual compatibility seams, deviations from #6433, and the upgrade procedure for the next version bump.
- [x] The documentation states the retirement condition: delete the local compatibility layer when upstream provides equivalent official Codex subscription support and the acceptance suite passes without it.

## Result

Cut over to official `pydantic-ai-slim==2.30.0`; the installed official package has no `pydantic_ai.providers.openai_codex` module, proving runtime success does not hide a fork dependency. Live OAuth refresh rotated the credential revision and a subsequent Codex request returned 200. Final gates: `83 passed`, Ruff PASS, Pyright `0 errors`, `git diff --check` PASS.
