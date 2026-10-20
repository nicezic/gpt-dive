# GBrain Stable Index Filter

Updated: 2026-10-20 KST
Status: active filter policy for two upstream repositories (Core + Harness, Monty)
Filter version: 3

## Purpose

This document is the **Index Filter SSOT** for the user's stable Pydantic GBrain corpus.

It answers one question:

> Which files from the latest stable Pydantic AI (including Harness) / Monty releases are worth putting into semantic retrieval?

Installation, database reconstruction, provider/model configuration, quota guards, and recovery remain in `~/gpt-dive/gbrain/docs/reconstruction.md`. Retrieval usage remains in `~/wiki/workflow/search.md`.

## Core invariant

The normal corpus is:

```text
latest upstream stable tag
  ∩ git-tracked files
  ∩ approved evidence roots
  ∩ approved evidence extensions
  ∩ GBrain built-in safety/prune rules
```

Anything outside that intersection is **not normal search corpus**, even if GBrain technically knows how to parse it.

GBrain is a retrieval layer, not a mirror of every file in the upstream repositories.

## Version boundary

Normal indexing follows the latest **stable release tag** of:

- `pydantic/pydantic-ai` (Core + Harness)
- `pydantic/monty`

Do not use moving `main` as the canonical corpus target.

Pre-release, PR-specific, experimental checkout, or one-off investigation content is read directly from its checkout when needed; it is not added to the stable brain.

Specifically excluded from the normal brain:

```text
~/ref/pydantic-ai-pr-6433
```

## Source: `pydantic-ai`

Checkout:

```text
~/ref/pydantic-ai
```

Approved roots:

```text
pydantic_ai_slim/**
pydantic_graph/**
pydantic_evals/**
src/pydantic_ai_harness/**
examples/pydantic_ai_examples/**
docs/**
tests/**
agent_docs/**
```

Why these roots:

- `pydantic_ai_slim/`: Core implementation and provider/runtime behavior.
- `pydantic_graph/`: graph/runtime implementation used by the ecosystem.
- `pydantic_evals/`: eval implementation and contracts.
- `src/pydantic_ai_harness/`: Harness implementation after the upstream repository merger; `docs/harness/` is covered by `docs/`.
- `examples/pydantic_ai_examples/`: official executable usage examples.
- `docs/`: official user-facing behavior and API guidance.
- `tests/`: executable behavioral evidence and regression contracts.
- `agent_docs/`: upstream agent-facing operational/reference guidance with direct development value.

## Source: `pydantic-ai-monty`

Checkout:

```text
~/ref/pydantic-ai-monty
```

Approved roots:

```text
README.md
crates/monty/src/**
crates/monty/README.md
crates/monty-alloc/**
crates/monty-fs/**
crates/monty-js/**
crates/monty-macros/**
crates/monty-pool/**
crates/monty-proto/**  # except src/generated/**
crates/monty-python/**
crates/monty-runtime/**
crates/monty-type-checking/**
crates/monty-types/**
crates/monty-wasm-runtime/**
limitations/**
examples/**
packages/pydantic-monty/**
```

Why these roots:

- top-level and crate `README.md`: public architecture/package context.
- `crates/monty/src/` plus selected `crates/monty-*` runtime/binding crates: Monty VM/runtime, Python binding, filesystem, protocol, type-checking, and runtime integration implementation. Rust is first-class implementation evidence here.
- `limitations/`: explicit compatibility and resource-limit boundaries.
- `examples/`: executable Python examples showing the embedding/runtime surface.
- `packages/pydantic-monty/`: public package-facing documentation.
- `crates/monty/test_cases/` is bulk executable fixture data (566 Python files at v0.0.21), not normal semantic evidence; `crates/monty-proto/src/generated/` is generated protocol output; fuzzing, benchmark-only crates, release scripts, and project configuration are also excluded.

## Approved evidence extensions

Approved extensions are source-specific:

```text
pydantic-ai          .py .md .mdx
pydantic-ai-monty    .rs .py .md .mdx
```

### Why Python

Pydantic AI and Harness are overwhelmingly Python, and Monty exposes Python examples/integration surfaces. Python source gives high-value implementation, provider, tool, capability, test, and example evidence.

### Why Rust

Monty's VM/runtime implementation is Rust. Excluding `.rs` would turn the Monty source into a mostly documentation/example index and omit the implementation evidence that Code Mode questions need. Rust is therefore allowed only for the Monty approved roots.

### Why Markdown / MDX

Official docs and agent-facing reference material often explain intended behavior, caveats, migrations, and usage more clearly than implementation alone.

## Intentionally excluded content

The following are normally excluded from semantic indexing even when they are tracked or parseable.

### Cassette / recording / bulk fixture data

Examples:

```text
tests/**/cassettes/**/*.yaml
tests/**/recordings/**/*
large serialized fixtures
```

Reason: high volume, low general retrieval value, and strong risk of ranking noisy request/response payloads above source/docs/tests that explain the behavior.

### Project/tool configuration

Examples:

```text
*.json
*.yaml
*.yml
*.toml
uv.lock
package/tool configuration
navigation manifests such as docs/nav.json
```

Reason: these files can be opened directly when a dependency/configuration question specifically requires them. Broad semantic indexing adds low-signal tokens to normal implementation queries.

### Build/support/generated/vendor material

Examples:

```text
scripts outside approved evidence roots
build output
generated files
vendor/dependency trees
lock files
media/binary assets
```

