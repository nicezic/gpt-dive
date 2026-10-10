# Conduit Room — Start/Reopen Proposal

> **Approved direction, not a delivered one-click workflow.** The existing CLI is `gpt-dive-conduit-room --room-dir <path> --sol-url <exact ChatGPT conversation URL>`; legacy `gpt-dive-council --council-dir` still works.

## Why

Room v1 proved Git conversation, OPUS review and Web SOL input/output. Startup still requires manually choosing/creating a Git room, writing `init.md`, locating the exact **existing** ChatGPT Web SOL conversation, starting the server and opening the UI. Never create a replacement SOL chat merely to simplify startup: the current conversation already holds the causal context.

~~~text
existing ChatGPT Web SOL
     │ reconstruct relevant why/constraints
     ▼
init.md + Git room (proposed ~/conduit/rooms/<YYMMDD-title>/)
     │
     ▼
Room lifecycle capability behind code_mode (future)
     │
     ├─ init / reopen Git state
     ├─ attach exact existing SOL conversation
     └─ start server + local UI
~~~

The room root is a *proposed new-room convention*, not an implemented auto-migration. Existing `~/council/` Git rooms and `refs/council/context/*` remain valid and must not be silently relocated.

## `init.md` minimum content

- **Why:** what event, user constraint and real pain caused the room to exist.
- **Background/current reality:** actual code, tools, verified facts and model economics (with sources).
- **Question/goal:** concrete decision to be reached; how success is recognized.
- **Constraints and settled decisions:** requirements, discarded alternatives and reasons, open uncertainties.

Keep `init.md` a **starting causal snapshot**. New evidence and changed judgment belong in `chat.md` plus the Git timeline rather than silently rewriting history. A reviewer may ask for missing real-world constraints first: missing Why once caused a competent Council reviewer to reject the wrong problem.

## Reopen considerations

~~~text
same Web SOL conversation → use existing native context and unread Git suffix
new Web SOL conversation  → hydrate context from init.md + needed chat.md
OPUS subprocess          → reconstruct model working context from Git cursors
~~~

Advance `refs/council/context/{sol,opus}` **only after successful participant response commits**. Do not manufacture synchronization by advancing on dispatch or first token. A failed/uncertain response requires Git evidence checks before retry; a late SOL response may already have committed.

## Boundaries

- Implement reproducible mechanics behind Code Mode without adding a fifth public MCP tool or a generic orchestration framework.
- The USER/active SOL authors the **meaning** of `init.md`; lifecycle code owns deterministic Git/process/browser steps.
- Respect the existing input-only Edge/Playwright path. Browser scraping is not a completion detector.
- Start/reopen and future `@c`/Room UI integration are separate backlog items.

**Current manual baseline:** build `web/`, run `gpt-dive-conduit-room` against an existing Git room, and use the local server (default port 8791). See [Room README](README.md) for the runnable command.
