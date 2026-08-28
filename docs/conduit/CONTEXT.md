# Conduit Context

Conduit is the thin conversation and asynchronous-work control protocol between ChatGPT Web SOL and the user's local system. This file owns Conduit-specific canonical language only; implementation decisions belong elsewhere.

## Language

**Mirrored Full Output**:
The same complete assistant answer is sent through Conduit to the local output/event path and also returned unchanged as the native ChatGPT Web assistant final for that real user turn. The two copies are intentionally identical so myWeb can receive the full answer without sacrificing ChatGPT's normal conversation history.
_Avoid_: mirrored answer, duplicate answer, double output when referring to this specific protocol behavior.

**Turn Marker**:
A monotonically increasing integer appended as the final line of each Mirrored Full Output. A new ChatGPT conversation starts at `1` on its first real user turn; each subsequent real user turn increments it by one. Tool calls and `@c` calls do not affect the count.

**TrackedTasks**:
The GPT Dive Runtime-owned compact projection of unhandled Tasks that Conduit surfaces through `@c`; Conduit consumes this shared concept rather than owning a separate task-tracking domain. Canonical definition: `../runtime/CONTEXT.md`.
_Avoid_: Conduit task list, Conduit-owned tracking when referring to the shared Runtime projection.

**Opportunistic Evidence Pickup (OEP)**:
The workflow in which Web SOL launches Task-backed asynchronous work without waiting, continues its own reasoning, later notices completion through TrackedTasks during ordinary tool activity, and inspects the result only when useful. Worker output is candidate evidence rather than authority, so pickup may end in discard, deduplication, or selective use.

**Conduit Action**:
One strict `@c` request variant: `start`, `sync`, `get`, `cancel`, `dismiss`, or `emit`. Runtime lifecycle actions use the shared `execution_id`; Conduit does not translate it into a second Task identity.
_Avoid_: collect/ack when referring to the current get/dismiss contract; `task_id`.
