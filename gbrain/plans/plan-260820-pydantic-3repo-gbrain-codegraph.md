# Pydantic 3-Repo GBrain + CodeGraph Refresh

Date: 2026-08-20 KST
Status: COMPLETE

## Problem Statement

The local Pydantic retrieval system currently treats `pydantic-ai` and `pydantic-ai-harness` as the complete normal corpus, while Monty has now become a first-class dependency of the Code Mode stack and exists as a third local upstream reference repository. As a result, semantic retrieval, Stable Index maintenance policy, and CodeGraph coverage are inconsistent with the actual architecture.

The refresh path also needs to preserve the current safety properties: reproducible stable-release boundaries, high-value-only indexing, stale-only Voyage embedding, free-usage accounting, and retrieval acceptance before declaring the corpus healthy.

## Solution

Expand the normal Pydantic corpus from two physical sources to three by adding Monty as its own canonical source, keeping all three source identities separate under the existing `pydantic` named source group.

All three repositories will be resolved to their latest numeric stable release before indexing. The Stable Index filter and refresh helper will be extended so Monty follows the same high-value source/docs/tests policy rather than being indexed wholesale.

The change will be applied in two planes:

1. GBrain: repository refresh -> filtered sync without embedding -> Voyage guard/baseline -> stale-only embedding -> source-specific and cross-repo retrieval acceptance -> usage/cost accounting.
2. CodeGraph: after GBrain acceptance, ensure all three repositories have indexes current for the final checkout and run a Monty symbol smoke test.

## User Stories

1. As the primary engineer, I want all three Pydantic repositories represented in semantic retrieval, so that Code Mode questions can retrieve Monty evidence as naturally as Core and Harness evidence.
2. As the primary engineer, I want each repository to remain a separate physical GBrain source, so that retrieval provenance is explicit and source-scoped debugging remains possible.
3. As the primary engineer, I want the existing `pydantic` named source group to include all three sources, so that normal unqualified Pydantic queries search Core, Harness, and Monty together.
4. As the primary engineer, I want the corpus boundary to follow numeric stable releases rather than moving `main`, so that retrieved evidence is reproducible and does not silently include unreleased behavior.
5. As the primary engineer, I want dirty reference checkouts to block automatic updates, so that local work cannot be overwritten by maintenance.
6. As the primary engineer, I want Monty indexing roots derived from the actual repository tree, so that the filter reflects its real architecture rather than copied assumptions from the other repositories.
7. As the primary engineer, I want only high-value implementation, documentation, and tests embedded, so that retrieval quality is not diluted by generated output, bulk fixtures, release tooling, or configuration noise.
8. As the primary engineer, I want the Stable Index refresh helper to understand all three sources, so that one maintenance path remains the canonical corpus refresh mechanism.
9. As the primary engineer, I want the refresh helper to remain incapable of spending embedding quota, so that corpus inspection and sync can be reviewed before any provider usage occurs.
10. As the primary engineer, I want stale embedding size measured before execution, so that the amount of provider work is visible before spending free allowance.
11. As the primary engineer, I want the existing Voyage quota guard and credential path preserved, so that corpus changes cannot silently bypass usage protection.
12. As the primary engineer, I want only stale/required chunks embedded when the embedding shape is unchanged, so that adding Monty or updating releases does not trigger an unnecessary full re-embed.
13. As the primary engineer, I want source-level coverage, failures, queues, and ordinary stale state checked after embedding, so that completion is determined by the index state rather than progress output.
14. As the primary engineer, I want a retrieval canary for each of Core, Harness, and Monty, so that every source proves it can actually win relevant retrieval results.
15. As the primary engineer, I want one cross-repository retrieval test, so that the combined corpus proves it can answer questions about the responsibility boundary between Core, Harness, and Monty.
16. As the primary engineer, I want an explicitly Monty-scoped query, so that source registration can be tested independently from federated ranking.
17. As the primary engineer, I want before/after Voyage usage recorded, so that the token delta attributable to this maintenance run is measurable.
18. As the primary engineer, I want nominal list-price value separated from actual billed cost, so that free allowance usage is not confused with cash spend.
19. As the primary engineer, I want current operational documentation updated to the three-source topology while preserving historical two-source records, so that future sessions can distinguish current state from history.
20. As the primary engineer, I want CodeGraph coverage for all three final checkouts, so that symbol/flow exploration and semantic retrieval cover the same upstream architecture.
21. As the primary engineer, I want a real Monty CodeGraph explore canary, so that presence of an index directory alone is not treated as proof of a usable index.

## Implementation Decisions

- The normal Pydantic corpus will contain three separate physical sources: Core, Harness, and Monty.
- The existing logical `pydantic` source group remains the default federated retrieval boundary and will be expanded to contain all three sources.
- Source identity will not be physically merged. Provenance, source-scoped queries, page/chunk identity, and independent maintenance remain available.
- Numeric stable releases are the canonical corpus version boundary for all three sources. A moving development branch is not a normal-corpus target.
- Repository updates must fail closed on dirty worktrees and must verify that the final checkout exactly matches the selected stable release commit.
- Monty receives its own Stable Index policy derived from its current tree. The allowed material is conceptually an allowlist of high-value implementation/docs/tests/reference content.
- Existing Index Filter behavior remains conservative: low-value/generated/configuration-heavy content is excluded even when the underlying parser can ingest it.
- The Stable Index refresh helper remains the single operator path for filtered repository sync and remains unable to invoke embedding.
- Adding Monty is treated as a source/corpus expansion, not as a reason to change the embedding provider, model, dimensions, reranker, search mode, or database architecture.
- When the current embedding shape remains compatible, maintenance uses incremental filtered sync plus stale-only embedding rather than a clean full re-embed.
- Provider-dependent embedding continues through the established credential wrapper and Voyage quota guard. Provider fallback is not automatic.
- Usage accounting records a before/after provider ledger delta. Conservative local token estimates must be labeled as estimates.
- Cost reporting separates token consumption, nominal list-price equivalent, and actual billed cost after free allowance.
- Current-state docs are updated to describe three sources, but completed historical measurements remain historical rather than being rewritten.
- CodeGraph indexing is downstream of successful GBrain acceptance so both search planes are built from the same final repository checkouts.

