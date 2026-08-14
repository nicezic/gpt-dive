# Code Mode Final Output Spill

Date: 2026-08-14
Status: Planned

## Goal / Why

Protect ChatGPT Web context from an unexpectedly large **final** `code_mode` return without weakening the main advantage of Code Mode: large intermediate tool results stay inside Monty where they can be filtered, searched, compared, and aggregated before Web SOL sees them.

The safety net is intentionally simple. When a successful final Code Mode response is still oversized after local processing, write the full response to a local file and return only a compact preview plus the real file path. Web SOL can use the existing local file/shell capabilities on a later call to inspect only the required slice.

## Current State

- Foreground `code_mode` returns `code_runtime.run(...)` directly from `src/gpt_dive/app.py`.
- `MontyCodeRuntime.run()` returns a dict containing `result` and optional captured `stdout`; there is currently no final-response size limit at this boundary.
- Background Code Mode uses the same runtime in `code_mode_worker.py`; `action='result'` later returns the worker envelope through `_background_code_mode_result()`.
- Internal Code Mode capabilities are deliberately available to Monty before the final MCP return. This is the context-saving boundary: large `read_file`, search, shell, or other capability results can be reduced locally before only a compact result is returned.
- Harness Shell already has its separate `50_000` character output cap. That protects shell execution output and is not the same layer as this final Code Mode response policy.
- SubAgent workers now use Harness `ToolOutputLimits` with an 8,000-character spill threshold and 48-hour spill TTL (`56d20ee`). Code Mode cannot attach that Agent hook directly because its Web-facing runtime is a direct Monty/MCP path rather than a Pydantic `Agent` tool execution path.

## Scope

- Add one final-output safety boundary for successful Code Mode responses.
- Use **8,000 characters** as the spill threshold.
- Persist the complete oversized response under a dedicated Code Mode spill directory in `/tmp`.
- Use a **48-hour lazy TTL**: stale spill files are pruned on later spill writes, matching Harness `LocalFileStore(cleanup_after=...)` semantics.
- Return the actual local file path, total size, and a bounded head/tail preview instead of inventing a handle abstraction.
- Add the dedicated Code Mode spill directory as a read-only trusted FileSystem root so a later Code Mode call can use `read_file`, `search_files`, `file_info`, etc. directly on the returned path; do not grant write authority through that trusted-root route.
- Apply the same final-output policy to foreground completion and successful background `action='result'` retrieval.
- Keep failure/error diagnostics on their existing path rather than spilling or truncating them in this feature.
- Update the MCP `code_mode` description with one compact model-facing sentence describing the >=8K spill behavior and read-back path.
- Add only 1-2 operating sentences to `~/wiki/workflow/pydantic-ai/code-mode.md`; keep implementation detail in `docs/pydantic/tool-output-limits.md`.
- Keep the shared SubAgent/Code Mode output policy documented together in `docs/pydantic/tool-output-limits.md`, while preserving their intentionally different integration seams.

## Explicit Non-goals

- Do not apply the 8K boundary to individual capabilities inside Monty. Internal large results must remain available for local filtering and aggregation.
- Do not add `read_tool_result`, handle-to-path mapping, a new query API, or another storage backend abstraction.
- Do not add M3 or any LLM summarization.
- Do not change Harness Shell's existing 50K output cap.
- Do not change SubAgent `ToolOutputLimits`; its Agent integration remains separate.
- Do not add compaction or rewrite prior model history.
- Do not create tickets; this is a small sequential change.

## Key Decisions

### 1. Limit only the final MCP-visible Code Mode response

- **Decision:** Measure and spill only after Monty has completed the program and produced the successful response that would otherwise be returned to ChatGPT Web.
- **Reason:** Code Mode earns its value by keeping large intermediate data local. Limiting `read_file`, `search_files`, `run_command`, or other registered capability returns at 8K would force Monty to lose or re-fetch data before it has a chance to reduce it.
- **Rejected alternatives:** Wrap every registered capability with an 8K spill limiter; attach Harness `ToolOutputLimits` to the direct Monty path.
- **Consequences / tradeoffs:** A very large intermediate value can still consume local memory during one Code Mode run, but it does not automatically pollute persistent Web model context. The safety boundary protects the Web return, not Monty's local working set.

### 2. Return a real file path instead of a spill handle

- **Decision:** An oversized successful response is persisted to a deterministic local file and the compact response exposes that exact path.
- **Reason:** GPT Dive is a user-owned local WSL2 runtime. Web SOL already has local filesystem/shell access on later calls, so a handle resolver and `read_tool_result()` API would duplicate capabilities without buying useful portability here.
- **Rejected alternatives:** Harness-style opaque handle plus a new read-back capability; exposing both handle and path.
- **Consequences / tradeoffs:** The contract is intentionally local-machine-specific. The dedicated spill directory must also be exposed as a read-only trusted FileSystem root so the returned absolute path is directly useful to `read_file`/`search_files`; this must not expand write authority. If Code Mode later gains a remote/distributed storage backend, this decision may need supersession rather than pretending the path is portable.

