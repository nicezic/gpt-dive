# Conduit Bootstrap

> Purpose: causal context packet for fresh ChatGPT Web sessions and independent peer review. Read this before designing, reviewing, or implementing Conduit.

## 1. What Conduit is

Conduit is a GPT Dive subproject that introduces a small Web-facing MCP namespace, `@c`, for conversation output, lightweight synchronous work, Runtime-owned Task lifecycle, and automatic outstanding-Task awareness.

The design is optimized for the user's actual ChatGPT Web workflow rather than for an abstract generic agent platform.

The key idea is simple:

```text
user presses Enter
      ↓
ChatGPT Web SOL turn
      ↓
@c call
      ↓
primary action result
+
compact active-task snapshot
      ↓
SOL keeps reasoning
```

A user conversation turn therefore becomes the natural refresh cadence for asynchronous work. The server does not need to wake ChatGPT when a Task finishes. A completed Task remains available until a later `@c` or `@dive` interaction exposes it and Web SOL explicitly dismisses it.

## 2. Why this exists

The user uses ChatGPT Web GPT-5.6 Sol as the primary engineer and conductor. Web SOL has been observed to have a comparatively generous quota and, through GPT Dive, can directly inspect and operate the user's WSL2 environment.

The practical pain is that long-running local work, external workers, tests, or shell executions can block the reasoning flow when every tool call waits synchronously. MCP Tasks (`io.modelcontextprotocol/tasks`, informally called “MCP 2.0 Tasks” in the project discussion) would solve part of this at the protocol level, but ChatGPT Web has not negotiated that extension in the verified environment.

Conduit aims to recover most of the useful async workflow without requiring server-initiated wake-up:

```text
Turn N
  @c start(t1)
  → t1 running
  → SOL continues useful work

Turn N or N+1
  any @c call
  → snapshot includes t1 done
  → SOL may get/use the result, then dismiss awareness
```

This is intentionally conversation-driven pull, not push notification infrastructure.

## 3. Existing evidence and foundations

Conduit does not start from zero. Several required ideas are already proven locally.

### GPT Dive

Current Web SOL execution path:

```text
ChatGPT Web
  → Secure MCP Tunnel
  → GPT Dive MCP
  → code_mode / ExecutionManager / local capabilities
  → WSL2
```

GPT Dive now creates an always-durable Execution for every Code Mode run and publishes Task awareness only when needed. Conduit reuses the same SQLite lifecycle, `ExecutionManager`, single `execution_id`, and TrackedTasks projection rather than recreating them.

### Council precedent

Council already proved the important asymmetric Web SOL transport pattern:

```text
input to Web SOL
  → Edge / Playwright

output from Web SOL
  → explicit local tool emission (`council_emit`)
```

Playwright is deliberately input-only. It does not scrape assistant output. This is the strongest existing precedent for making meaningful SOL output flow through a tool-backed local path.

### Edge / logged-in ChatGPT Web

The user's existing authenticated Edge session can be controlled through the official Playwright Extension path. Conduit may later reuse this for a custom web front-end that injects user input into the existing ChatGPT Web conversation while keeping output on the local event plane.

### Redis

Redis is already a proven local component in the user's environment and is a settled Conduit design choice. Do not reopen Redis-vs-SQLite as a fallback discussion unless a new hard blocker appears.

Conduit intends Redis to be the event/fan-out branch point, not the place where all domain logic is concentrated.

```text
@c
 ↓
Conduit gateway
 ↓
Redis
 ├─ /tmp NDJSON      # first tracer output
 ├─ myWeb            # later
 ├─ durable DB       # later
 ├─ GBrain pipeline  # later
 └─ other consumers  # later
```

## 4. User economics and model constraints

Architecture reviews must include the user's real model economics. Omitting them previously caused a strong Council reviewer to challenge the wrong problem.

Current operating reality:

