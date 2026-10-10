# Conduit Room

**Conduit's human-steered shared multi-model discussion feature**, originally named Council. It removes manual message relay between USER, Web SOL, and an OPUS reviewer without automating decisions.

~~~text
USER chooses the recipient
    │
    ├─ SOL → input-only Edge / Playwright → existing ChatGPT Web
    │                                      └─ code_mode: council_emit
    └─ OPUS → Pydantic AI → approved opus-5-micu model
                   │
                   ▼
           Git-backed room
       init.md + append-only chat.md
       + refs/council/context/{sol,opus}
                   │
                   ▼
               Svelte UI (web/)
~~~

The Git transcript is chronological, and participant cursors advance after successful turns. `init.md` supplies why the room exists; `chat.md` preserves the USER/SOL/OPUS discussion. Browser automation is **input-only**; a Git commit after `council_emit` confirms SOL output, not DOM scraping.

## Run a room

~~~bash
cd web && pnpm run build
gpt-dive-conduit-room --room-dir /path/to/existing/git-room \
  --sol-url '<exact existing ChatGPT Web conversation URL>'
~~~

The Room server exposes `/api/state`, `/api/turn`, and `/api/retry` alongside the UI. Its canonical Python implementation is `gpt_dive.conduit.room` with the `ConduitRoom` server class.

**Compatibility:** `gpt-dive-council --council-dir` maps to the same server. The existing Git refs, `initialize_council`, `CouncilProtocolError` and `council_emit(council_dir=...)` stay unchanged to protect older room repositories and the current MCP contract. No room-data migration is performed.

## Invariants

- **Human steering:** USER selects each turn; no autonomous SOL ↔ OPUS loop.
- **Judgment independence:** participants share evidence without forced agreement.
- **Preserve why:** constraints, dissent, rejected approaches and changed evidence stay in the transcript.
- **Explicit ownership:** Git owns Room content; SQLite owns Runtime Task lifecycle.
- **SOL stays in ChatGPT Web:** the server does not instantiate a replacement model.

## References

| Document | Role |
|---|---|
| [Conduit](../README.md) | Product architecture and event transport |
| [Room history](history.md) | Council origins, rejection history and rationale |
| [Room v1 spec](spec.md) | Historical implementation and acceptance record |
| [Start/reopen direction](startup.md) | Future usability improvements, not delivered |
| [Chat/session investigation](chat-session-context.md) | Historical OPUS context investigation |
| [Web SOL experiment](../../../experiments/conduit/room_web_sol_e2e/README.md) | Proven Edge input / MCP+Git output boundary |
| [Implementation tickets](../../../plans/conduit/room/2026-08-12-council-v3-tickets.md) | Historical completed steps |

The Room UI and `@c` event stream are currently separate entrypoints. A single Conduit UI is a future integration, not current behavior.
