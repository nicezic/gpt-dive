# Conduit

Conduit is GPT Dive's conversation and task transport subproject for ChatGPT Web.

Its purpose is to keep the Web-facing interaction small while letting ChatGPT Web SOL hand off conversation output and asynchronous work through a local `@c` MCP surface while reusing GPT Dive Runtime. Both `@c` snapshots and ordinary `@dive` traffic now consume the same Runtime-owned TrackedTasks projection.

```text
ChatGPT Web SOL
      |
     @c
      |
   Conduit
      |
      +-- Runtime start/get/cancel/dismiss
      +-- Redis event fan-out
             |
             +-- /tmp logging
             +-- custom Web UI
             +-- durable storage
             +-- GBrain / later consumers
```

Conduit does not replace GPT Dive's execution runtime. GPT Dive remains the owner of Execution, Task, TrackedTasks, deadlines, recovery, and local capabilities. Conduit adds a conversation/event plane over those components and uses the same single `execution_id`; it has no Task store of its own.

```text
@c start(label, command)
        │
        ▼
Runtime Execution + published Task
        │
        ├─ @c get / cancel / dismiss
        └─ shared TrackedTasks snapshot
```

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
  owns: conversation protocol, event envelope, Redis publication

GPT Dive runtime
  owns: Execution/Task lifecycle, TrackedTasks projection, deadlines, local capabilities

Redis
  owns: event transport / fan-out
  does not own: Conduit domain semantics

Custom Web UI
  owns: user-facing rendering and interaction

GBrain / storage consumers
  own: downstream indexing, analysis, and persistence policy
```

The governing design bias is to keep the primary path small. Do not add fallback paths just because they are technically possible; only resilience mechanisms whose value clearly outweighs their complexity should enter the design.
