# Plan: Code Mode Static Type Check

Date: 2026-08-14
Status: Implemented — local validation PASS; live reload acceptance pending

## Goal / Why

Make GPT Dive direct `code_mode` statically validate generated Monty programs against the live registered capability signatures before any capability dispatch.

The triggering failure was a contract-adherence error: live `CAPABILITIES` correctly exposed `search_files(pattern=...)`, but generated code called `search_files(query=...)`. Runtime argument validation prevented state damage, but only after execution reached the host callable. Pydantic Monty can reject this class of mistake before host dispatch.

## Current State

- `CallableRegistry.describe()` already derives model-visible signatures directly from the registered live Python callables using `inspect.signature`.
- `MontyCodeRuntime.run()` currently explicitly disables static checking with both `monty.checkout(type_check=False)` and `skip_type_check=True`.
- The installed `pydantic-monty 0.0.21` supports `checkout(type_check=True, type_check_stubs=...)`.
- A live canary using the full current 18-capability registry proved that signature-derived stubs compile valid `search_files(pattern=...)` code and reject `search_files(query=...)` with `MontyTypingError` before host dispatch.
- Upstream Pydantic AI Harness CodeMode uses the same general pattern: render callable signatures as Monty type-check stubs and type-check before execution.

## Scope

- Enable Monty static type checking by default for GPT Dive direct `code_mode`.
- Generate the checker stubs mechanically from the same registered callables that own the live `CAPABILITIES` signatures.
- Preserve parameter names, positional/keyword-only markers, defaults, annotations, async/sync shape, and return annotations from `inspect.signature`.
- Add regression coverage for the exact `search_files(query=...)` failure class and normal Code Mode behavior.

### Explicit Non-goals

- No parameter aliases or automatic `query -> pattern` correction.
- No rename/change to `search_files`, `repo_search`, or other capability contracts.
- No prompt/bootstrap expansion as the primary fix.
- No worker/model routing or tool-surface changes.
- No user-facing `type_check=False` escape hatch in this change.
- No migration to Harness `CodeModeToolset`; this patch only restores the missing deterministic validation layer in GPT Dive's existing direct Monty runtime.

## Key Decisions

### 1. Static type-check is default-on and fail-closed

- **Decision:** Every direct Code Mode program is checked before execution whenever registered capabilities are present.
- **Reason:** Model-side contract adherence is probabilistic. A deterministic checker at the program/capability boundary prevents wrong argument names and other statically provable call-shape errors from reaching host execution.
- **Rejected alternatives:** Stronger prompt warnings; retrying after runtime `TypeError`; leaving validation runtime-only.
- **Consequences / tradeoffs:** Programs Monty judges invalid will fail earlier. If a genuine checker false-positive appears, it should be investigated explicitly rather than silently rerunning unchecked.

### 2. Live registry is the single source of truth for checker stubs

- **Decision:** `CallableRegistry` renders type-check stubs from its registered callables using `inspect.signature`; do not maintain a second hand-authored signature table.
- **Reason:** The model-visible `CAPABILITIES` contract and deterministic checker must drift together or not at all.
- **Rejected alternatives:** Hard-coded `.pyi` text; manual per-capability schemas; aliases that normalize incorrect calls.
- **Consequences / tradeoffs:** A newly registered callable automatically participates in static checking. Callable signatures must therefore remain valid Python signature material, which is already required by `CAPABILITIES` discovery.

### 3. Preserve runtime validation as a backstop

- **Decision:** Static checking is additive. Existing Python/Harness runtime validation and exceptions remain unchanged.
- **Reason:** Static checking cannot prove every dynamic value/path. Runtime validation still owns dynamic failures.
- **Rejected alternatives:** Treating static checking as sufficient validation and weakening runtime guards.
- **Consequences / tradeoffs:** There are intentionally two layers: pre-dispatch static validation and execution-time validation.

## Implementation Direction

- Add a small `CallableRegistry` method that renders Monty type-check stubs from the current registered callables.
- Include the minimal typing import needed by current annotations and emit `async def` or `def` according to the actual callable.
- In `MontyCodeRuntime.run()`, create the stubs once per run and pass them to `AsyncMonty.checkout(type_check=True, type_check_stubs=...)`.
- Call `feed_start(..., skip_type_check=False)` so the program is checked before execution.
- Do not catch and downgrade `MontyTypingError` into unchecked execution. Preserve the diagnostic.

## Failure Policy

- A static type error fails the Code Mode call before capability dispatch.
- Do not automatically rewrite bad arguments, retry unchecked, or fall back to another execution path.
- Dynamic/runtime failures continue to surface through the existing exception behavior.
- If type checking breaks previously valid Code Mode patterns, treat that as an acceptance failure and diagnose the specific incompatibility before widening scope.

## Test Contract

At minimum prove:

1. Given live `search_files(pattern, *, path, include_glob)`, when Code Mode receives `search_files(query=...)`, then it raises `MontyTypingError` naming both the missing `pattern` and unknown `query` before host dispatch.
2. A representative valid capability call still executes normally with type checking enabled.
3. Existing patterns using `CAPABILITIES`, `INPUT`, `asyncio.gather`, FileSystem, Shell, `repo_search`, `subagent_call`, `bare`, and background Code Mode remain regression-green through the existing test suite.
4. Type-check stubs are derived from the registry rather than a duplicated static signature list.

## Acceptance / Validation

- Targeted `tests/test_code_runtime.py` PASS.
- Full GPT Dive pytest suite PASS.
- Ruff check/format PASS for touched files.
- `git diff --check` PASS.
- Inspect the final diff and preserve unrelated dirty worktree files.
- After implementation is loaded by the active MCP service, live canary `search_files(query=...)` must fail at static type-check rather than host runtime dispatch.

## Result

Implementation is complete and local validation passes.

- `CallableRegistry.type_check_stubs()` now renders runtime globals plus every registered callable directly from the live Python signature. No parallel hand-authored capability schema was added.
- `MontyCodeRuntime.run()` now uses `checkout(type_check=True, type_check_stubs=...)` and `skip_type_check=False`; there is no unchecked fallback.
- `CWD` and `CAPABILITIES` are declared to the checker on every run. `INPUT` is declared only when the outer `code_mode(input=...)` payload exists, preserving the existing runtime contract.
- Added a regression test for the triggering failure: `search_files(query='M3', ...)` raises `MontyTypingError` with both missing `pattern` and unknown `query` diagnostics before host dispatch.
- Initial targeted validation exposed one compatibility gap: Monty type checking does not infer `feed_start(inputs=...)` names automatically. The implementation was corrected by adding the runtime-injected globals to the generated type stubs rather than disabling checking or adding a fallback.

Validation:

- `uv run pytest -q tests/test_code_runtime.py` -> **35 passed**.
- `uv run pytest -q` -> **88 passed**.
- `uv run ruff check src/gpt_dive/code_runtime.py tests/test_code_runtime.py` -> PASS.
- `uv run ruff format --check src/gpt_dive/code_runtime.py tests/test_code_runtime.py` -> PASS.
- `git diff --check` -> PASS.
- Final diff inspection shows only the intended runtime/test changes for this patch; pre-existing dirty docs and the separate output-spill plan remain untouched.

Live acceptance remains pending until the active MCP service reloads the edited source. Per `docs/runtime/operations.md`, reload must be detached from the initiating MCP response; no inline post-restart round-trip should be attempted.
