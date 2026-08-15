# GPT Dive × Pydantic AI

This directory is the development SSOT for how GPT Dive uses, extends, and constrains Pydantic AI / Pydantic AI Harness.

It owns **repository implementation knowledge**, not Web SOL operating policy and not generic Pydantic learning material.

## Scope

Keep here:

- Pydantic/Harness integration architecture inside GPT Dive.
- Code Mode implementation and capability-registry behavior.
- Local provider/model integration and compatibility layers.
- GPT Dive-specific ADRs and upstream-delta rationale.
- Upgrade/retirement seams that must evolve with this repository.

Keep elsewhere:

- Web SOL operating rules: `~/wiki/workflow/pydantic-ai/`.
- Cross-component AI Orchestra policy: `~/wiki/workflow/orchestra/`.
- Verified reusable Pydantic concepts: `~/wiki/pydantic/handbook/`.
- Ongoing Pydantic study/incubation: `~/wiki/pydantic/study/`.
- One-change implementation history and acceptance: `plans/`.

## Documents

- `architecture.md` — Pydantic adoption → current GPT Dive integration, including major customizations and their Why.
- `code-mode.md` — Code Mode registry, FileSystem/Shell wiring, workspace boundaries, lifecycle, and model-facing contract.
- `tool-output-limits.md` — SubAgent ToolOutputLimits policy and the distinct Code Mode final-output spill seam.
- `providers.md` — provider/model alias integration roles and repository ownership boundaries.
- Root `README.patch.openai.provider.md` — intentionally prominent maintenance SSOT for the local ChatGPT Codex subscription compatibility layer; keep it at repository root so Pydantic upgrades encounter it early.
- `adr/README.md` — ADR admission rule and scope boundary.
- `adr/0004-code-mode-trusted-filesystem-roots.md` — why Code Mode uses curated external filesystem roots, keeping reference trees read-only while allowing `/tmp` read/write access.

## Authority rule

The repository source/tests and current dependency lock are authoritative for current behavior. These docs explain architecture and maintenance intent; they must not override live code or upstream package contracts.
