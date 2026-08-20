# Stable Index Upgrade

Date: 2026-08-14 KST
Status: COMPLETE / production cutover PASS

> Canonical source-ID note (2026-08-16): the historical short IDs were re-keyed in place to `pydantic-ai` and `pydantic-ai-harness`. At the user's request, this completed plan now uses the current canonical IDs throughout; the recorded counts, versions, and acceptance results remain the original 2026-08-14 history.

## Goal / Why

Keep the local Pydantic evidence index on the latest **stable releases** while indexing only material with real retrieval value. The current brain is healthy, but the update path is not yet explicit enough: a default markdown sync can miss Python changes, while `strategy=auto` admits configuration/cassette formats that add noise.

The durable target is:

```text
latest stable tag
  -> high-value source/docs/tests/examples only
  -> deterministic filtered sync
  -> changed/stale chunks only on normal upgrades
  -> SOL opens the matching authoritative ~/ref files and reasons from them
```

This is an index-policy/pipeline change, not a GBrain product upgrade.

## Current State

Verified on 2026-08-14:

- GBrain runtime for this work: `0.45.9.0`; any GBrain product upgrade is a separate, version-volatile task.
- Brain baseline: `1144 pages / 21262 chunks / 21262 embedded`, 100% coverage.
- Current code pages: `947` total: `925 python`, plus `8 yaml / 7 toml / 3 json / 3 html / 1 typescript`.
- `pydantic-ai` checkout is exactly `v2.30.0`; remote latest stable tag is `v2.30.0`.
- `pydantic-ai-harness` remains on local branch `main`, but its HEAD commit is the `v0.20.0` stable tag commit; remote latest stable tag is `v0.20.0`.
- Reconstruction/maintenance SSOT remains `~/gbrain/local-docs/reconstruction.md`.
- Retrieval-only operating guidance remains `~/wiki/infra/gbrain.md`.

GBrain sync behavior relevant to this change:

- The source strategy defaults to `markdown` when no source/CLI strategy is set.
- `markdown` admits only `.md/.mdx`.
- `code` admits the broad code-extension set.
- `auto` admits markdown + all code extensions, including `.json`, `.yaml/.yml`, `.toml`, shell, HTML, etc.
- `--exclude` is repeatable and works in both full and incremental sync paths.
- `--exclude` cannot be combined with `sync --all`, so filtered refresh must run per source.
- Exclusion is conservative: newly excluded files are not automatically deleted from an already-populated brain. Therefore the first adoption of this filter is a filter-schema migration, not a normal incremental refresh.

Current tracked-file sanity counts for the proposed high-value roots and `.py/.md/.mdx` extensions:

- `pydantic-ai`: about `914` files (`645 py`, `269 md/mdx`) at the current checkout.
- `pydantic-ai-harness`: about `352` files (`285 py`, `67 md/mdx`) at the current checkout.

These are sanity anchors, not acceptance constants; stable releases legitimately change them and GBrain's own metafile/prune rules can reduce indexed page counts.

## Scope

### In scope

1. Create `~/gbrain/local-docs/index-filter.md` as the human-readable SSOT for what belongs in the stable search index and why.
2. Resolve/index **stable release tags**, never moving `main` as the canonical corpus target.
3. Make Python source updates deterministic rather than relying on the default markdown strategy.
4. Keep only high-value source/docs/tests/examples material in normal retrieval scope.
5. Replace broad `sync --all` maintenance with per-source filtered sync.
6. Perform a one-time clean candidate rebuild for the filter-policy migration.
7. After the migration, update stable releases incrementally and embed only changed/stale chunks.
8. Update `~/gbrain/local-docs/reconstruction.md` and, only where retrieval routing materially changes, `~/wiki/infra/gbrain.md`.

### Non-goals

- Upgrade GBrain itself from `0.45.9.0` to `0.45.10.0`.
- Change embedding provider, model, dimension, chunker, reranker, or search mode.
- Index `~/ref/pydantic-ai-pr-6433` or any other PR/nightly/main-only checkout.
- Tune query expansion, search ranking, or answer synthesis.
- Introduce hosted/vector infrastructure.

