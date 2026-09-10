# Probe in GPT Dive

Checked: 2026-09-11 KST
Status: external CLI used through Code Mode `run_command`

## Boundary

Probe is a local repository context engine, not a GPT Dive capability or reasoning agent. GPT Dive intentionally does not wrap its search result schema.

```text
Web SOL
  → GPT Dive code_mode
  → run_command
  → probe search / extract / symbols / query
  → bounded shell output
  → SOL reasoning
```

Use Probe for fuzzy source discovery; use `rg`, `search_files`, or `find_files` for known literals and filenames. Use CodeGraph when the question becomes caller/impact/relationship oriented.

This keeps the runtime smaller:

```text
exact text / filename      → search_files / find_files / rg
fuzzy source discovery    → run_command → probe search
known hit / owner          → run_command → probe extract / symbols
structural AST query       → run_command → probe query
callers / impact / flow    → CodeGraph
```

## Installed CLI contract

Check the live command before relying on flags:

```bash
probe search --help
probe extract --help
probe symbols --help
probe query --help
```

Probe needs no GPT Dive-local index or daemon. Avoid adding embeddings, a vector database, a reranker service, or another MCP layer unless real retrieval failures justify the extra architecture.

## References

- `~/wiki/workflow/search.md` — search routing SSOT
- `~/ref/probe/README.md` — Probe upstream/reference source
- current Code Mode generated declarations — runtime capability authority