GBrain also has built-in prune rules for hidden/vendor/build directories. This policy does not weaken those guards.

### Unapproved top-level roots

A file is excluded when it is outside the approved roots, even if its extension is `.py` or `.md`.

This prevents a future upstream directory from silently joining the semantic corpus merely because `strategy=auto` recognizes its extension.

## Representative PASS paths

These are policy examples, not frozen upstream filenames.

```text
PASS  pydantic-ai          pydantic_ai_slim/pydantic_ai/.../*.py
PASS  pydantic-ai          pydantic_graph/.../*.py
PASS  pydantic-ai          pydantic_evals/.../*.py
PASS  pydantic-ai          src/pydantic_ai_harness/.../*.py
PASS  pydantic-ai          docs/harness/.../*.md
PASS  pydantic-ai          examples/pydantic_ai_examples/.../*.py
PASS  pydantic-ai          docs/.../*.md
PASS  pydantic-ai          tests/.../test_*.py
PASS  pydantic-ai          agent_docs/.../*.md


PASS  pydantic-ai-monty    crates/monty/src/.../*.rs
PASS  pydantic-ai-monty    crates/monty-runtime/src/.../*.rs
PASS  pydantic-ai-monty    crates/monty-python/src/.../*.rs
PASS  pydantic-ai-monty    README.md
PASS  pydantic-ai-monty    crates/monty/README.md
PASS  pydantic-ai-monty    limitations/.../*.md
PASS  pydantic-ai-monty    examples/.../*.py
PASS  pydantic-ai-monty    packages/pydantic-monty/.../*.md
```

## Representative FAIL paths

```text
FAIL  pydantic-ai          tests/.../cassettes/foo.yaml
FAIL  pydantic-ai          docs/nav.json
FAIL  pydantic-ai          pyproject.toml
FAIL  pydantic-ai          scripts/release.sh
FAIL  pydantic-ai          unrelated_new_root/new_feature.py


FAIL  pydantic-ai-monty    Cargo.toml
FAIL  pydantic-ai-monty    Cargo.lock
FAIL  pydantic-ai-monty    crates/monty/test_cases/.../*.py
FAIL  pydantic-ai-monty    crates/fuzz/.../*.rs
FAIL  pydantic-ai-monty    crates/monty-bench/.../*.rs
FAIL  pydantic-ai-monty    crates/monty-proto/src/generated/.../*.rs
FAIL  pydantic-ai-monty    scripts/.../*.py
FAIL  pydantic-ai-monty    unrelated_new_root/feature.rs

FAIL  normal brain  ~/ref/pydantic-ai-pr-6433/**
```

## GBrain strategy mapping

GBrain `0.46.12.0` exposes these sync strategies:

```text
markdown -> .md/.mdx only
code     -> broad code/config extension set
    auto     -> markdown + broad code/config set
```

A naked `auto` is therefore **not** this policy.

The operator pipeline may use `--strategy auto` only when it also enforces this SSOT's approved roots and extensions through deterministic filtering.

Important current CLI constraints:

- `--exclude` is repeatable.
- `--exclude` cannot be combined with `sync --all`.
- filtered maintenance therefore runs `pydantic-ai` and `pydantic-ai-monty` separately.
- exclusion does not remove an already-indexed page merely because it is newly excluded.

The implementation mechanism may evolve, but its resulting file set must remain equivalent to this policy.

## Change classification

### Incremental refresh

Use normal incremental sync + stale embedding when only the stable release content changes and these remain unchanged:

- Index Filter policy
- embedding model
- embedding dimensions
- chunker semantics/version requiring rebuild

### Rebuild review

A clean rebuild is justified when a material index-shape invariant changes, including:

- Index Filter roots/extensions change materially;
- embedding provider/model changes;
- embedding dimension changes;
- chunker change invalidates existing chunks;
- stored corpus is known to contain content that new exclusion rules cannot remove incrementally.

The initial adoption of Filter version 1 was such a migration because previously indexed low-value config/code pages could remain under conservative exclusion semantics.

Filter version 3 folds the merged Harness code/docs into the `pydantic-ai` source policy and removes the standalone Harness checkout. Existing GBrain pages, source IDs, and embeddings are retained as historical data until a separately authorized index migration; this policy change alone does not run sync, delete source records, or consume embedding quota.

## Cost / execution boundary

Index policy is separate from permission to spend provider quota.

Repository update and filtered sync should be inspectable with embedding disabled first.

Real Voyage embedding requires:

```text
fresh quota verification PASS
  + explicit operator authorization for that execution
  + no provider/model auto-switch
```

If the guard fails or provider behavior is uncertain, keep the refreshed unembedded/stale state or the current known-good brain rather than switching providers automatically.

## Acceptance rule

A candidate corpus passes this filter when:

```text
1. new filesystem-backed sources come only from the intended two upstream repositories (`pydantic-ai`, `pydantic-ai-monty`); preexisting Harness-indexed records are not silently deleted
2. every indexed filesystem-backed page maps to an approved root/content class
3. Core/Harness code is Python in the merged `pydantic-ai` policy; Monty code may be Rust or Python only inside its approved roots
4. cassette/config/generated/fuzz/benchmark bulk is absent
5. representative PASS paths are indexable
6. representative FAIL paths are not indexed
```

Exact page/chunk totals are recorded after each stable refresh but are not part of the policy because upstream releases legitimately change them.