## Key Decisions

### Decision 1 — Stable tags are the corpus version boundary

**Decision:** The normal corpus follows the latest upstream stable tag for `pydantic-ai` and `pydantic-ai-harness`.

**Reason:** GBrain is an authoritative evidence locator for normal development questions. Stable tags give a reproducible version boundary and avoid indexing unreleased `main` churn.

**Rejected alternatives:**

- Track `main`: fresher but non-reproducible and can surface unreleased behavior.
- Keep permanently pinned old snapshots: reproducible but creates retrieval drift.

**Consequences / tradeoffs:** Version resolution becomes an explicit maintenance step. PR-specific investigation continues to read the PR checkout directly rather than contaminating the stable index.

### Decision 2 — `~/gbrain/local-docs/index-filter.md` owns search-value policy

**Decision:** A separate Index Filter document defines high-value roots, accepted content classes, exclusions, examples, and rationale.

**Reason:** “Index the latest stable corpus” is too vague. Future SOL needs a durable answer to “what is worth embedding?” that is separate from installation/reconstruction details.

**Rejected alternatives:**

- Hide the policy inside one long sync command: hard to review and easy to drift.
- Treat all GBrain-supported code/config formats as valuable: admits cassettes/config/generated noise.

**Consequences / tradeoffs:** The implementation helper must remain behaviorally consistent with the documented policy and its inclusion/exclusion test cases.

### Decision 3 — Positive search-value scope, implemented through `auto + excludes`

**Decision:** The policy is conceptually an allowlist: selected roots plus `.py` and `.md/.mdx`. GBrain currently exposes a broad strategy plus repeatable `--exclude`, not a positive `--include` flag on `sync`, so the operator helper compiles the policy into deterministic per-source sync arguments.

Target roots:

`pydantic-ai`:

- `pydantic_ai_slim/**`
- `pydantic_graph/**`
- `pydantic_evals/**`
- `examples/pydantic_ai_examples/**`
- `docs/**`
- `tests/**`
- `agent_docs/**`

`pydantic-ai-harness`:

- `pydantic_ai_harness/**`
- `docs/**`
- `tests/**`
- `integration_tests/**`
- `agent_docs/**`

Target extensions:

- `.py`
- `.md`
- `.mdx`

Examples of intentional exclusions:

- cassette/recording data such as `tests/**/cassettes/**/*.yaml`
- JSON/YAML/TOML configuration data such as `docs/nav.json` and project config
- locks, generated/build/vendor material, media assets
- unrelated top-level implementation/support directories outside the explicit root set

GBrain's built-in metafile/prune behavior remains in force, including its skip of structural basenames such as `README.md`.

**Reason:** Python implementation + docs + executable tests/examples are the highest-value evidence for SOL. Config/cassette bulk is cheap to open directly when specifically needed but expensive in recall noise when embedded broadly.

**Rejected alternatives:**

- `markdown`: misses Python implementation changes.
- `code`: misses docs.
- naked `auto`: includes too many low-value structured/config formats.

**Consequences / tradeoffs:** The helper must sync each registered source independently because GBrain forbids `--exclude` together with `--all`.

### Decision 4 — Filter changes trigger a clean rebuild; release changes do not

**Decision:** The initial adoption of this Index Filter is a full corpus rebuild into a separate candidate GBrain home. After cutover, ordinary stable release upgrades are incremental.

**Reason:** Existing excluded pages are preserved by GBrain's conservative `--exclude` semantics, so an incremental filtered sync cannot prove a clean corpus. A filter-policy change is one of the explicit reasons a full rebuild is justified.

**Rejected alternatives:**

- Incremental-only first migration: leaves previously indexed noise behind.
- Delete pages in-place while discovering the filter: harder to roll back and violates the preference to avoid unconfirmed destructive cleanup.

**Consequences / tradeoffs:** First migration pays a one-time full embedding cost. `GBRAIN_HOME` supports a side-by-side candidate home, so the known-good current brain stays untouched until acceptance passes.

