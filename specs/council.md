# Council — Shared Multi-Model Discussion Workspace

> Status: Implemented / Council v1 FULL PASS
> Created: 2026-08-12
> Scope: GPT Dive generation 3

## Goal / Why

Council turns the user's already-successful manual USER ↔ SOL ↔ OPUS copy/paste workflow into a small local discussion workspace.

The manual workflow already proves the reasoning pattern: SOL and Opus can see each other's arguments, disagree materially, refine each other's reasoning, and change position when evidence warrants it. The user supplies real-world context, chooses who speaks next, and remains the final decision owner.

The pain is **transport**, not judgment.

Council therefore automates message transport and durable context while preserving the human-controlled discussion loop.

Core invariant:

> **Automate transport, not judgment.**

A second invariant follows from the first Council experiments:

> **Preserve Why.** A conclusion without the reasoning, constraints, rejected alternatives, and disagreement that produced it is incomplete context.

## Current State

GPT Dive v1-v2 is stable:

- four Web-facing MCP tools: `bootstrap`, `code_mode`, `wsl2_sync`, `wsl2_async`;
- `code_mode` is the primary programmable Pydantic Monty-backed harness;
- durable executions reuse `ExecutionManager`;
- `subagent_call` and `gz64` are registered capabilities behind Code Mode;
- current local suite: 39 tests passing before this spec.

A Council Web SOL transport probe already exists:

```text
local input
  -> persistent Playwright / Edge CDP
  -> existing ChatGPT Web SOL conversation
  -> code_mode -> council_emit
  -> chat.md
  -> Git commit
```

The probe passed end-to-end. Playwright input delivery works, `council_emit` records a SOL response as one Git event, and a persistent CDP connection avoids repeated Edge approval prompts.

The probe is evidence, not the final Council runtime.

## Mental Model

Council is one shared discussion room, not two private AI lanes.

```text
USER = moderator / domain owner
SOL  = primary engineer
OPUS = independent peer

USER / SOL / OPUS
       -> one chronological Council conversation
```

The user decides who speaks next through the Council UI.

Participants share the conversation context. Independence means **independent judgment**, not hidden context:

- seeing another participant's argument does not imply agreement;
- material disagreement should be explicit;
- participants should challenge assumptions when warranted;
- participants may update their position when evidence changes;
- important rationale and disagreement must not be erased merely to create consensus.

For rare fresh-eye reviews, an Independent Challenge mode may later hide prior AI discussion. It is not part of the default v1 Council flow.

## Scope

### In scope

- a local Council Web UI;
- USER input with two explicit turn targets: `To SOL` and `To OPUS`;
- one append-only shared transcript;
- Git-backed event history and participant context cursors;
- Web SOL input through the existing ChatGPT Web conversation;
- Web SOL output through GPT Dive MCP, not browser scraping;
- Opus input/output through the local Pydantic AI harness;
- enough status/error state in the UI to make turn progress understandable;
- Svelte 5 + Vite + TypeScript frontend;
- Python Council backend inside GPT Dive.

### Explicit non-goals

- autonomous SOL ↔ OPUS debate loops;
- automatic convergence or consensus detection;
- browser scraping of SOL output;
- Copy-button or clipboard extraction;
- DOM streaming-completion detection;
- private per-model conversation lanes as the default architecture;
- routing metadata embedded in `chat.md`;
- parsing the most recent `# SOL` / `# OPUS` heading as transport state;
- premature conversation summarization or compression;
- SvelteKit or a second Node backend;
- production-grade multi-user authentication;
- generalized browser automation beyond the narrow SOL input adapter.

## Key Decisions

### 1. Shared Room, not private lanes

**Decision**

USER, SOL, and OPUS share one chronological Council transcript.

**Reason**

This matches the successful manual workflow and allows participants to build on or challenge each other's reasoning directly. The important property is judgment independence, not information isolation.

**Rejected alternative**

Separate private SOL/OPUS lanes with explicit human relay.

**Why rejected**

It adds addressing, relay, synchronization, and visibility semantics that do not solve a demonstrated problem and make the experience less like the real Council workflow.

**Consequence**

The default context includes prior participant reasoning. Rare independent audits may later use a special mode.

### 2. Git-backed Council repository

**Decision**

Each Council uses a small Git repository:

```text
init.md
chat.md
.git/
```

`init.md` carries the current Why / background / problem / constraints needed to understand the room.

