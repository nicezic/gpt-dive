---
title: ADR — Keep Pydantic Upstream Clones under ~/ref
created: 2026-08-10
updated: 2026-08-10
type: decision
status: accepted
---

# ADR — Keep Pydantic Upstream Clones under `~/ref`

## Decision

Keep upstream Pydantic AI/Harness source and docs clones under `~/ref` rather than moving them to top-level `~/pydantic*` project directories.

## Reason

Their primary role is source/docs/API reference, compatibility inspection, and temporary custom snapshot support. Actual Python imports are owned by each project's `uv`/venv dependency configuration, so making the clones top-level workspaces would add naming/ownership ambiguity without runtime benefit.

## Current / future

- Core authority: `~/ref/pydantic-ai/`.
- Harness: `~/ref/pydantic-ai-harness/`.
- `~/ref/pydantic-ai-pr-6433/` is historical provenance for the former local Codex compatibility layer; GPT Dive retired that layer after official support shipped in Pydantic AI 2.42.0.

Official docs are read from these clones directly; Wiki does not maintain a duplicate official-doc tree.
