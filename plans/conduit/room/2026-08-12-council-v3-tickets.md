# Council v3 — Implementation Tickets

> Parent spec: `docs/conduit/room/spec.md`
> Status: COMPLETE — T1/T2/T3/T4 PASS
> Created: 2026-08-12

## T1 — Council Repo Protocol

### Purpose / Reason
Build the Git-backed Council protocol that both participant turn flows depend on.

### Blocked by
None.

### Exact Boundary
Own Council repository initialization, append-only USER/SOL/OPUS turn commits, participant context refs, snapshot-based unread suffix extraction, and protocol validation. Keep this logic under `gpt_dive.conduit.room` and preserve `council_emit` compatibility. Do not implement browser transport, Pydantic Opus calls, or Web UI.

### Implementation Guidance
Promote the current experimental `council.py` seam into a small package if useful. Git is the synchronization SSOT. `chat.md` remains human-readable and append-only. Use `refs/council/context/sol` and `refs/council/context/opus` as participant cursors. Cursor movement is explicit and occurs only after the participant response commit succeeds.

### Failure Policy
Fail visibly on Git errors, missing Council files/refs, invalid roles, empty messages, or non-append transcript mutation. Never guess/reconstruct protocol state and never advance a cursor on a failed append/commit.

### Required Tests / Test Contract
- New Council starts with both participant refs at the initial commit.
- Each USER/SOL/OPUS speaking event appends exactly one transcript block and creates exactly one commit.
- Snapshot-delta extraction returns only the pure chronological appended transcript suffix.
- Non-append transcript mutation is rejected.
- Participant cursor moves only when explicitly advanced to a successful response commit.
- Existing `council_emit` registry behavior remains compatible.

### Forbidden Extras
No database, queue, autonomous retry, transcript metadata, generalized event framework, browser code, provider code, or unrelated refactor.

### Done Condition / Result Format
Targeted Council tests pass; existing suite remains green for touched behavior; diff is limited to Council protocol seams and required imports/tests.

### Result — PASS
Implemented in `e4713ec` (`feat: implement Council repo protocol`). Final suite remains green at 60 passed.

---

## T2 — To OPUS End-to-End Turn

### Purpose / Reason
Deliver one complete USER → OPUS → Git response turn using the existing Pydantic AI path and T1 protocol.

### Blocked by
T1.

### Exact Boundary
Own OPUS unread-context construction, Pydantic model invocation, OPUS response commit, and `context/opus` advancement. Do not touch SOL browser transport or build the final UI.

### Implementation Guidance
Use the shared-room chronological suffix from T1. Preserve independent-peer role guidance. Git cursor remains synchronization authority even if the internal Pydantic history implementation changes.

### Failure Policy
Provider/model failure leaves the committed USER turn intact and `context/opus` unchanged. Surface the failure for safe retry; no hidden fallback model unless separately approved.

### Required Tests / Test Contract
- OPUS receives exactly its unread shared-room transcript in chronological order.
- One successful response creates exactly one OPUS commit and advances only `context/opus`.
- Provider failure creates no OPUS response commit and does not move the cursor.
- Intervening SOL/USER turns are included on OPUS's next turn.

### Forbidden Extras
No browser automation, autonomous debate loop, automatic retries, context summarization, or provider-routing redesign.

### Done Condition / Result Format
Targeted tests plus a real provider E2E pass with commit/cursor evidence.

### Result — PASS
Implemented in `3423723` with retry correction in `79484ad`. Real `opus5` provider E2E created one OPUS response commit and advanced only `context/opus`; failure/retry preserves the original USER commit.

---

## T3 — To SOL End-to-End Turn

### Purpose / Reason
Deliver one complete USER → Web SOL → MCP → Git response turn using the proven asymmetric transport.

### Blocked by
T1.

### Exact Boundary
Own SOL unread-context construction, persistent Playwright/Edge CDP input adapter, Web SOL target resolution, completion via `council_emit`, and `context/sol` advancement. Do not scrape assistant output and do not build the final UI.

### Implementation Guidance
Reuse the already-proven persistent CDP approach. Playwright remains input-only. A successful SOL response Git commit is the local completion event. Council bridge lifetime must not silently inherit the generic 600-second job lifetime.

### Failure Policy
Bridge/target/generation failure leaves `context/sol` unchanged. Surface a clear error. Never fall back to DOM output scraping, Copy-button extraction, clipboard capture, or streaming-completion detection.

### Required Tests / Test Contract
- Only SOL's unread chronological Council suffix is delivered.
- Real Web SOL emits through MCP and creates exactly one SOL response commit.
- `context/sol` advances only after that successful response commit.
- Intervening OPUS/USER turns are delivered in order.
- Browser output scraping is not used.

### Forbidden Extras
No generalized browser automation framework, DOM output parser, autonomous retries/debate loop, or unrelated MCP-surface expansion.

### Done Condition / Result Format
Targeted tests plus real Web SOL E2E pass with Git commit/cursor evidence.

### Result — PASS
Implemented in `d4aa608`. Final integrated Web SOL acceptance used input-only persistent Edge/CDP, `council_emit(expected_head=...)`, one SOL Git commit, and `context/sol` advancement with no DOM assistant-output scraping.

---

## T4 — Shared Room UI Integration

### Purpose / Reason
Expose the working T2/T3 participant flows as one minimal local Council room.

### Blocked by
T2 and T3 for backend integration. A mock-only UI shell may be developed earlier in isolation under `web/`.

### Exact Boundary
Own top-level `web/` Svelte 5 + Vite + TypeScript UI, minimal Python↔frontend integration seam, transcript rendering, composer, `To SOL`, `To OPUS`, turn/status/error feedback, and final integrated acceptance. Do not redesign the Council protocol.

### Implementation Guidance
Keep the first UI intentionally small. The ChatGPT Web SOL tab is a background participant runtime. Choose the smallest local Python↔Svelte transport that fits the existing runtime; WebSocket is not required unless evidence demands it.

### Failure Policy
Display participant/bridge/provider failures clearly and allow only safe retry semantics already guaranteed by unchanged Git cursors. Do not invent client-side recovery state that conflicts with Git.

### Required Tests / Test Contract
- One visible chronological room updates from Git-backed events.
- User can alternate `To SOL` and `To OPUS` without directly operating the ChatGPT tab.
- Frontend type/build check passes.
- Integrated repo protocol, real SOL E2E, real OPUS E2E, and shared-room UI E2E pass.

### Forbidden Extras
No SvelteKit, second Node backend, auth system, multi-user collaboration, multiple rooms, rich history browser, automatic summarization, or speculative UI framework abstractions.

### Done Condition / Result Format
Minimal Council room works end to end and the parent spec acceptance matrix is green; update the spec Result and continuation docs only with verified delivered behavior.

### Result — PASS
Integrated in `80ac9fe`. Starlette/Uvicorn REST serves the Svelte room, real `To OPUS` API and Svelte-button E2Es pass, and final `To SOL` full-path acceptance returned through Git. Frontend check/build and the parent acceptance matrix are green.

