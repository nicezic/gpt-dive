# Conduit Room — Council v1 Acceptance Record

> Historical implementation record, **2026-08-12**. The feature was originally called Council. For current commands, module paths and runtime contracts use [Room README](README.md), not this snapshot.

## Purpose / why

The USER already moderated technical discussions by relaying messages between Web SOL and independent OPUS. The proven value was **judgment independence with a shared context**, not hiding another participant's reasoning. The pain was copying arguments between conversations, so the design automated **transport, not judgment**, and preserved reasons, dissent and rejected options.

~~~text
USER controls To SOL / To OPUS
     │
     ├─ SOL via input-only Playwright / existing Web ChatGPT
     └─ OPUS via local Pydantic AI
                  │
                  ▼
         append-only chat.md + Git commit
                  │
       refs/council/context/{sol,opus}
~~~

## Accepted decisions

| Design | Why / rejected alternative |
|---|---|
| One USER/SOL/OPUS transcript | Separate private lanes added routing, relay and hidden-visibility complexity |
| `init.md` + append-only `chat.md` + Git commit per turn | Git provides human-readable durable timeline; no second room DB needed |
| Explicit `refs/council/context/sol` and `opus` | Participant's known history cannot be inferred from last speaker heading |
| Unread content = pure `chat.md` suffix from cursor snapshot | `git diff` patch syntax is not a conversation; refuse non-append edits |
| Advance cursor only after successful response commit | Delivery failures must not discard unread context |
| Web SOL input via Edge/CDP, output via `council_emit` | DOM scrape/copy and stream polling are unreliable; completion is Git commit |
| Exact composer READY gate, persistent browser session | Prevent double sends and repeated approval prompts |
| `expected_head` for SOL emissions | Reject late/duplicate commits to the wrong Git parent |
| OPUS reconstructs synchronized history + unread suffix | Worker calls do not retain a durable provider-native chat session |
| Svelte 5 + Vite + Starlette REST | One shared room needs no additional SPA/backend framework or WebSocket |

## Failure / retry invariants

- Git dirty/non-append state is an error, not an opportunity to repair history silently.
- Web SOL input errors, missing response commit and provider failures **do not advance** the participant cursor.
- Retry the same pending participant turn without adding a duplicate USER commit; a late SOL Git response is reconciled before re-sending.
- Room Git log is authoritative for dialogue, separate from GPT Dive Runtime's Execution/Task SQLite authority.
- Playwright stays input-only; independent participant judgment is not an autonomous AI debate loop.

## Delivered historical validation

Council v1 passed Python/room protocol tests, real OPUS review, Svelte UI build/E2E and real Web SOL input→MCP→Git output on 2026-08-12. Key implementation deviations: the SOL bridge has explicit lifecycle rather than generic ten-minute detached timeout; REST instead of WebSocket; `council_emit(expected_head=...)` handles races; port 8791 avoided an occupied local port; Git CLI was preferred over another Git library.

The original implementation tickets and Web SOL proof remain in [plans](../../../plans/conduit/room/2026-08-12-council-v3-tickets.md) and [experiment](../../../experiments/conduit/room_web_sol_e2e/README.md); the complete 2026-08-12 specification is recoverable in Git history.

## Deferred

Room creation/reopen, cross-turn OPUS working-memory persistence, context compaction, multi-room navigation, an integrated `@c` event UI and any autonomous discussion workflow **were not delivered** by v1. See [startup](startup.md) and [chat context issue](chat-session-context.md) for the remaining questions.