### 3. Reuse Harness `LocalFileStore` lifecycle semantics where practical

- **Decision:** Use a dedicated explicit `LocalFileStore(base_dir=..., cleanup_after=timedelta(hours=48))` for persistence/cleanup, while the Code Mode adapter owns threshold measurement and preview formatting.
- **Reason:** The public store already provides safe path handling, owner-only root creation, and non-blocking age-based cleanup. Reusing it avoids writing a second TTL sweeper merely because Code Mode does not use the Agent hook.
- **Rejected alternatives:** Custom file store and cleanup implementation; no TTL because the root is under `/tmp`.
- **Consequences / tradeoffs:** Cleanup is lazy, not an exact 48-hour timer. A stale file can remain beyond 48 hours until another spill write occurs or WSL clears `/tmp`.

### 4. Keep the policy aligned with the SubAgent defaults chosen for GPT Dive

- **Decision:** Final Code Mode spill threshold is 8,000 characters and retention is 48 hours. Preview stays small (target about 1,000 characters head+tail). No LLM summarization.
- **Reason:** These values already reflect the user-approved context policy: spill before a roughly 2K-token tool payload becomes persistent baggage, retain the exact source long enough for follow-up work, and prefer lossless local read-back over lossy summaries.
- **Rejected alternatives:** Harness default 10K threshold; M3 summarization; indefinite retention.
- **Consequences / tradeoffs:** Outputs in the 8K-10K range will spill more often, but the full data remains locally available.

### 5. Preserve failure diagnostics

- **Decision:** This feature only transforms successful oversized Code Mode results. Existing exceptions, worker protocol failures, timeout errors, and unsuccessful background envelopes remain unchanged.
- **Reason:** Recovery depends on concrete error details. An output limiter that hides diagnostics can turn a recoverable failure into a convincing but opaque one.
- **Rejected alternatives:** Apply the same 8K spill/truncate rule indiscriminately to every return path.
- **Consequences / tradeoffs:** A pathological error can still be large. If failure-output bounding becomes a demonstrated problem, it should be designed separately with recovery semantics explicitly preserved.

### 6. Duplicate only the small operating contract across MCP + Wiki

- **Decision:** Put the immediate spill/read-back behavior in both the MCP `code_mode` description and the Web SOL workflow, but keep each to 1-2 sentences. Keep architecture and maintenance detail only in `docs/pydantic/tool-output-limits.md`.
- **Reason:** MCP descriptions are visible exactly when the model chooses/calls the tool, while the Wiki is durable fresh-session operating memory. Both need the behavior, but duplicating the full design would create drift and prompt bloat.
- **Rejected alternatives:** MCP-only documentation; Wiki-only documentation; copying the full implementation explanation into both.
- **Consequences / tradeoffs:** One tiny factual duplication is intentional. Any threshold/path-contract change must update both short surfaces plus the developer SSOT in the same change.

## Implementation Direction

Introduce a small shared Code Mode final-output adapter rather than changing the registry callables.

Conceptual flow:

```text
registered capabilities
        │
        ▼
     Monty run
  large data allowed
        │
        ▼
 successful response
        │
        ├─ < 8K ────────────────► return unchanged
        │
        └─ >= 8K
              │
              ▼
       /tmp/... spill file
         full response
              │
              ▼
       compact MCP response
       - spilled: true
       - chars: N
       - path: /tmp/...
       - preview: head + tail
```

Implementation should provide one helper that both foreground completion and successful background result retrieval can call. Keep the storage root dedicated to Code Mode, for example `/tmp/gpt-dive-code-mode-spill/`, so returned paths are obvious and cleanup is scoped. Register that exact directory as an additional read-only trusted FileSystem root in the Code Mode registry; `read_file`, `list_directory`, `search_files`, `find_files`, and `file_info` may route there, while `write_file`, `edit_file`, and `create_directory` remain workspace-only.

Measure the serialized model-visible successful response, not each internal capability result. The spill file should preserve enough structure to reconstruct the original response; JSON is preferred for the current dict-shaped Code Mode envelope, encoded as UTF-8. The compact replacement must state that the full result is stored at the returned path and can be inspected with existing Code Mode file/shell operations.

Do not depend on Harness private helpers such as `_head_tail_preview` or private store internals. A tiny local head/tail preview formatter is acceptable; persistence should use the public `LocalFileStore` API with an explicit base directory.

