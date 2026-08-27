# Pydantic Integration Architecture

> Development lineage and current ownership boundaries for GPT Dive's Pydantic AI / Harness integration. Exact current behavior is owned by source, tests, dependency locks, and live capability discovery.

## Why Pydantic entered GPT Dive

GPT Dive began as a small MCP bridge for direct WSL2 control. As local work grew beyond single shell commands, the repository needed a programmable execution layer that could compose tools, filter large intermediate results, call local models selectively, and keep the Web-facing MCP surface small.

Pydantic AI and `pydantic-ai-harness` supplied reusable model/tool/capability primitives without requiring GPT Dive to become a monolithic autonomous-agent runtime.

## Evolution

```text
Local MCP bridge
  -> sync / async WSL2 execution
  -> Pydantic-backed Code Mode
  -> registry-owned local capabilities
  -> explicit subagent model calls
  -> Harness coding-worker bundle
  -> direct Harness FileSystem + bounded run_command in Code Mode
  -> local Codex subscription compatibility layer
  -> Probe-backed repository retrieval
  -> current extensible runtime
```

### 1. Pydantic as the local harness substrate

**Change**
- Adopted Pydantic AI Core plus Pydantic AI Harness as the primary local model/capability substrate behind GPT Dive.

**Why**
- Reuse provider/model/tool/capability semantics instead of inventing an agent framework inside GPT Dive.
- Keep Web SOL as the primary engineer/conductor while allowing local model calls and deterministic capability composition when useful.

### 2. Code Mode as the programmable root

**Change**
- Added `code_mode` as the primary programmable MCP execution root, backed by a fresh Monty runtime and a per-run `CallableRegistry`.
- Reduced the current Web MCP surface to `bootstrap`, `code_mode`, and the Runtime-owned `task` lifecycle tool instead of adding one top-level tool per local capability.

**Why**
- Multiple operations can be composed or run concurrently inside one model-visible call.
- Large intermediate data can be reduced locally before returning to Web SOL.
- Reusable behavior can grow behind one stable top-level contract.

Primary implementation: `src/gpt_dive/code_capabilities.py`, `src/gpt_dive/app.py`, `src/gpt_dive/code_runtime.py`.

### 3. Explicit local model primitive

**Change**
- Added `subagent_call(model, task, ...)` behind Code Mode rather than exposing each model/provider as a top-level MCP tool.
- Added the underlying `invoke_model_call(...)` primitive for deliberately tool-less model calls, then upgraded the outer Code Mode `peer_review(...)` route into a draft independent peer reviewer with read-only Harness `FileSystem + CodeMode`. Tool-less mode remains available internally for callers such as `m3_evidence()`.
- Added `agy_worker(task, model=...)` as a separate external-worker capability for Google Antigravity through the official `agy` CLI; it defaults to `gemini-3.7-flash-high`, uses `stream-json`, and launches in read-only `plan` mode with headless tool approvals auto-approved so bounded investigation does not stall on permission prompts.

**Why**
- Web SOL often already knows which model or worker to consult and does not need an extra local parent-agent turn.
- Provider details stay behind the central model registry for Pydantic models. `agy` stays separate because it is already an external agent runtime, not a Pydantic `Model`, and Google authentication/entitlement remain owned by the official CLI.

Primary implementation: `src/gpt_dive/subagent_runtime.py`, `src/gpt_dive/subagent_worker.py`, `src/gpt_dive/model_call.py`, `src/gpt_dive/model_registry.py`, `src/gpt_dive/agy_worker.py`. Peer-review details: `docs/pydantic/peer-review.md`.

### 4. Harness coding-worker bundle

**Change**
- Workspace-enabled subagents receive official Harness `FileSystem + Shell + RepoContext + ToolOutputLimits` capabilities.

**Why**
- Reuse upstream filesystem containment, repo instruction discovery, command execution, and output bounding.
- Avoid a growing set of hand-written agent tools.

GPT Dive still owns lower local execution policy such as `guard-bin` PATH precedence and provider-credential stripping. Harness Shell is not treated as an OS sandbox.

### 5. Direct FileSystem, always-durable execution, and one awaited command

**Change**
- Registered the Harness FileSystem toolset directly in the Code Mode registry: read/write/edit/list/search/find/create/info.
- Reintroduced one awaited `run_command(command)` capability with Runtime-owned budget, process cleanup, sanitized environment, and bounded output; `start/check/stop` command modes remain absent.
- Made every Code Mode call durable from acceptance. Runtime waits inline for at most 100 seconds, answers by 110 seconds, and contains the Execution at a 3,590-second work cutoff plus ten seconds of cleanup. See `docs/runtime/timeouts.md`.
- Moved Task list/get/cancel/dismiss out of Monty and into the strict top-level `task` tool.

**Why**
- Ordinary file work no longer needs shell quoting or custom wrappers.
- Restores direct CLI ergonomics without restoring an unbounded or independently timed shell lane.
- Separates execution lifetime from response delivery: an inline result and a published Task refer to the same Execution.

### 6. Host filesystem boundary

Code Mode resolves relative filesystem paths from the effective `cwd` and allows host reads/writes across `/` subject to normal OS permissions, except explicitly blocked credential/secret paths. Registered Harness FileSystem capabilities share this policy. `run_command` inherits the same cwd, guard-bin precedence, denied secret environment, and outer Execution deadline. Subagents and external workers retain bounded, audited execution capabilities under standard guard policies.

### 7. Local ChatGPT Codex subscription compatibility

**Change**
- GPT Dive consumes official stable `pydantic-ai-slim` rather than carrying a downstream Pydantic fork.
- Subscription-backed Codex aliases route through the local `gpt_dive.openai_codex` compatibility package.

**Why**
- Keep upstream Pydantic upgradeable while isolating only the OAuth/provider/Responses behavior that is not yet available in the required released upstream form.
- Make the compatibility layer explicitly retireable.

Maintenance SSOT: root-level `README.patch.openai.provider.md`. It intentionally stays prominent at repository root so Pydantic upgrades do not miss the compatibility/retirement check.

### 8. Repository retrieval behind Code Mode

**Change**
- Added `repo_search`, backed by Probe BM25 ranking plus AST-aware blocks, as a bounded repository exploration capability.

**Why**
- Locate a small relevant evidence set before opening files, reducing blind recursive reads and model-context growth.
- Keep search-engine implementation replaceable behind an engine-neutral capability name.

Implementation: `src/gpt_dive/repo_search.py`.

## Current ownership boundaries

```text
Web MCP surface
  bootstrap / code_mode / task

GPT Dive runtime
  lifecycle + registry + local execution policy + provider routing

Pydantic AI Core
  Agent / model / provider / message / tool semantics

Pydantic AI Harness
  reusable capabilities such as FileSystem / Shell / RepoContext / output controls
```

GPT Dive should prefer upstream public seams and thin adapters. New local behavior is justified when it solves a GPT Dive-specific transport, lifecycle, security, provider, or integration problem that upstream does not already solve cleanly.

## Where decisions live

- Cross-Orchestra operating decisions live in `~/wiki/workflow/orchestra/`.
- GPT Dive-specific Pydantic implementation ADRs live in `docs/pydantic/adr/`.
- One-change specs and acceptance evidence remain in `plans/`.