## Testing Decisions

The highest-value test seams are intentionally few and operate at observable boundaries rather than internal implementation details.

### 1. Stable Index refresh seam

Use the existing refresh helper's self-test and preview/apply boundary as the primary corpus-policy test seam.

A good test proves externally visible behavior:

- all three sources are recognized;
- intended Monty paths are accepted;
- representative low-value Monty paths are rejected;
- preview resolves all three stable targets;
- filtered sync runs with embedding disabled;
- a dirty checkout blocks update rather than being overwritten.

Prefer extending the existing include/exclude fixture pattern rather than introducing a second filter test framework.

### 2. GBrain retrieval seam

Use the real GBrain query surface as the semantic acceptance seam.

Required canaries:

- one current Core-specific question whose relevant top evidence comes from Core;
- one current Harness-specific question whose relevant top evidence comes from Harness;
- one current Monty-specific question whose relevant top evidence comes from Monty;
- one cross-repository question requiring evidence from the Core/Harness/Monty responsibility boundary;
- one query explicitly scoped to Monty.

Index health must also show healthy embedding coverage, zero ordinary stale chunks, zero failures, and zero queued embedding work before this seam passes.

### 3. CodeGraph seam

Use the real CodeGraph CLI/index surface after GBrain acceptance.

A good test proves that each final checkout has a current usable index, then selects one real Monty symbol and runs an `explore` smoke query that returns relevant structure. Presence of `.codegraph` alone is insufficient.

### Usage/cost evidence

Provider usage is tested through the existing guard/ledger before and immediately after the real embedding operation. The reported delta must be attributable to the maintenance window and clearly distinguish estimated versus authoritative values.

## Out of Scope

- Upgrading the GBrain product version.
- Changing the embedding provider or embedding model.
- Changing embedding dimensions.
- Changing the reranker or search mode.
- Changing chunker semantics unless execution discovers an independently blocking incompatibility.
- Indexing PR-specific, nightly, or development-branch-only Pydantic checkouts into the normal corpus.
- Physically merging the three GBrain sources.
- Broad retrieval tuning unrelated to adding Monty.
- Replacing GBrain or CodeGraph with another search system.
- Adding low-value fallback paths when the established Stable Index or Voyage guard path fails.

## Further Notes

### Execution order

```text
inspect three repos
  -> resolve/update latest numeric stable tags
  -> inspect Monty tree and extend Index Filter
  -> extend Stable Index refresh helper + self-test
  -> register Monty + expand pydantic source group
  -> filtered sync with embedding disabled
  -> capture GBrain + Voyage baseline
  -> stale-only Voyage embedding
  -> GBrain health + retrieval canaries
  -> calculate token delta / nominal cost / actual billed cost
  -> update current-state operational docs
  -> refresh/init CodeGraph for all three final checkouts
  -> Monty CodeGraph explore smoke
```

### Current verified anchors before implementation

- Core and Harness local checkouts are detached.
- Monty currently tracks upstream `main`, so it must be moved to the selected stable release for normal-corpus use.
- Monty publishes numeric stable release tags.
- The current named Pydantic group and Stable Index helper are still two-source definitions.
- Current embedding is Voyage `voyage-code-3` at 1024 dimensions.
- Core and Harness currently have CodeGraph directories; Monty does not.

### Final acceptance report

The implementation report should summarize:

```text
Repo      before -> stable target -> final SHA
GBrain    2 -> 3 sources, pages/chunks/coverage/stale/failures/queue
Retrieval Core/Harness/Monty/cross-repo canaries
Voyage    before/after/delta, nominal value, actual billed cost, free quota remaining
CodeGraph Core/Harness/Monty index status + Monty explore canary
Changes   actual changed files only
Issues    actual unresolved issues only
```

### Completed acceptance — 2026-08-20 KST

```text
Repos      Core v2.32.1 / Harness v0.24.0 / Monty v0.0.21; all detached and clean
GBrain     3 sources / 1568 pages / 27087 chunks / 100% embedded / stale 0 / FAILS 0 / QUEUE 0
Filter     v2 / 19 include + 17 exclude fixtures PASS; Monty bulk test_cases + generated proto excluded
Retrieval  Core PASS / Harness PASS / Monty PASS / Monty-scoped PASS / cross-repo PASS
Voyage     delta 12,221,544 conservative estimated tokens / nominal ~$2.20 / actual billed $0
CodeGraph  Core PASS / Harness PASS / Monty PASS; ResourceLimits extract_limits explore PASS
Tests      helper self-test PASS / typecheck PASS / diff-check PASS / verify 53 of 54 PASS
Known gate full unit attempted but local 1x1 memory-adapted run exceeded the 540s execution window; verify's only failure is pre-existing module-size ratchet drift in five untouched src files
```
