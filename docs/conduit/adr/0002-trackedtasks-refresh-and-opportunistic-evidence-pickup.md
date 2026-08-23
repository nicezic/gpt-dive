---
title: ADR - TrackedTasks Refresh and Opportunistic Evidence Pickup
created: 2026-08-17
updated: 2026-08-17
type: decision
status: accepted
---

# ADR - TrackedTasks Refresh and Opportunistic Evidence Pickup

## Decision

Extend Conduit's conversation-driven task-pull model into a shared **TrackedTasks refresh contract** across the Web SOL tool surfaces.

Detached work must not force Web SOL to stop and wait. Web SOL may launch asynchronous work, continue its own foreground reasoning and tool use, and discover completion later because ordinary `@c` and `@dive` interactions carry the latest compact TrackedTasks view.

```text
launch detached work
        |
        +--------------------------+
        |                          |
        v                          v
 background work              Web SOL foreground
 M3 / agy / code / cmd        web / code / reasoning / tools
        |                          |
        |                    ordinary tool calls
        |                          |
        +------ eventually --------+
                    |
                    v
          TrackedTasks: done
                    |
                    v
      Opportunistic Evidence Pickup
          /          |          \
      discard      dedupe       use
```

The pattern is **runner-agnostic**. A search scout is only one example. The same course applies to:

- asynchronous search such as an M3 research scout;
- `/agy-worker`;
- `/m3-worker`;
- background Code Mode;
- arbitrary durable WSL2 commands or executions;
- future workers or runners that can be represented as tracked asynchronous work.

The common course is:

```text
launch -> do not wait -> keep working -> encounter refreshed TrackedTasks
       -> notice terminal work -> inspect when useful -> discard/dedupe/use
```

### Worker integration boundary

Workers do not need to share one implementation, runtime, or transport. `/agy-worker`, `/m3-worker`, background Code Mode, shell executions, and future runners may remain independent behind their existing execution paths.

Only the **response/status boundary** needs enough alignment for Conduit to represent the work consistently: identify the tracked item, expose a compact lifecycle state, and make the terminal result retrievable when Web SOL chooses to pick it up. Conduit should adapt heterogeneous worker responses at this boundary rather than forcing every worker into one internal protocol.

This keeps OEP cheap to extend: a new worker primarily needs a small response adapter, not a rewrite around Conduit.

## Context

ADR 0001 proved the narrower canary: ChatGPT Web SOL can launch detached work through `@c`, continue reasoning in the same real user turn, and rediscover completion on a later `@c` call without native MCP Tasks negotiation.

The next design pressure is broader. Web SOL routinely uses `@dive` while detached workers are running. If only explicit `@c` calls refresh task state, Web SOL must remember to poll or perform a special refresh action. That weakens the original goal of letting foreground work continue naturally.

ChatGPT Web currently does not negotiate the native MCP Tasks extension used by GPT Dive's TasksExtension path. Conduit therefore uses ordinary tool activity as a practical refresh channel instead of depending on server-initiated wake-up.

## TrackedTasks contract

**TrackedTasks** is the compact view of asynchronous work that Conduit still wants Web SOL to remain aware of.

A terminal task may remain present after execution reaches `done`, `failed`, or another terminal state. Execution completion and Web SOL handling are separate events. Removal from TrackedTasks happens only after a later explicit lifecycle decision handles that item.

The exact TrackedTask entry schema and exact lifecycle action names are intentionally not defined by this ADR.

### `@c`

Successful `@c` calls expose the current TrackedTasks view as part of their normal protocol result. For chat-first calls whose primary result carries no independent payload, TrackedTasks may be the effective return value itself.

### `@dive`

Every ordinary `@dive` tool result should also expose the latest TrackedTasks while preserving the tool's primary result.

Conceptually:

```text
@dive code_mode(...)
        |
        v
{
  result: <normal Code Mode result>,
  tracked_tasks: <latest compact view>
}
```

TrackedTasks is additive metadata, not a replacement for Code Mode output, shell output, or other tool-specific results.

The existing GPT Dive tool-call middleware is the natural implementation seam because all ordinary `tools/call` results already pass through it for periodic reminder injection.

Transport or protocol failure cannot guarantee a refresh because no usable tool result may return. Tool-level errors that still produce a normal MCP tool result should, where practical, preserve the same task-awareness opportunity.

## Opportunistic Evidence Pickup

**Opportunistic Evidence Pickup (OEP)** is the workflow in which Web SOL does not wait for asynchronous candidate evidence. It continues foreground work and notices completed tracked work through a later ordinary tool interaction. Only then does it inspect the result if it is still useful.

Worker output is **candidate evidence, not authority**. After pickup, Web SOL may:

- discard low-quality or irrelevant output;
- deduplicate information already found independently;
- retain useful evidence and incorporate it into the current reasoning;
- defer inspection if the result is no longer useful to the active work.

OEP therefore allows cheap or specialized workers to run speculatively without turning their latency into the critical path or their output into mandatory context.

## Example: unified search

A unified search flow may start an M3 scout asynchronously while Web SOL independently performs web search, GBrain/CodeGraph/Probe retrieval, source reading, and reasoning.

```text
user question
    |
    v
Web SOL
    |\
    | +--> M3 scout -------------------------+
    |                                        |
    +--> web search                          |
    +--> local retrieval                     |
    +--> reasoning                           |
    +--> more ordinary tools                 |
              |                              |
              +---- TrackedTasks: M3 done <--+
                              |
                              v
                             OEP
```

This example does not make OEP search-specific. `/agy-worker`, `/m3-worker`, background Code Mode, and arbitrary durable command execution follow the same lifecycle when launched asynchronously.

## Relationship to native MCP Tasks

This ADR does not replace or reject native MCP Tasks. GPT Dive may continue to support the standard Tasks extension for clients that negotiate it.

TrackedTasks is the ChatGPT Web-facing awareness mechanism for the environment where that negotiation is absent. It deliberately uses the conversation and existing tool calls as refresh opportunities instead of requiring active polling.

## Consequences

- Web SOL can keep useful foreground momentum while detached work runs concurrently.
- Background latency is removed from the critical path unless Web SOL explicitly chooses to wait.
- Normal `@dive` activity becomes a semi-forced task-awareness channel, reducing forgotten background work without a push subsystem.
- The same asynchronous workflow applies uniformly to AI workers, research scouts, Code Mode, shell executions, and future runners.
- Worker implementations stay independent; only a small compatible response/status boundary is required for TrackedTasks and later result pickup.
- Cheap or noisy workers can be used more aggressively because their results are optional candidate evidence.
- TrackedTask semantics remain distinct from the low-level Execution/ExecutionManager execution primitive.
- `wsl2_async` naming and future low-level Execution surface design remain separate follow-up work.

## Non-goals

This decision does not define:

- the final TrackedTask tuple/object schema;
- terminal handling action names such as ack/handled/release;
- the replacement or rename of `wsl2_async`;
- the implementation of unified search itself;
- worker-specific orchestration policy;
- Council conversation routing;
- the directed conversation protocol (`sender`, `recipient`, turn numbering, or Mirrored Full Output);
- a server-push notification subsystem.

Those concerns may build on this decision but should be settled independently when their own design pressure is concrete.