- **ChatGPT Web GPT-5.6 Sol**: primary engineer/conductor; observed Web quota is generous enough that Web-first engineering is economically preferred.
- **OpenAI Codex pool (Sol/Terra/Luna)**: comparatively scarce on the user's ChatGPT Plus subscription; preserve this pool for cases where Codex-native execution or independent review adds real value.
- **Google Antigravity / Gemini 3.8 Flash High**: fast external worker through the official `agy` CLI. Normal worker path is `code_mode → agy_worker()`; deliberately external long work may be delegated to a sibling `systemd-run --user` unit outside GPT Dive Runtime.
- **Opus-5 through third-party providers**: paid/selective independent reviewer. Useful for consequential peer review, not the default worker.
- **MiniMax M3**: abundant purchased quota but lower trust for difficult reasoning; not a design authority.

The economic goal is therefore not to replace Web SOL with a local model. It is to make Web SOL more productive while external/local work continues concurrently.

Volatile pricing, quota, provider, and model facts belong to the Wiki SSOT, not this document.

## 5. Active domain-language stewardship

**Web SOL actively owns domain-modeling discipline during Conduit design. This is not an optional cleanup pass and does not require the user to invoke `/domain-modeling` first.** When terminology is being created, overloaded, contradicted, or used to move a conceptual boundary, Web SOL should proactively stop the drift and mediate the language before design continues.

In particular, Web SOL should intervene when:

- two names may refer to the same concept;
- one name is being used for two different concepts;
- a new statement conflicts with an already-settled definition or boundary;
- fuzzy language would let two incompatible designs appear equivalent;
- a concrete edge case reveals that the current vocabulary cannot describe the system precisely.

Do not silently reinterpret the user's words to make them fit. Surface the conflict concretely, explain which statements cannot all be true at once, propose the smallest useful split/merge/rename, and let the user decide the domain meaning. **Facts are Web SOL's execution to investigate; domain decisions are the user's.** Once a term is resolved, capture it immediately in `docs/conduit/CONTEXT.md` rather than batching terminology cleanup for later. Keep that glossary free of implementation detail.

`/grill-with-docs` therefore means what the Matt Pocock upstream workflow intends: `/grilling` plus active `/domain-modeling`. Web SOL should keep challenging vocabulary throughout the design tree, not merely read the glossary at session start.

The user and Web SOL may use recurring conversational aliases alongside canonical terms:

- **웹솔이** = ChatGPT Web GPT-5.6 Sol, the primary engineer/conductor.
- **잼민이** = the Gemini worker, usually Gemini 3.8 Flash High through `agy`.
- **단틱이** = Pydantic AI.

These aliases are conversational shorthand, not automatically Conduit domain terms; only concepts specific to Conduit belong in `docs/conduit/CONTEXT.md`.

Web SOL should maintain a **small practical mapping from the user's recurring wording to canonical terms** so both partners can use natural shorthand while preserving one shared domain model. Keep only recurring, useful mappings rather than turning the glossary into a thesaurus.

Web SOL should intervene when a wording choice creates **semantic conflict**: two plausible mappings imply different architecture, one term is being used for two concepts, or a new statement contradicts a settled meaning. Surface the conflict and help the user resolve the canonical meaning before design continues.

Treat this discipline as **always on during consequential Conduit design**, even when `/domain-modeling` was not explicitly invoked in the current turn. Before accepting a new key term, boundary, lifecycle state, actor, message type, or protocol concept, reconcile it against `docs/conduit/CONTEXT.md` and the decisions already made. Do not rely on the user to remind Web SOL to invoke the skill.

## 6. Active design draft

The detailed protocol shape, first canary, task semantics, and future myWeb / DB / GBrain / GPT Dive integration ideas are intentionally kept out of this stable bootstrap packet:

`docs/conduit/adr/0_brainstorm-and-design-draft.md`

The `0_` prefix means **pre-ADR design workspace**, not a settled architecture decision. Promote only durable decisions into numbered ADRs after live evidence and implementation pressure justify them.

Current high-level constraints remain: `@c` is the stable namespace from canary onward, one primary action per call, every result carries a compact task snapshot, Redis is the fixed event/fan-out layer, and low-value fallback trees are excluded.

