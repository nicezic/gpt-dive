# Tool Output Limits in GPT Dive

Date: 2026-08-14
Status: SubAgent current / Code Mode planned

## Purpose

GPT Dive uses two different output-bounding seams because SubAgents and Web-facing Code Mode have different execution architectures. The shared policy is to keep exact oversized data locally, keep model-visible context small, and avoid LLM summarization unless real use proves it necessary.

## Shared policy

| Policy | Value |
|---|---:|
| Spill threshold | 8,000 characters |
| Spill retention | 48 hours, lazy cleanup |
| Preview target | about 1,000 characters, head + tail |
| Spill failure fallback | about 4,000 characters, head + tail |
| LLM summarization | off |
| Shell output cap | 50,000 characters, separate lower-layer boundary |

The 8K threshold and 48-hour retention are GPT Dive choices. Preview/fallback values intentionally track the current Harness defaults where practical.

## SubAgent: current

Workspace-enabled SubAgents are real Pydantic `Agent` runs, so GPT Dive uses the official Harness capability directly:

```text
Agent
  ├─ FileSystem
  ├─ Shell(max_output_chars=50_000)
  ├─ RepoContext
  └─ ToolOutputLimits
       ├─ >= 8K -> Spill
       ├─ spill failure -> Truncate
       └─ LocalFileStore(cleanup_after=48h)
```

Implementation: `src/gpt_dive/subagent_worker.py::_build_tool_output_limits()`.

The Harness capability runs in `after_tool_execute`, so oversized successful tool returns are replaced with a compact preview + handle while the exact payload remains in the overflow store. `ModelRetry` and tool failures stay on the error path and are not reduced by this hook.

Current configuration was introduced by commit `56d20ee`.

## Code Mode: planned final-output seam

Web-facing GPT Dive `code_mode` is not a Pydantic `Agent` using Harness `CodeMode`; it is a direct MCP -> Monty runtime with registered host callables. Therefore the Agent-bound `ToolOutputLimits` hook cannot be attached directly without changing the architecture.

More importantly, individual Code Mode capability outputs must remain large inside Monty when needed so the program can filter, search, compare, or aggregate them before returning compact evidence.

```text
registered capabilities
        │
        ▼
     Monty run
  large local values OK
        │
        ▼
 final successful response
        │
        ├─ < 8K -> return unchanged
        │
        └─ >= 8K
              ├─ full JSON response -> local spill file
              └─ Web gets path + size + small preview
```

The planned Code Mode spill returns the **real local file path**, not an opaque handle. Spill files under `/tmp` are directly readable and writable through the broad host filesystem policy, subject to normal OS permissions and credential/secret denial. A later call can inspect the returned path with `read_file`, `search_files`, `file_info`, or Shell without a separate `read_tool_result` handle API.

The final-output adapter applies only to successful foreground completion and successful background `action='result'` retrieval. Failure diagnostics remain unchanged.

Implementation/decision record: `plans/code_mode/plan-260814-output-spill.md`.

## Why the seams stay separate

```text
SubAgent tool result
    -> Pydantic Agent hook
    -> Harness ToolOutputLimits

Code Mode intermediate result
    -> Monty keeps it locally
    -> local reduction
    -> final MCP return only
    -> thin GPT Dive spill adapter
```

Trying to apply the SubAgent hook semantics to every Code Mode capability would undermine Code Mode's context-boundary advantage. The policy values can align while the integration seams remain intentionally different.

## Documentation surfaces

- MCP `code_mode` description: only the immediate behavior/action needed by a fresh model-facing call.
- `~/wiki/workflow/pydantic-ai/code-mode.md`: only the Web SOL operating rule.
- This document: implementation architecture, rationale, and SubAgent/Code Mode distinction.
- `plans/code_mode/plan-260814-output-spill.md`: one-change decision, implementation, and acceptance history.

Do not copy the full implementation explanation into MCP or Wiki surfaces.