`chat.md` is the append-only human-readable chronological transcript:

```markdown
# USER

...

---

# SOL

...

---

# OPUS

...

---
```

One speaking event becomes one Git commit.

**Reason**

Git already provides an atomic, durable, timestamped event timeline and makes the complete reasoning history inspectable without another database.

**Rejected alternatives**

- database-first transcript state;
- structured routing metadata inside Markdown;
- mutable conversation files without event commits.

**Consequence**

`chat.md` stays intentionally dumb; protocol state lives in Git.

**Implementation choice**

Council intentionally uses the official `git` CLI through a narrow Python subprocess seam rather than adding GitPython, pygit2/libgit2, or Dulwich. The v1 protocol depends on a small set of Git plumbing operations (`commit`, `rev-parse`, `show`, `merge-base --is-ancestor`, `update-ref`), so direct Git CLI usage keeps Git semantics authoritative and avoids an extra abstraction/dependency without a demonstrated benefit. Revisit only if deployment without a Git executable or substantially heavier embedded Git workloads become real requirements.

### 3. Explicit Git refs are participant context cursors

**Decision**

Use:

```text
refs/council/context/sol
refs/council/context/opus
```

Each ref means: **this participant's model/native conversation context is synchronized through this Council commit**.

Both refs start at the initial Council commit.

**Reason**

Transport state should not be inferred by parsing transcript content. A participant may have received several other turns since its own last visible reply, so “last speaker block” and “known context” are conceptually different states.

**Rejected alternative**

Search `chat.md` for the most recent `# SOL` or `# OPUS` block.

**Consequence**

Context position remains format-independent and can later evolve without changing the human transcript format.

### 4. Unread context is derived from Git snapshots, not patch text

**Decision**

A participant's unread Council input is determined by its context ref and current HEAD, but the model receives the **pure appended transcript suffix**, not raw `git diff` patch syntax.

Conceptually:

```text
old = chat.md at participant context ref
current = chat.md at target HEAD
require current starts with old
unread = current suffix after old
```

**Reason**

Git determines *where* context starts; `chat.md` determines *what* was said. This also directly enforces the append-only transcript invariant.

**Failure behavior**

If the current transcript is not an append-only extension of the snapshot at the cursor, fail visibly instead of guessing or silently reconstructing context.

### 5. Cursor advances only after a successful participant response commit

**Decision**

Do not move a participant context ref when the user merely presses `To SOL` or `To OPUS`.

Successful flow:

```text
USER turn commit
  -> build unread context
  -> deliver to participant
  -> participant produces response
  -> response commit
  -> move that participant's context ref to the response commit
```

**Reason**

Delivery or generation can fail. Moving the cursor early could mark context as synchronized when the participant never successfully processed it.

**Consequence**

A failed turn leaves the cursor unchanged, so the same unread context remains available for retry/recovery.

### 6. Web SOL uses asymmetric transport

**Decision**

SOL input and output use different paths:

```text
Input:  Council backend -> playwright-cli -> Playwright Extension -> existing ChatGPT Web SOL composer
Output: Web SOL -> GPT Dive MCP -> Council Git repo
```

The current input adapter reuses the named `msedge` CLI session when available and otherwise attaches through the official Playwright Extension + stored token. Before insertion it requires the exact target tab's composer to be READY: visible, editable, empty, and without the visible ChatGPT stop button. After Enter it verifies that the composer accepted and cleared the message. This readiness gate protects repeated sends; it is not the SOL response-completion signal.

Playwright is **input-only**.

**Reason**

The actual SOL exists in ChatGPT Web and cannot be recreated inside the local Pydantic runtime. MCP already provides a clean explicit output path, so DOM response extraction is unnecessary and brittle.

**Rejected alternatives**

- scraping assistant DOM output;
- detecting streaming completion from browser UI;
- Copy-response/clipboard extraction.

**Consequence**

A successful SOL response Git commit is the local completion event for the turn.

### 7. SOL receives only Council context it lacks

**Decision**

The existing ChatGPT Web conversation remains SOL's native history. On `To SOL`, Council sends the chronological transcript suffix since `refs/council/context/sol`, including any USER and OPUS turns SOL has not yet received.

**Reason**

Logical Council context is the full conversation, but repeatedly transmitting the full conversation is unnecessary when Web SOL already has its own prior delivered history.

**Consequence**

Logical context and physical transport are separate concerns. The protocol preserves full shared context without duplicating all previous tokens every turn.

