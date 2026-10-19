# GPT Dive Pydantic ADRs

This directory contains **long-lived GPT Dive-specific architecture decisions about Pydantic AI / Pydantic AI Harness integration**.

Cross-domain decision ownership: [GPT Dive ADR index](../../ADR.md).

It does not replace the normal implementation docs in `docs/pydantic/`.

## Admission rule

Create an ADR here only when a decision:

- materially changes a durable architecture, authority, security, compatibility, or lifecycle boundary;
- has a realistic alternative that future maintainers might otherwise reconsider or accidentally reintroduce; and
- is expected to outlive one implementation patch.

Do **not** create an ADR for ordinary implementation detail, mechanical refactors, version bumps, or one-off acceptance results. Those belong in the relevant current-state document and/or `plans/` history.

## Document roles

- `../architecture.md` — current integration shape and evolution.
- `../code-mode.md` — current Code Mode implementation contract.
- `../providers.md` — current provider/model integration.
- `./` — durable **Decision + Why + rejected alternative/consequence** records only.
- `../../../plans/` — one-change spec, implementation plan, and acceptance evidence.

## Scope boundary

- GPT Dive-specific Pydantic implementation decision → this directory.
- Cross-component AI Orchestra operating decision → `~/wiki/workflow/orchestra/`.
- Generic Pydantic/Harness concept learned from upstream → `~/wiki/pydantic/`.

Preserve ADR identifiers once published. Gaps are acceptable when a historical decision is owned elsewhere after a documentation-boundary migration.
