# Probe in GPT Dive

Checked: 2026-08-14 KST
Status: active retrieval capability; ranking promotion blocked on upstream release

## Why Probe is here

Probe is a **local repository context engine** for Web SOL, not another reasoning agent or knowledge system.

GPT Dive uses it to answer fuzzy repository questions such as:

- where/how a behavior is implemented;
- which source blocks are most relevant before reasoning;
- which code or Markdown sections should be read instead of dumping broad grep output.

The intended boundary is small:

```text
Web SOL
  -> GPT Dive code_mode
  -> search_repo()
  -> Probe
  -> compact path + lines + code + score + symbol
  -> SOL reasoning
```

Exact known identifiers/strings remain better served by `rg`; Probe is strongest for fuzzy architectural or code-location discovery.

## Current local integration

`src/gpt_dive/repo_search.py` already wraps Probe behind `search_repo()` and returns compact JSON evidence rather than raw CLI output.

Current compact fields:

- `file`
- `lines`
- `code`
- `score`
- `symbol`
- `language`

This is intentionally retrieval-only. GPT Dive does not need a second agent, vector database, background knowledge service, or GBrain-style memory layer for this role.

## Local evidence

Two bounded searches against `~/gpt-dive` showed the useful tradeoff:

| Query shape | Probe | raw `rg` | Observation |
|---|---:|---:|---|
| subagent / code_mode | ~0.42 s, ~3.1 KB | near-instant, ~26.5 KB | Probe returned about 8.5x less model-visible text |
| background result/error propagation | ~0.49 s, ~3.5 KB | ~0.02 s, ~83 KB | Probe returned about 23x less text and surfaced the implementation seam directly |

These tests support Probe as a **context-shaping primitive**, not as proof that it always has better recall than grep.

Current routing candidate:

```text
known exact identifier/string -> rg
fuzzy "where/how is this implemented?" -> Probe
chosen target -> Probe extract or direct read
```

## Upstream blocker: ranking correctness

The installed release is still the pre-fix `0.6.0-rc330` line. Upstream PR #583, **Fix/ranking correctness and stability**, was merged on 2026-08-11 but was not in the published release when last checked.

PR #583 matters directly to AI evidence retrieval because it fixes:

1. exact/quoted queries skipping BM25 relevance ranking;
2. `--max-results` changing the scoring/candidate pool and therefore changing ranking;
3. AST block merges discarding a better rank;
4. outline formatting hiding relevance order by regrouping files.

Local rc330 reproduction confirmed the exact-search problem: exact results had missing/null ranking fields and the defining symbol could appear only when `--max-results` was increased.

A fuzzy search still produced populated `score` and `bm25_score`, but JSON presentation order was not score order. This does **not** mean sorting locally fixes #583; candidate scoring and selection correctness must be fixed upstream.

Therefore the current policy remains:

> Do not promote Probe to a universal Probe-first search policy until a released build containing #583 passes local revalidation.

## TODO after a release containing #583

- [ ] Confirm the published Probe release contains PR #583 / commit `e34a3d4277a45acd2bd1463619bfb95ec067cc66`.
- [ ] Upgrade the local Probe package.
- [ ] Re-run the two existing bounded-search comparisons with the same queries and budgets.
- [ ] Compare `--max-results` values and verify relevance ordering/candidate stability.
- [ ] Verify exact search now exposes meaningful ranking fields and ranks the defining symbol/file sensibly.
- [ ] Inspect the new JSON schema for an explicit rank field.
- [ ] If useful, make `search_repo()` preserve explicit rank and stabilize presentation order without reimplementing Probe ranking.
- [ ] Re-run the targeted GPT Dive repo-search/runtime tests.
- [ ] If all checks pass, reconsider making bounded Probe search the default for fuzzy repository discovery.

## What not to add yet

Do **not** add embeddings, LanceDB, a reranker, daemon/index service, or a separate MCP server merely because they are available.

The current corpus/retrieval problem is small enough that `rg + Probe + SOL` is the simpler baseline. Embeddings or another engine should be considered only after real Pydantic/Harness questions demonstrate repeatable semantic-recall failures that Probe cannot solve well.

A future challenger such as Semble can be benchmarked against Probe, but it is not currently a reason to replace the working GPT Dive integration.

## Related local references

- `src/gpt_dive/repo_search.py`
- `tests/test_repo_search.py`
- `tests/test_code_runtime.py`
- `~/wiki/pydantic/study/probe/role-boundary.md`
- upstream Probe PR #583