### 8. Opus is a first-class shared-room participant through Pydantic AI

**Decision**

`To OPUS` uses GPT Dive's local Pydantic AI path rather than browser automation.

The input must preserve the same shared-room timeline semantics as SOL. Its context cursor is `refs/council/context/opus`.

**Reason**

Opus is already available through the local AI harness, so no browser adapter is necessary.

**Consequence**

SOL and OPUS have different transport adapters but converge on the same Git-backed transcript and context model.

The exact internal Pydantic history/cache optimization is an implementation detail as long as externally the participant receives all Council context it has not yet incorporated and the Git cursor remains authoritative for synchronization.

### 9. Preserve Why and raw conversation before optimizing context

**Decision**

Early Council v1 does not summarize or compress the shared transcript automatically.

**Reason**

The first Design Council showed that missing causal context changes review quality. Summaries disproportionately lose why a proposal existed, which alternatives were rejected, and what evidence changed a participant's position.

**Consequence**

If long Council sessions later create a demonstrated context-size problem, compression must preserve reasoning lineage rather than only final decisions.

### 10. Council Web UI uses Svelte 5 + Vite + TypeScript

**Decision**

Place the frontend in a top-level `web/` project using Svelte 5, Vite, and TypeScript. Do not use SvelteKit initially.

**Reason**

Svelte 5 offers an unusually AI-friendly modern coding surface, fast development with little boilerplate, and a lightweight runtime. GPT Dive already owns the backend, so another server framework is unnecessary.

**Rejected alternatives**

React, SolidJS, Preact, SvelteKit.

**Consequence**

Python runtime and frontend build stay cleanly separated.

## UI Turn Semantics

After Council starts, the user should be able to remain on the GPT Dive Council page. The existing ChatGPT Web SOL tab is a background participant runtime rather than the primary user interface.

### `To SOL`

```text
1. USER enters message in Council UI
2. append # USER block to chat.md
3. commit USER turn
4. build SOL unread transcript from context/sol -> current commit
5. send unread transcript through `SolBridge` using the Playwright Extension after the composer READY gate
6. Web SOL reasons in its existing ChatGPT conversation
7. SOL emits response through MCP Council capability
8. append # SOL block and commit
9. move context/sol to the SOL response commit
10. UI displays the new SOL turn
```

The payload sent to SOL is the unread Council conversation, not merely the latest USER message. If USER and OPUS discussed several turns since SOL last participated, those turns must be delivered in chronological order.

### `To OPUS`

```text
1. USER enters message in Council UI
2. append # USER block and commit
3. build OPUS unread transcript from context/opus -> current commit
4. invoke Opus through Pydantic AI
5. append # OPUS block and commit
6. move context/opus to the OPUS response commit
7. UI displays the new OPUS turn
```

## Participant Role Guidance

Shared participant behavior should remain compact.

Common intent:

> Read the shared Council conversation and preserve independent judgment. Do not follow another participant merely because their view appeared earlier. Challenge reasoning when warranted, update your position when evidence warrants it, and preserve the why behind proposals, disagreements, and decisions.

SOL additionally acts as the primary engineer responsible for integrating discussion into a coherent technical direction without erasing material dissent.

OPUS acts as an independent peer, not a subordinate reviewer.

## Implementation Direction

### Python

Promote the experimental `src/gpt_dive/council.py` seam into a small Council package when implementation begins:

```text
src/gpt_dive/council/
├── __init__.py
├── repo.py        # Council init/append/commit/ref/snapshot-delta
├── sol.py         # SOL transport orchestration
├── opus.py        # Pydantic Opus adapter
└── bridge.py      # Council-scoped persistent Edge/CDP adapter
```

Exact file splitting may stay small and should follow implementation pressure; the important boundary is Council logic under `gpt_dive.council` rather than adding new top-level MCP tools.

The existing `council_emit` capability should evolve behind `code_mode` rather than becoming a fifth Web-facing MCP tool.

### Web

```text
web/
├── package.json
├── vite.config.ts
├── tsconfig.json
└── src/
```

Initial UI needs only the minimum Council room:

- current transcript;
- composer;
- `To SOL` and `To OPUS` actions;
- participant/turn status;
- clear failure state and retry affordance where safe.

Do not design a full collaboration product before the two participant flows work end to end.

### Browser bridge

