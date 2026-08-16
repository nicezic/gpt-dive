# Conduit Canary Plan

## Problem Statement

ChatGPT Web GPT-5.6 Sol is the user's primary engineer and conductor, but ChatGPT Web does not currently negotiate MCP Tasks. Long-running workers or shell jobs therefore either block a tool call or require manual lifecycle polling that interrupts the reasoning flow. Conduit must test whether the existing ChatGPT Web tool loop can recover useful async behavior without server push: start detached work, continue reasoning, and rediscover task state automatically on later `@c` calls.

The first canary must validate this behavior through the permanent `@c` namespace rather than a throwaway test namespace. Redis is already a settled component and is not under evaluation.

## Solution

Introduce the smallest permanent Conduit MCP surface needed to exercise one conversation-driven async loop. Each `@c` call performs exactly one primary action and always returns a compact snapshot of Conduit-owned active tasks. The canary supports a detached task start, a short synchronous action, and non-destructive result collection. Conduit reuses GPT Dive's existing durable JobManager rather than implementing a second process lifecycle.

The live acceptance question is intentionally narrow: after one user Enter, can ChatGPT Web SOL call `@c`, reason over the response, then call `@c` again before producing its final response?

## User Stories

1. As the user, I want `@c` to be the real permanent namespace from the first canary, so that successful prototype work evolves directly into Conduit.
2. As Web SOL, I want to start a detached task and receive its stable task ID immediately, so that I can continue useful reasoning without waiting for task completion.
3. As Web SOL, I want every `@c` response to contain a compact active-task snapshot, so that task awareness follows normal conversation/tool use without separate status polling ceremony.
4. As Web SOL, I want to run a short synchronous canary action while detached work continues, so that the same-turn `c1 -> reasoning -> c2` behavior can be observed.
5. As Web SOL, I want completed task results to remain retrievable after the first read, so that an interrupted tool response does not destroy the only copy of a result.
6. As the user, I want task snapshots to stay compact, so that detached work does not inflate ChatGPT context on every tool call.
7. As the user, I want Redis to receive Conduit events from the start, so that `/tmp`, a future custom Web UI, durable storage, and GBrain can subscribe without changing the Web-facing protocol.
8. As the user, I want the first consumer to append simple NDJSON under `/tmp`, so that I can inspect the event path without committing to later persistence design.
9. As the user, I want failures to stop explicitly rather than trigger speculative fallback paths, so that the canary remains small and diagnosable.
10. As a maintainer, I want Conduit execution to reuse GPT Dive's current JobManager and execution policy, so that the canary does not create a parallel process runtime.
11. As a maintainer, I want MCP metadata/schema changes to be accepted only in a fresh ChatGPT Web session after restart, so that schema-cache behavior cannot produce a false PASS.
12. As a reviewer, I want automated tests to validate Conduit response envelopes, task snapshots, non-destructive collection, and event emission before live Web acceptance.

## Implementation Decisions

- Conduit is a distinct Web-facing MCP namespace named `c`; its implementation remains inside the GPT Dive repository and may reuse GPT Dive backend modules.
- The Web-facing surface stays minimal. One call performs one primary action. The canary actions are detached start, short synchronous execution, and result collection.
- Every successful Conduit call returns one response envelope containing the primary result plus the current compact task snapshot.
- Snapshot entries contain only stable task identity, a short caller-supplied label/intent, status, and compact timing metadata. They do not repeat task output.
- Detached execution delegates to the existing JobManager. Conduit owns only the mapping between a Conduit task and its underlying durable job.
- Result collection is non-destructive in v0. Repeated collection of a completed task returns the same stored/durable result while retention remains valid.
- Redis is the fixed Conduit event/fan-out transport. The canary emits lifecycle/action events to one Conduit stream and runs a minimal consumer that appends NDJSON under `/tmp`.
- Redis failure is an explicit Conduit failure; no alternate event transport is implemented.
- The first live canary does not require server-initiated notification or MCP Tasks negotiation. User turns and ordinary `@c` calls provide the status-refresh cadence.
- The `@c` MCP surface must be deployable alongside the existing `@dive` surface without replacing GPT Dive's backend runtime.
- MCP restart and fresh-session acceptance are separate from local implementation tests. The current ChatGPT session is not authoritative after schema changes.

## Testing Decisions

- Prefer the Web-facing Conduit tool boundary as the highest automated seam: exercise actions and inspect returned envelopes rather than testing internal helper calls in isolation.
- Reuse existing JobManager test patterns for detached start/status/result behavior rather than mocking a second task runtime.
- Test that every Conduit action response includes a task snapshot.
- Test a real short detached command transitioning from running to completed, then collect the result twice and verify it remains retrievable.
- Test that snapshot entries remain compact and exclude command output.
- Test that an emitted Conduit event reaches Redis and the canary NDJSON consumer writes a valid event line under `/tmp` when Redis integration is exercised locally.
- Test invalid action/arguments as explicit errors; do not test fallback routing because no fallback exists.
- Run focused Conduit tests repeatedly, then type/lint checks and the repository full test suite once at the end.
- Final live acceptance must occur only after MCP restart in a fresh ChatGPT Web session. PASS requires observing `c1 -> SOL reasoning -> c2` after one user Enter. A later user turn must also be able to observe the earlier detached task in the automatic snapshot.

## Out of Scope

- Server push or waking ChatGPT when a task completes.
- Requiring or emulating the MCP Tasks extension.
- General-purpose replacement of all GPT Dive tools behind Conduit.
- Custom myWeb implementation.
- Durable conversation database design.
- GBrain ingestion/indexing implementation.
- Redis alternatives or fallback event transports.
- Automatic task deletion/consumption policy beyond existing retention.
- Broad worker types beyond what is needed to prove the first detached-task path.

## Further Notes

The stable causal context is `docs/conduit/bootstrap.md`; active design ideas are in `docs/conduit/adr/0_brainstorm-and-design-draft.md`. Redis, GPT Dive JobManager, Council's asymmetric Web-SOL transport precedent, and the lack of ChatGPT Web MCP Tasks negotiation are existing constraints/evidence rather than canary hypotheses.

The canary should remain intentionally thin. Additional resilience ideas that do not prevent high-impact data loss or a security-boundary failure are excluded from this first implementation.