### Decision 5 — Refresh and embedding are separate phases

**Decision:** Repo checkout + filtered sync run with `--no-embed` first. Real embedding is a separate gated step.

**Reason:** The local installation has a fail-closed Voyage free-quota guard because a prior unapproved embedding/provider-switch incident created unwanted cost/rate-limit risk. Separating phases makes corpus inspection possible before any provider call.

**Rejected alternatives:** Let `gbrain sync` auto-embed immediately.

**Consequences / tradeoffs:** One extra explicit operator step, in exchange for a clear cost boundary.

### Decision 6 — GBrain product upgrade is independent

**Decision:** Do not mix the GBrain binary upgrade into Stable Index Upgrade.

**Reason:** The local GBrain checkout carries a Voyage safety patch. Combining product upgrade, patch reapplication, filter migration, stable corpus refresh, and embeddings would make failures ambiguous and rollback harder.

## Implementation Direction

### 1. Index Filter SSOT

Create `~/gbrain/local-docs/index-filter.md` with:

- purpose and authority boundary;
- per-source allowed roots;
- allowed extensions/content classes;
- explicit noise exclusions and rationale;
- representative PASS/FAIL path examples;
- stable-tag policy;
- rule that PR-specific checkouts are read directly, never registered;
- change classification: stable release update = incremental; filter/model/dim/chunker change = rebuild review.

### 2. Stable refresh helper

Add a small local operator helper under `~/gbrain/local-patches/` rather than changing upstream GBrain sync semantics.

Responsibilities:

1. Determine the latest stable tag from upstream tag refs.
2. Refuse to alter a dirty reference checkout.
3. Fetch/checkout the selected stable tag reproducibly.
4. Compile the Index Filter into per-source `gbrain sync --strategy auto ... --no-embed` invocations.
5. Provide a dry-run mode that prints target tag, current tag/commit, source, and candidate scope before mutation.
6. Never register or touch the PR-specific clone.
7. Never switch embedding provider.

Normal refresh must run `pydantic-ai` and `pydantic-ai-harness` separately, not `sync --all`, because filtered `--exclude` scope is per invocation.

### 3. One-time filter migration

Build a clean candidate brain using an alternate `GBRAIN_HOME` parent directory:

```text
current known-good brain
        │
        ├── untouched rollback source
        │
        └── candidate GBRAIN_HOME
                -> init PGLite
                -> same Voyage model/dim config
                -> register only pydantic-ai + pydantic-ai-harness
                -> filtered sync --no-embed
                -> inspect corpus
                -> explicit embedding gate
                -> acceptance
                -> cut over only after PASS
```

Do not delete/overwrite the current `~/.gbrain` brain during candidate construction.

### 4. Normal stable update after migration

```text
resolve latest stable tags
  -> compare with recorded indexed stable versions
  -> clean checkout guard
  -> fetch/checkout changed tag(s)
  -> filtered per-source sync --no-embed
  -> review diff/stale count
  -> fresh Voyage quota guard
  -> explicit operator authorization
  -> embed --stale
  -> acceptance
  -> update reconstruction/version record
```

No full rebuild is expected when only stable source content changes and model/dim/chunker/filter are unchanged.

## Failure Policy

- Dirty `~/ref` checkout: **BLOCK**; do not reset or discard user work automatically.
- Stable tag resolution ambiguous/unavailable: **BLOCK**; keep current indexed stable version.
- Filter dry-run contains out-of-policy roots/extensions: **BLOCK** before sync.
- Candidate build failure: keep current brain untouched and report the failing phase.
- Fresh Voyage free-quota verification missing/invalid/below floor: **BLOCK embedding**.
- Real embedding without explicit operator authorization in the current execution: **BLOCK**.
- Provider failure: **BLOCK**; never auto-switch provider/model.
- GBrain upgrade notice during this task: report it, but do not upgrade as part of this plan.
- Do not destructively delete the current known-good brain during migration. Rollback is selecting the existing home again.

## Test Contract

### Filter inclusion