The SOL adapter should keep one CDP connection persistent for the active Council rather than reconnecting for every turn. The first experiment proved that repeated CDP attachments trigger repeated Edge approval friction.

The bridge must not inherit the generic 600-second async timeout as its effective Council lifetime. Exact supervision/start/stop mechanics are implementation details, but its lifecycle must correspond to the active Council rather than silently expiring after ten minutes.

## Failure Policy

Keep failure handling explicit and small.

### Transcript / Git failure

- Do not advance context refs if append/commit fails.
- Treat non-append transcript mutation as a protocol violation.
- Surface the failure; do not silently repair or rewrite history.

### SOL input failure

- If the browser bridge is unavailable or the target ChatGPT conversation cannot be resolved, do not move `context/sol`.
- Surface a clear bridge/target error in the Council UI.
- Do not fall back to output scraping or alternate hidden browser automation.

### SOL generation/output failure

- No SOL response commit means the SOL cursor does not advance.
- The unread context remains recoverable from Git for a later retry.

### OPUS failure

- Provider/model failure does not advance `context/opus`.
- Preserve the committed USER turn and allow a later retry from the same context position.

### No speculative resilience in v1

Do not add distributed queues, autonomous retries, workflow engines, browser lifecycle managers, or background debate schedulers merely to make Council resilient. Add complexity only for observed failure modes.

## Test Contract

Prefer a small number of high-level seams.

### 1. Council repository protocol

**Given** a newly initialized Council with both participant context refs at the initial commit,  
**When** USER/SOL/OPUS turns are appended,  
**Then** each turn creates exactly one append-only transcript block and one Git commit, and the correct participant cursor advances only after its successful response commit.

Also prove that snapshot-delta extraction returns pure chronological transcript text and rejects a non-append mutation.

### 2. `To SOL` end-to-end seam

**Given** a Council where SOL's context ref is behind current HEAD,  
**When** the user submits `To SOL`,  
**Then** only SOL's unread chronological Council transcript is sent through the persistent ChatGPT Web input adapter; the real Web SOL emits through MCP; exactly one SOL turn is committed; and `context/sol` advances to that response commit.

No browser output scraping may be used to satisfy this test.

### 3. `To OPUS` end-to-end seam

**Given** a Council where OPUS's context ref is behind current HEAD,  
**When** the user submits `To OPUS`,  
**Then** Opus receives the unread shared Council transcript through the Pydantic path, exactly one OPUS response turn is committed, and `context/opus` advances to that response commit.

### 4. Shared-room cross-participant context

**Given** USER and OPUS have exchanged turns since SOL's previous synchronized commit,  
**When** the next `To SOL` turn runs,  
**Then** SOL receives those intervening OPUS/USER turns in order before the latest USER request.

Mirror the same behavior for OPUS after intervening SOL turns.

### 5. Minimal Web UI integration

**Given** a running local Council backend and UI,  
**When** the user alternates `To SOL` and `To OPUS`,  
**Then** one visible chronological room is updated from Git-backed events without requiring the user to interact directly with the ChatGPT Web tab.

## Acceptance / Validation

Before Council v1 is accepted:

```text
Python Ruff                PASS
Python full pytest         PASS
Frontend type/build check  PASS
Council repo protocol      PASS
To SOL real Web E2E        PASS
To OPUS real provider E2E  PASS
Shared-room UI E2E         PASS
```

The existing `plans/council/2026-08-11-web-sol-e2e.md` remains evidence for the already-proven SOL transport primitive, but final acceptance must exercise the integrated v3 Council flow.

## Follow-up / Deferred

Only after v1 evidence justifies them:

- Independent Challenge mode;
- context compression that preserves reasoning lineage;
- richer Council history/navigation UI;
- multiple simultaneous Council rooms;
- automatic room naming/management;
- more participant models;
- bridge hardening beyond the demonstrated local single-user use case.

## Result

**FULL PASS — Council v1 implemented and accepted on 2026-08-12.**

### Delivered

- **T1 Council Repo Protocol** — `init.md` + append-only `chat.md`, one speaking event per commit, explicit `refs/council/context/{sol,opus}`, pure unread transcript suffix extraction, append-only validation, dirty-transcript rejection, and explicit cursor advancement.
- **T2 To OPUS** — real `opus5` Pydantic path, shared-room context reconstruction, one OPUS response commit, cursor advancement only after success, failure-safe retry without duplicate USER commits.
- **T3 To SOL** — persistent input-only Playwright/Edge CDP bridge, Web SOL output through `code_mode -> council_emit`, Git commit as completion signal, `expected_head` stale/duplicate-response guard, retry and late-response reconciliation without DOM output scraping.
- **T4 Shared Room UI** — top-level Svelte 5 + Vite + TypeScript UI backed by a local Starlette/Uvicorn REST server, real Git transcript rendering, `To SOL`, `To OPUS`, status/error/retry feedback, and explicit Council-owned SOL bridge lifecycle.

