# Conduit — Design Context

> Short causal-context packet for future sessions/reviewers. **Current code and [Conduit README](README.md) are authoritative for implemented behavior.** This document explains why the product exists, not an extra runtime contract.

## Product lineage and purpose

~~~text
Manual USER ↔ Web SOL ↔ OPUS relay
                ↓ (transport friction)
Council v1 Git-backed Room + input-only Edge bridge
                ↓ (generalized event / asynchronous work flow)
Conduit = Room + @c conversation/task transport + Redis fan-out
                ↓
future unified local web interaction (not implemented)
~~~

The user wants the **existing logged-in ChatGPT Web conversation** to remain SOL. Council showed that two AI participants could read the same reasoning and still disagree. The correct product automates the message relay while leaving judgment, turn order and domain decisions with the USER.

Long local commands and external workers should not stop SOL from thinking. When ChatGPT Web does not negotiate the MCP Tasks extension, Conduit uses **conversation-driven opportunistic Task pickup**:

~~~text
@c start → GPT Dive durable Execution → running Task
SOL continues ordinary work
later @c / @dive response → shared TrackedTasks
SOL optionally task(get), then explicit dismiss
~~~

No server-initiated wakeup or separate Task database is necessary. `execution_id`, SQLite lifecycle, cancellation and deadlines belong to GPT Dive Runtime. Conduit owns conversation/event protocol and Redis fan-out; the Room owns the Git transcript.

## Proven building blocks

- GPT Dive Code Mode: typed Monty capabilities, WSL2 commands, Agent/peer workers and always-durable Execution.
- Room: input-only Playwright Extension/Edge delivery to **existing** Web SOL; SOL response through `council_emit` → Git commit; OPUS through Pydantic AI.
- Conduit `@c`: task actions, conversation `emit/sync`, Redis event publication and compact Runtime-owned TrackedTasks snapshots.
- Redis: event/fan-out layer for NDJSON logs, later UI, durable consumers and GBrain—not the Execution authority. Avoid inventing competing fallback transports.
- Future myWeb: may reuse the Room UI and Conduit event stream but is not yet integrated.

## Constraints reviewers must receive

- Optimize **Web SOL as the primary engineer**, not an imaginary local substitute. Paid model quotas, provider costs and preferences are volatile: check `~/wiki/user/models-and-providers.md` for current facts instead of caching old model names here.
- Preserve **parallel productivity**: SOL can reason while AGY/OPUS/local commands work.
- Current transport/connector capabilities need live verification after changes; historical canary acceptance is not a guarantee for a new session.
- Reuse the one Runtime `Execution` and Task awareness projection. A second scheduler/task store or speculative ACP/MCP Tasks implementation adds complexity without confirmed need.
- Protect the literal ChatGPT browser conversation, strict argument validation, credential isolation, cancellation, and non-replay after uncertain failures.
- Favor explicit errors and minimal systems; avoid speculative fallback trees.

## Domain modeling during redesign

When two names imply the same responsibility (as Council and Conduit once did), or one term covers incompatible meanings, **surface the collision and agree on one canonical definition**. The USER owns domain decisions; the AI investigates concrete facts and proposes the minimal name/boundary. Record durable Conduit terms in [CONTEXT](CONTEXT.md), not in duplicate glossary files.

## Reading order

1. [Conduit](README.md) — **current** product/ownership map.
2. [Runtime architecture](../runtime/architecture.md) — Execution/Task invariants.
3. [Conduit Context](CONTEXT.md) — canonical protocol terms.
4. [Conduit continuation](CONTINUATION.md) — dated remaining work; verify live.
5. [Room](room/README.md) and [Room history](room/history.md) — implemented multi-model interaction and why.
6. [Conduit ADRs](adr/) — accepted design decisions; older pre-ADR brainstorming is in Git history.

For a peer review, include the actual constraints above before inviting alternative architectures. Keep upstream documentation and AI operation rules in Wiki, not copied into this packet.