Given the current stable repos, the filter must admit representative paths in each evidence class:

- Pydantic AI Core Python source.
- Graph/Evals Python source.
- official Pydantic AI example Python.
- docs Markdown/MDX.
- Python unit tests.
- Harness package Python.
- Harness docs Markdown/MDX.
- Harness unit/integration Python tests.

### Filter exclusion

The filter must reject representative noise:

- YAML cassettes/recordings.
- `docs/nav.json` and other JSON config.
- TOML project/tool config.
- shell/build/support scripts outside the evidence roots.
- generated/vendor/build/lock/media files.
- any file under `~/ref/pydantic-ai-pr-6433` by virtue of the source never being registered.

### Sync behavior

Given an unchanged stable checkout after a successful refresh:

- a second filtered dry-run reports no unintended corpus change;
- no filtered maintenance path depends on `gbrain sync --all`;
- source failures/queues remain zero.

Given a stable tag update containing a changed `.py` file in an allowed root:

- the filtered sync imports/re-chunks that file even though the default GBrain strategy is markdown.

Given a changed YAML cassette:

- the filtered sync does not import it.

### Candidate corpus shape

After the clean candidate rebuild and before cutover:

- only `pydantic-ai` and `pydantic-ai-harness` are normal federated sources;
- code-page language distribution contains Python only under this policy;
- no YAML/TOML/JSON/HTML/TS code pages appear unless the Index Filter is intentionally revised later;
- embedding coverage reaches 100% only after the gated embedding phase;
- `gbrain embed --stale --dry-run` is zero after completion;
- `gbrain sources status` shows `FAILS 0 / QUEUE 0` for both sources.

### Retrieval probes

Run a small fixed probe set after candidate embedding:

1. exact/structural Pydantic AI implementation symbol;
2. Pydantic AI behavior documented in docs + tests;
3. Harness capability implementation;
4. Harness behavior backed by source + docs/tests.

For each, GBrain only needs to surface high-value candidates; final truth is checked by opening the returned `~/ref` files.

## Acceptance / Validation

Minimum evidence before cutover:

```text
[x] latest stable tags resolved from upstream refs
[x] reference checkouts clean before movement
[x] Index Filter PASS/FAIL path fixtures pass
[x] candidate non-empty source registrations are pydantic-ai + pydantic-ai-harness only
[x] filtered sync dry-run/apply stayed inside Filter v1
[x] candidate corpus has no disallowed code-language pages
[x] fresh Voyage quota guard PASS immediately before real embedding
[x] explicit operator authorization obtained before real embedding
[x] embedding coverage 100%
[x] normal stale dry-run = 0
[x] sources FAILS 0 / QUEUE 0
[x] retrieval probe set PASS
[x] previous known-good production brain preserved as rollback
[x] ~/gbrain/local-docs/reconstruction.md promoted to the new production tags/commits/counts after cutover
```

The final page/chunk totals are recorded after the build; they are not pre-fixed acceptance numbers.

## Result

Implementation, real Voyage embedding, retrieval acceptance, and production cutover completed on 2026-08-14 KST. The final production brain is the validated Stable Index candidate, exposed at the normal `~/.gbrain` path through a symlink to `~/.cache/gbrain-stable-index-v1/.gbrain`; the previous production brain is preserved at `~/.gbrain.rollback-pre-stable-index-20260814`.

Implemented:

- Index Filter SSOT: `~/gbrain/local-docs/index-filter.md` (Filter v1).
- Stable refresh helper: `~/gbrain/local-patches/stable-index-refresh`.
  - resolves numeric stable tags from upstream refs;
  - refuses dirty reference checkouts;
  - previews target/current tag and filter counts;
  - checks out exact stable tags on `--apply`;
  - runs per-source `gbrain sync --strategy auto --no-embed --no-pull` with exact-path excludes compiled from Filter v1;
  - blocks `--full` on the default brain unless an explicit non-default `GBRAIN_HOME` is set;
  - treats textual `Sync BLOCKED` / `Full sync blocked:` as failure even when GBrain returns process exit 0;
  - never embeds or switches provider;
  - `--self-test`: 12 include fixtures + 9 exclude fixtures PASS.