### Final validation evidence

```text
Python Ruff                PASS
Python full pytest         PASS — 60 passed
Council/App Pyright        PASS — 0 errors, 0 warnings
Svelte type check          PASS — 0 errors, 0 warnings
Vite production build      PASS
Council repo protocol      PASS
To OPUS real provider E2E  PASS
Shared-room Svelte UI E2E  PASS
To SOL real Web E2E        PASS
```

The final real SOL acceptance traversed the integrated path:

```text
Svelte `To SOL`
  -> local Python Council server
  -> SolBridge / playwright-cli / Playwright Extension input
  -> existing ChatGPT Web SOL
  -> code_mode / council_emit(expected_head=...)
  -> one SOL Git commit
  -> context/sol advancement
  -> UI-visible Git state
```

Acceptance evidence from the throwaway Council repo showed the USER turn at `fad1287790170b5962ec877a3c6516a3e13a403b`, the SOL response commit at `d4a998a761f033b96cbf9cc5ec8779aa683c4dc9`, and final `HEAD == refs/council/context/sol` at that SOL commit. Playwright remained input-only throughout.

### Meaningful implementation discoveries / deviations

1. **Opus Pydantic calls are stateless across worker invocations.** Git cursor semantics remain authoritative, while the Opus adapter reconstructs previously synchronized transcript context plus the new unread suffix for each call. No separate conversation database was added.
2. **The SOL bridge is Council-owned rather than a generic 600-second background execution.** `SolBridge` has explicit start/close lifecycle, reuses a healthy shared `msedge` Playwright CLI session when present, and otherwise attaches through the official Extension. This removes the direct-CDP/socket lifetime from production while leaving a pre-existing shared browser session alive on close.
3. **SOL output gained an `expected_head` guard.** `council_emit` remains backward compatible, while integrated SOL turns use compare-and-swap-style HEAD validation so late or duplicate responses cannot silently attach to the wrong Council state.
4. **Retries preserve the original USER event.** OPUS and SOL retry paths reuse unchanged unread context instead of committing duplicate USER turns; a late SOL commit can be reconciled before reconnecting the browser.
5. **The UI transport is simple REST, not WebSocket.** Starlette + Uvicorn is sufficient for the single-room v1 because one user-triggered turn can await its participant result while the Python process owns the persistent SOL bridge.
6. **Default Council port is 8791.** Port 8787 was already occupied by the local Hermes UI during acceptance.
7. **Git CLI is intentionally retained.** Council uses a narrow subprocess adapter around official Git plumbing rather than adding GitPython, pygit2/libgit2, or Dulwich.

The deferred list above remains deferred; v1 success does not implicitly approve multi-room management, automatic summarization, autonomous debate, or richer history/navigation.


## Post-v1 Direction — Start / Reopen Ergonomics

> This section is **not part of the Council v1 acceptance contract** above. It records approved direction discovered after v1 was completed. Current implementation remains the CLI/manual startup documented in `docs/council/startup.md`.

The next product problem is startup/reopen friction, not a redesign of the delivered Shared Room protocol.

Approved direction:

- the current ChatGPT Web conversation remains SOL;
- new Council rooms use `~/council/<YYMMDD-title>/`;
- SOL authors the initial `init.md` from the current session plus relevant source/runtime evidence;
- `init.md` should preserve causal context, including `Why`, compact `Background Knowledge`, current reality, constraints, prior decisions/rejected alternatives when material, `Original References`, and the Council goal;
- a peer may surface missing/ambiguous context because incomplete causal context previously caused a strong review to attack the wrong problem; this is a reason, not a mandatory “ask questions first” behavior rule;
- reusable start/reopen mechanics belong behind a registered `code_mode` capability, not a fifth top-level MCP tool;
- room-state recovery and fresh Web SOL native-context rehydration are distinct problems.

See `docs/council/startup.md` for the current design contract. Exact lifecycle capability schema and reopen/rehydration behavior remain to be decided before implementation.
