# Conduit

**Conduit is GPT Dive's conversation and collaboration layer.** It unifies two stages of the same product direction:

- **Room** (originally Council, implemented first): the human-steered USER / SOL / OPUS Git discussion room and Svelte UI.
- **Transport** (later named Conduit): the `@c` MCP surface for conversation events, Redis fan-out, and Runtime-backed asynchronous work.

These are **features of one product**, not independent applications with their own job lifecycles. The old Council name survives inside the Git room protocol and the `council_emit` capability for compatibility.

## Architecture

~~~text
                         ChatGPT Web SOL
                            │
                 ┌──────────┴──────────┐
                 ▼                     ▼
             @c Conduit            Code Mode
           conversation             council_emit
           + Task actions               │
                 │                      ▼
         Redis event stream       Conduit Room (Git)
                 │                ├─ USER moderator
        NDJSON / consumers        ├─ SOL via input-only Edge
                                 └─ OPUS via Pydantic AI
                                      │
                                 Svelte UI

             Both reuse GPT Dive Runtime
        Execution / Task / TrackedTasks / SQLite
~~~

**Currently implemented:** `@c` actions with Redis event publication, and a Git-backed Room with SOL/OPUS delivery and local UI. A single web interface integrating the Room with the `@c` event stream is **not yet implemented**. Room Git history, Redis events, and Runtime SQLite state remain separate authorities.

**Room design invariant:** automate transport, not judgment. USER chooses each turn; SOL and OPUS may share context and disagree. Preserve the causes, constraints, and evidence behind decisions.

## Run and develop

~~~bash
# Local Conduit conversation/task MCP server
uv run --locked --no-sync python -m gpt_dive.conduit

# Build the shared room UI (Svelte/Vite)
cd web && pnpm run check && pnpm run build

# Serve a Git-backed room using the existing ChatGPT Web conversation
uv run --locked --no-sync python -m gpt_dive.conduit.room.server \
  --room-dir /path/to/existing/git-room \
  --sol-url '<exact ChatGPT Web conversation URL>'
~~~

The installed CLI name is `gpt-dive-conduit-room`. The older `gpt-dive-council` command and `--council-dir` argument remain accepted. Live `@c` and `council_emit` signatures are unchanged. Production operations and service restart instructions belong to [Runtime operations](../runtime/operations.md).

## Ownership

| Owner | Owns |
|---|---|
| GPT Dive Runtime | Execution, Task, SQLite state, TrackedTasks, deadlines and recovery |
| Conduit transport | `@c` conversation/task interface, Redis publication, event envelopes |
| Conduit Room | Shared USER/SOL/OPUS turns, Git transcript, context cursors, local UI |
| Redis / downstream consumers | Event fan-out and independent downstream storage |

Conduit does not duplicate Runtime's Task store. Git is authoritative for Room transcript content; SQLite owns Execution/Task lifecycle; Redis carries events.

## Documentation

| Purpose | Source |
|---|---|
| Room behavior, command, protocol | [Room README](room/README.md) |
| Room implementation record | [Room v1 spec](room/spec.md) (historical snapshot) |
| Council → Conduit design history | [Room history](room/history.md) |
| Room start/reopen UX direction | [Room startup](room/startup.md) (not fully implemented) |
| Conduit vocabulary and ownership | [CONTEXT](CONTEXT.md) |
| Original constraints, economics, proven components | [Bootstrap](bootstrap.md) |
| Conduit decisions | [Conduit ADRs](adr/) |
| Dated handoff and next product work | [CONTINUATION](CONTINUATION.md) |
| Redis/NDJSON event format | [NDJSON reference](ndjson-ref.md) |
| Tunnel and consumer service templates | [Runtime templates](runtime/) |

Current source and tests override historical plans and specs. Room code is in `src/gpt_dive/conduit/room/`; transport code is in `src/gpt_dive/conduit/`; the existing Room frontend stays in `web/`. Experiments and implementation history are grouped under `experiments/conduit/` and `plans/conduit/`.