## 7. Peer review packet

Independent reviewers should review **the real constrained system**, not a generic async-agent architecture.

Before judging Conduit, assume the following facts unless live evidence supersedes them:

- The primary intelligence is the existing **ChatGPT Web GPT-5.6 Sol**, not a locally instantiated equivalent.
- Web SOL is economically favored because its observed quota is generous; scarce Codex usage should not be substituted casually.
- The user wants to preserve a productive single SOL reasoning flow while asynchronous workers/Executions run.
- GPT Dive already connects ChatGPT Web to the real WSL2 machine and makes every accepted Code Mode Execution durable from the start.
- ChatGPT Web has not negotiated MCP Tasks (`io.modelcontextprotocol/tasks`) in the verified environment.
- The design does **not** require server-initiated wake-up. The user's next conversation turn is an acceptable and intentional status-refresh boundary.
- Council already proved input-only browser transport plus tool-based SOL output.
- Redis is a settled, already-proven local component and the chosen event fan-out point.
- The user strongly prefers low-complexity, fail-explicit systems. Do not propose large fallback trees unless they prevent a high-impact failure such as irreversible data loss or a security-boundary break.

Peer review should focus on:

1. whether the one-Enter `c1 → reasoning → c2` tool loop is viable in actual ChatGPT Web;
2. task identity, result retention, idempotency, restart and retry boundaries;
3. compact task-snapshot semantics and context cost;
4. whether `@c` remains a clear protocol surface rather than becoming a god-object;
5. security/execution-policy inheritance from GPT Dive;
6. which assumptions require live acceptance rather than theoretical reasoning;
7. whether a proposed simplification preserves the user's actual economic/workflow advantages.

Do not spend review budget re-litigating Redis, requiring server push, or replacing Web SOL with a different model unless new evidence demonstrates a hard blocker.

## 8. SSOT / authority links

This bootstrap preserves causal context. For current detailed truth, follow the appropriate authority below.

| Topic | SSOT / authority |
|---|---|
| Conduit document map and ownership | `docs/conduit/README.md` |
| Conduit canonical domain language | `docs/conduit/CONTEXT.md` |
| Current Conduit handoff / next action | `docs/conduit/CONTINUATION.md` |
| Rare durable Conduit decisions | `docs/conduit/adr/` |
| GPT Dive runtime architecture | `docs/runtime/architecture.md` |
| GPT Dive current implementation / source | `src/gpt_dive/` |
| Council current architecture | `docs/council/README.md` |
| Council causal history / lessons | `docs/council/history.md` |
| User model subscriptions, economics, routing | `~/wiki/user/models-and-providers.md` |
| Pydantic AI / Harness operating baseline | `~/wiki/workflow/pydantic-ai/README.md` |
| GBrain retrieval/current corpus policy | `~/wiki/infra/gbrain.md` |
| GBrain installation/maintenance/reconstruction | `~/gpt-dive/gbrain/docs/reconstruction.md` |
| Logged-in Edge / Playwright operating contract | `~/wiki/skills/web/edge-playwright.md` |
| Google Antigravity / `agy` worker contract | `~/wiki/reference/google/agy.md` |
| Credentials and secret handling | `~/wiki/reference/security/credentials.md` |
| Wiki global navigation | `~/wiki/index.md` |
| Recent causal history/provenance | `~/wiki/log.md` |

## 9. Fresh-session reading rule

For a fresh Conduit implementation/review session:

```text
1. read docs/conduit/README.md
2. read docs/conduit/bootstrap.md
3. read docs/conduit/CONTEXT.md and actively reconcile the current vocabulary against it
4. read docs/conduit/CONTINUATION.md if present
5. keep `/domain-modeling` discipline active during consequential design even without an explicit skill invocation
6. follow only the SSOT links relevant to the current task
7. verify volatile runtime facts live
```

For an independent peer review, `bootstrap.md` is the main review capsule. The peer should receive enough causal context to understand the economics, ChatGPT Web boundary, existing evidence, and rejected problem framings before challenging the design.
