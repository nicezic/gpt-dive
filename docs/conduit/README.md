# Conduit

Conduit is GPT Dive's conversation and task transport subproject for ChatGPT Web.

Its purpose is to keep the Web-facing interaction small while letting ChatGPT Web SOL hand off conversation output and detached work through a local `@c` MCP surface while reusing GPT Dive for execution. The current `@c` path already returns compact task snapshots. ADR 0002 accepts TrackedTasks + Opportunistic Evidence Pickup (OEP) as the shared awareness direction across asynchronous runners, including a future `@dive` refresh path; that cross-surface integration is not yet implemented.

```text
ChatGPT Web SOL
      |
     @c
      |
   Conduit
      |
      +-- task/runtime routing
      +-- Redis event fan-out
             |
             +-- /tmp logging
             +-- custom Web UI
             +-- durable storage
             +-- GBrain / later consumers
```

Conduit does not replace GPT Dive's execution runtime. GPT Dive remains the backend owner of Code Mode, ExecutionManager, execution policy, and local capabilities; Conduit is the conversation/task plane that can route into those existing components.

## Documentation

| Path | Role | Update when |
|---|---|---|
| `README.md` | Stable entry point. Short project description, document map, and ownership boundaries. | The meaning or document structure of Conduit changes. |
| `bootstrap.md` | Causal context packet for a fresh ChatGPT Web session or peer reviewer. Keeps the Why, user economics, ChatGPT Web constraints, proven infrastructure, settled design, and assumptions that still require live validation. | Background or a consequential design assumption changes. |
| `CONTEXT.md` | Canonical Conduit domain language maintained actively during design. Glossary only; no implementation detail. | A Conduit-specific term is resolved, split, merged, or renamed. |
| `CONTINUATION.md` | Current handoff state. Records the immediate objective, settled decisions relevant to the active work, current validation state, and next action. | `/handoff`, session change, or active implementation state changes. |
| `runtime/` | Reconstructable Conduit tunnel/systemd templates. Runtime sockets and secrets never belong here. | The deployed Conduit tunnel/service contract changes. |
| `adr/` | Rare Architecture Decision Records. Files prefixed `0_` are explicitly **pre-ADR brainstorm/design drafts**, not settled decisions. | A durable, consequential trade-off is settled, or an active design draft needs a temporary home before promotion. |

Detailed protocol and runtime documents should be added only after the corresponding behavior exists or becomes stable enough to deserve its own SSOT. Do not create speculative documentation layers merely to fill out the tree.

## Ownership boundaries

```text
Conduit
  owns: conversation/task protocol, active-task view, event routing

GPT Dive runtime
  owns: Code Mode, ExecutionManager, execution policy, local capabilities

Redis
  owns: event transport / fan-out
  does not own: Conduit domain semantics

Custom Web UI
  owns: user-facing rendering and interaction

GBrain / storage consumers
  own: downstream indexing, analysis, and persistence policy
```

The governing design bias is to keep the primary path small. Do not add fallback paths just because they are technically possible; only resilience mechanisms whose value clearly outweighs their complexity should enter the design.