- One-line GBrain compatibility fix in `src/core/frontmatter-inference.ts`: inferred titles containing a backtick are YAML-quoted.
  - Why: Pydantic AI v2.30.0 API-reference files such as ``docs/api/usage.md`` are bare Markdown whose first H1 is ``# `pydantic_ai.usage` ``. GBrain's inference serialized this as invalid YAML `title: `pydantic_ai.usage`` and blocked 69 files.
  - Regression: `test/frontmatter-inference.test.ts` now covers a backtick-leading inferred title; focused suite is 43 PASS / 0 FAIL.
  - `bun run typecheck`: PASS.

Stable targets / checkouts:

```text
pydantic-ai          v2.30.0  c24a9008a...
pydantic-ai-harness  v0.20.0  bbd773d7...
```

Both `~/ref` checkouts are now detached at those exact stable tags.

Candidate brain:

```text
GBRAIN_HOME   ~/.cache/gbrain-stable-index-v1
engine        PGLite
search.mode   conservative
embedding     voyage:voyage-code-3 / 1024d

pydantic-ai           885 pages / 100% embedded
pydantic-ai-harness   319 pages / 100% embedded
TOTAL         1204 pages
CHUNKS       21368
EMBEDDED      21368
CODE           930 pages, all Python
FAILS            0
QUEUE            0
STALE            0 chunks
```

The implicit empty `default` source row remains at 0 pages and is not part of the normal corpus.

Known-good production brain remained untouched throughout candidate construction:

```text
Pages       1144
Chunks      21262
Embedded    21262
pydantic-ai          818 pages / 100% embedded
pydantic-ai-harness  326 pages / 100% embedded
```

The first full `pydantic-ai` candidate sync exposed two GBrain behaviors that are now accounted for:

1. 69 official API-reference Markdown files failed because of the inferred-title YAML quoting bug above. After the one-line fix, all 69 imported successfully and the source checkpoint completed.
2. A blocked full sync can emit process exit 0. The helper therefore fail-closes on GBrain's blocked-state text instead of trusting return code alone.

Final embedding / cutover acceptance:

1. Immediately before real embedding, the browserless Voyage guard returned `PASS` with `195,443,218 / 200,000,000` free tokens remaining.
2. The operator explicitly authorized the real candidate embedding in this execution.
3. `gbrain embed --stale` embedded all `21,368` chunks across `1,170` embedding pages; exit code was 0.
4. Post-embed acceptance: `21,368 / 21,368` embedded, ordinary stale dry-run `0`, source `FAILS 0 / QUEUE 0`.
5. Retrieval probes passed for Pydantic `AbstractAgent.run`, Pydantic output-validation retries, Harness `ToolOutputLimits`, and Harness FileSystem/symlink safety.
6. The post-embed Voyage guard reported `194,165,967` remaining. This execution consumed `1,277,251` free tokens, about `0.639%` of the 200M allowance; about `97.08%` remains.
7. A first cutover attempt physically moved the PGLite `.gbrain` directory. The default path then opened an empty brain (`0 pages / 0 chunks`). Acceptance caught this immediately and rollback restored the previous production with `1144 / 21262 / 100%` intact.
8. Moving the embedded candidate back to its original path restored `1204 / 21368 / 100%`, proving the candidate data survived. A non-destructive symlink test then passed.
9. Final cutover preserves the candidate's original PGLite path and makes `~/.gbrain` a symlink to `~/.cache/gbrain-stable-index-v1/.gbrain`. Default-path status/stats/stale/retrieval all PASS; the old production remains at `~/.gbrain.rollback-pre-stable-index-20260814` for rollback.
10. The embed progress denominator is misleading (`1170/319`, >100%); completion authority is the final embedded-chunk count plus stale=0, not that progress percentage.
11. GBrain product upgrade remains a separate task; the runtime emitted an upgrade notice during acceptance, but no upgrade was performed.
