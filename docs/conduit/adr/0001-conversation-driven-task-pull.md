---
title: ADR — Conversation-Driven Task Pull for ChatGPT Web
created: 2026-08-16
updated: 2026-08-16
type: decision
status: accepted
---

# ADR — Conversation-Driven Task Pull for ChatGPT Web

## Decision

Use **conversation-driven task pull** as Conduit's task-refresh model for ChatGPT Web.

A normal Web SOL turn may start detached work through `@c`, continue reasoning in the same user turn, and call `@c` again later in that turn or on a later user Enter. Every successful `@c` call returns a compact task snapshot, so completed work is rediscovered through ordinary conversation activity rather than server-initiated wake-up.

```text
user Enter
   ↓
@c start
   ↓
detached task: running
   ↓
SOL continues reasoning
   ↓
@c sync / collect / emit
   ↓
compact snapshot: running / done
```

Server push is not required for the target workflow. Lack of ChatGPT Web negotiation of `io.modelcontextprotocol/tasks` is therefore not a blocker for this Conduit path.

## Context

GPT Dive already owns durable local execution through ExecutionManager. Conduit is the Web-facing conversation/task plane and should reuse that runtime rather than recreate it.

The design goal is to preserve one productive ChatGPT Web SOL reasoning flow while detached local or external work continues concurrently. The user's next conversation turn is an acceptable and intentional refresh boundary.

## Live evidence

Fresh-session acceptance on 2026-08-16 proved the core tool loop from one user Enter:

```text
@c start
  → detached task returned immediately: running

SOL reasoning
  → continued in the same turn

@c sync
  → same task snapshot: done
```

This directly demonstrated:

```text
c1 → SOL reasoning → c2
```

A later live semantics check on 2026-08-16 also confirmed the v0 retention direction:

- the same completed task was collected twice successfully;
- both reads returned the same completed result;
- completed tasks remained present in later compact snapshots, including tasks retained across later user turns.

## Task semantics carried by this decision

- `@c` remains the stable Web-facing namespace.
- One primary action is performed per `@c` call.
- Every successful call carries a compact task snapshot.
- Snapshots expose small correlation/status fields, not full repeated results.
- `collect` is non-destructive in v0. Duplicate reads are preferable to creating a result-loss window.
- Ordinary `@c` calls and user turns are the intentional refresh cadence.
- Redis remains the event/fan-out transport; it does not own Conduit domain semantics.

## Consequences

Conduit does not need a push-notification subsystem merely to make detached work useful in ChatGPT Web. Completed work may wait until the next ordinary `@c` interaction and still remain discoverable.

The protocol should evolve from real workflow pressure while keeping the Web-facing surface small. In particular, this ADR does not justify hiding all GPT Dive execution behind Conduit or adding speculative fallback paths.

## Non-goals

This decision does not define long-term archive/cleanup policy, myWeb UI behavior, durable database policy, GBrain ingestion, or a generic replacement for MCP Tasks. Those remain separate future concerns and should be designed only when concrete workflow pressure exists.