If persistence itself fails on a successful oversized result, retain a bounded local fallback rather than silently dropping the result. A compact explicit marker plus roughly 4,000 characters of head/tail content is sufficient. Storage failure must be visible in the replacement so Web SOL knows the full result is unavailable.

## Documentation / Model-facing Contract

The runtime behavior and documentation land together. Do not publish these as current behavior before the implementation exists.

**MCP `code_mode` description, target wording (one compact sentence):**

> Successful final Code Mode responses at or above 8,000 characters are spilled to a local file; the compact response includes the file path and preview, so inspect that path on a later Code Mode call instead of re-running or returning the whole payload.

**`~/wiki/workflow/pydantic-ai/code-mode.md`, target operating wording (1-2 sentences):**

> Successful final Code Mode output >=8K is automatically spilled to a local file; Web SOL receives only a compact preview plus the exact path. Read or search that file on a later Code Mode call when more detail is needed rather than pulling the whole payload back into context.

**Developer SSOT:** `docs/pydantic/tool-output-limits.md` owns the detailed distinction:

```text
SubAgent
  Pydantic Agent -> Harness ToolOutputLimits
  8K spill / 48h TTL

Code Mode
  large intermediate values stay inside Monty
  final successful MCP response only -> file spill
  8K spill / 48h TTL
```

`docs/pydantic/code-mode.md` should link to that SSOT rather than duplicate the full mechanics.

## Failure Policy

- Successful response under 8K: unchanged.
- Successful response at/over 8K and store write succeeds: full response stored; compact path + size + preview returned.
- Successful response at/over 8K and store write fails: return an explicit spill-failed marker plus bounded head/tail fallback; do not pretend the original is recoverable.
- Code Mode exception, timeout, worker protocol failure, or unsuccessful background result: preserve existing diagnostic behavior unchanged.
- Cleanup failure: warn/best-effort only through `LocalFileStore`; never fail an otherwise successful Code Mode run.

## Test Contract

### 1. Small foreground result passes through

- **Given:** a successful Code Mode response whose serialized model-visible size is below 8,000 characters.
- **When:** foreground `code_mode` completes.
- **Then:** the response is unchanged and no spill file is created.

### 2. Large foreground result spills to a readable file

- **Given:** a successful response above 8,000 characters with distinctive content beyond the preview.
- **When:** foreground `code_mode` completes.
- **Then:** Web-visible output is compact, includes the exact spill file path and total size, the file contains the complete original response, and the distinctive hidden content can be recovered from that path with Code Mode `read_file`/`search_files` without granting spill-root write access.

### 3. Large intermediate data can still be reduced locally without spilling

- **Given:** a capability returns well over 8K inside Monty.
- **When:** the Monty program locally extracts a small subset and returns that subset.
- **Then:** the final Code Mode response remains small and no spill occurs. This proves the limiter is at the correct boundary.

### 4. Successful background result uses the same policy

- **Given:** a background Code Mode job completes successfully with a result above 8K.
- **When:** `action='result'` retrieves it.
- **Then:** the same compact path + preview response is returned and the full result is readable from the spill file.

### 5. Failure diagnostics are not transformed

- **Given:** a foreground failure and a background unsuccessful/error envelope.
- **When:** those paths are returned/raised.
- **Then:** the existing diagnostic shape/content is preserved and no success spill marker replaces it.

### 6. Retention policy is configured

- **Given:** the Code Mode spill store.
- **Then:** it has an explicit 48-hour cleanup policy and a dedicated `/tmp` base directory. A focused store test may verify stale-file pruning behavior through the public store semantics without duplicating upstream Harness tests.

### 7. Spill path is readable but not writable through trusted-root routing

- **Given:** a spilled Code Mode response path under the dedicated spill directory.
- **When:** a later Code Mode run uses FileSystem capabilities against that absolute path.
- **Then:** `read_file`/`search_files`/`file_info` can inspect it, while workspace-scoped write/edit/create capabilities do not gain authority over the spill root.

## Acceptance / Validation

Minimum acceptance before implementation is considered complete:

```text
Targeted Code Mode tests                  PASS
Foreground >8K spill/read-back           PASS
Large internal → small final result       PASS
Background >8K result spill/read-back     PASS
Spill path read-only FileSystem access     PASS
Failure diagnostic preservation           PASS
MCP description advertises spill path     PASS
Wiki workflow has compact operating rule  PASS
Developer SSOT matches runtime policy      PASS
Ruff                                      PASS
git diff --check                          PASS
```

Run the broader GPT Dive test suite if the shared return boundary touches common MCP/background plumbing beyond the focused helper.

A live fresh-session acceptance is useful after any MCP server reload only if server-side `app.py` code changed and the active process has not already loaded the new implementation. Do not restart merely because the spec exists.

## Result

Pending implementation.
