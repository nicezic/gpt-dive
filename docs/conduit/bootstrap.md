# Conduit Bootstrap

> Purpose: causal context packet for fresh ChatGPT Web sessions and independent peer review. Read this before designing, reviewing, or implementing Conduit.

## 1. What Conduit is

Conduit is a GPT Dive subproject that introduces a small Web-facing MCP namespace, `@c`, for conversation output, lightweight synchronous work, detached task lifecycle, and automatic active-task awareness.

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

A user conversation turn therefore becomes the natural polling cadence for detached work. The server does not need to wake ChatGPT when a task finishes. A completed task can remain available until a later `@c` call exposes it.

## 2. Why this exists

The user uses ChatGPT Web GPT-5.6 Sol as the primary engineer and conductor. Web SOL has been observed to have a comparatively generous quota and, through GPT Dive, can directly inspect and operate the user's WSL2 environment.

The practical pain is that long-running local work, external workers, tests, or shell jobs can block the reasoning flow when every tool call waits synchronously. MCP Tasks (`io.modelcontextprotocol/tasks`, informally called “MCP 2.0 Tasks” in the project discussion) would solve part of this at the protocol level, but ChatGPT Web has not negotiated that extension in the verified environment.

Conduit aims to recover most of the useful async workflow without requiring server-initiated wake-up:

```text
Turn N
  @c start(t1)
  → t1 running
  → SOL continues useful work

Turn N or N+1
  any @c call
  → snapshot includes t1 done
  → SOL may collect/use the result
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
  → code_mode / JobManager / local capabilities
  → WSL2
```

GPT Dive already has durable detached execution through JobManager and background Code Mode. Conduit should reuse execution/runtime machinery rather than recreate it.

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
- **Google Antigravity / Gemini 3.7 Flash High**: fast external worker through the official `agy` CLI. Normal worker path is `code_mode -> agy_worker()`; long detached work can use the durable shell/job path.
- **Opus-5 through third-party providers**: paid/selective independent reviewer. Useful for consequential peer review, not the default worker.
- **MiniMax M3**: abundant purchased quota but lower trust for difficult reasoning; not a design authority.

The economic goal is therefore not to replace Web SOL with a local model. It is to make Web SOL more productive while external/local work continues concurrently.

Volatile pricing, quota, provider, and model facts belong to the Wiki SSOT, not this document.

## 5. Active design draft

The detailed protocol shape, first canary, task semantics, and future myWeb / DB / GBrain / GPT Dive integration ideas are intentionally kept out of this stable bootstrap packet:

`docs/conduit/adr/0_brainstorm-and-design-draft.md`

The `0_` prefix means **pre-ADR design workspace**, not a settled architecture decision. Promote only durable decisions into numbered ADRs after live evidence and implementation pressure justify them.

Current high-level constraints remain: `@c` is the stable namespace from canary onward, one primary action per call, every result carries a compact task snapshot, Redis is the fixed event/fan-out layer, and low-value fallback trees are excluded.

## 6. Peer review packet

Independent reviewers should review **the real constrained system**, not a generic async-agent architecture.

Before judging Conduit, assume the following facts unless live evidence supersedes them:

- The primary intelligence is the existing **ChatGPT Web GPT-5.6 Sol**, not a locally instantiated equivalent.
- Web SOL is economically favored because its observed quota is generous; scarce Codex usage should not be substituted casually.
- The user wants to preserve a productive single SOL reasoning flow while detached workers/jobs run.
- GPT Dive already connects ChatGPT Web to the real WSL2 machine and already provides durable background jobs.
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

## 7. SSOT / authority links

This bootstrap preserves causal context. For current detailed truth, follow the appropriate authority below.

| Topic | SSOT / authority |
|---|---|
| Conduit document map and ownership | `docs/conduit/README.md` |
| Current Conduit handoff / next action | `docs/conduit/CONTINUATION.md` |
| Rare durable Conduit decisions | `docs/conduit/adr/` |
| GPT Dive runtime architecture | `docs/runtime/architecture.md` |
| GPT Dive current implementation / source | `src/gpt_dive/` |
| Council current architecture | `docs/council/README.md` |
| Council causal history / lessons | `docs/council/history.md` |
| User model subscriptions, economics, routing | `~/wiki/user/models-and-providers.md` |
| Pydantic AI / Harness operating baseline | `~/wiki/workflow/pydantic-ai/README.md` |
| GBrain retrieval/current corpus policy | `~/wiki/infra/gbrain.md` |
| GBrain installation/maintenance/reconstruction | `~/gbrain/local-docs/reconstruction.md` |
| Logged-in Edge / Playwright operating contract | `~/wiki/skills/web/edge-playwright.md` |
| Google Antigravity / `agy` worker contract | `~/wiki/reference/google/agy.md` |
| Credentials and secret handling | `~/wiki/reference/security/credentials.md` |
| Wiki global navigation | `~/wiki/index.md` |
| Recent causal history/provenance | `~/wiki/log.md` |

## 8. Fresh-session reading rule

For a fresh Conduit implementation/review session:

```text
1. read docs/conduit/README.md
2. read docs/conduit/bootstrap.md
3. read docs/conduit/CONTINUATION.md if present
4. follow only the SSOT links relevant to the current task
5. verify volatile runtime facts live
```

For an independent peer review, `bootstrap.md` is the main review capsule. The peer should receive enough causal context to understand the economics, ChatGPT Web boundary, existing evidence, and rejected problem framings before challenging the design.
