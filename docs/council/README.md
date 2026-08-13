# Council

> Current product/architecture map for GPT Dive Council.
> Implementation SSOT: `../../specs/council.md`
> Historical reasoning: `history.md`
> Start/reopen direction: `startup.md`

## What Council Is

Council is a **human-steered shared discussion room** for difficult design, debugging, research, and technical decisions.

```text
USER = moderator / domain owner
SOL  = Web ChatGPT primary engineer
OPUS = independent peer through Pydantic AI

USER / SOL / OPUS
       -> one chronological Council conversation
```

The user chooses who speaks next. Council automates transport and durable context, not judgment.

Core principles:

- **Shared Context** — participants can see the same Council reasoning timeline.
- **Judgment Independence** — seeing another opinion does not imply following it.
- **Preserve Why** — keep causes, constraints, rejected alternatives, disagreement, and evidence that changed positions.
- **Human Controls Turns** — no autonomous SOL ↔ OPUS debate loop.
- **Raw reasoning first** — no automatic transcript summarization/compression in v1.

## Current Delivered Architecture

```text
Council UI (Svelte 5)
       │
       ├─ To SOL
       │    -> persistent input-only Playwright / Edge CDP
       │    -> existing ChatGPT Web SOL conversation
       │    -> code_mode -> council_emit
       │
       └─ To OPUS
            -> Pydantic AI `opus5`

Both paths
   -> append-only chat.md
   -> one Git commit per speaking event
   -> participant context cursor advances after successful response
```

Durable room state:

```text
init.md
chat.md
.git/commits
refs/council/context/sol
refs/council/context/opus
```

`chat.md` remains deliberately dumb and human-readable. Protocol state lives in Git, not in Markdown metadata or role-heading parsing.

## Context Model

Logical Council context is:

```text
initial causal context in init.md
+
chronological USER / SOL / OPUS reasoning in chat.md
```

Physical transport may send only the unread transcript suffix because participants already have native/model history. The Git refs identify the synchronization boundary.

The important unit is not merely a decision. It is:

```text
proposal / conclusion
+
reason
+
constraint
+
material disagreement
+
rejected alternative
+
evidence that changed the position
```

## Web SOL Boundary

The real SOL remains the **existing ChatGPT Web conversation**. It is not recreated inside Pydantic.

```text
Input to SOL : Council backend -> Playwright/CDP -> ChatGPT composer
Output from SOL: Web SOL -> MCP/code_mode -> council_emit -> Git
```

Playwright is input-only. It does not scrape assistant output, inspect streaming completion, click Copy, or read the clipboard. A successful SOL Git commit is the local completion event.

## Opus Boundary

OPUS is invoked through the local Pydantic path. Current Council uses model alias `opus5`; provider routing remains owned by GPT Dive's model registry.

The peer is valuable because it brings independent judgment, not because it is forced to disagree. Earlier Council experience showed that a strong reviewer can challenge the wrong problem when causal context is incomplete. This is why startup context quality matters.

## User Experience

After Council is running, the user stays on the local Council page:

```text
[ message ................................ ]
              [ To SOL ] [ To OPUS ]
```

The ChatGPT Web SOL tab stays open in the background as a participant runtime.

The delivered v1 CLI is still:

```text
gpt-dive-council --council-dir <path> --sol-url <exact ChatGPT conversation URL>
```

Reducing that manual startup/reopen friction is the current next product step. See `startup.md`.

## Documentation Map

- `README.md` — this compact current architecture map.
- `history.md` — causal evolution and rejected/changed directions.
- `startup.md` — approved post-v1 startup/reopen direction; not yet delivered runtime behavior.
- `chat-session-context.md` — design issue: AI chat/session fundamentals, Pydantic/Harness mechanisms, and the Council OPUS context architecture draft.
- `../../specs/council.md` — Council v1 implementation/decision SSOT and acceptance evidence.
- `../../plans/council/2026-08-11-web-sol-e2e.md` — Web SOL transport feasibility evidence.
- `../../plans/council/2026-08-12-council-v3-tickets.md` — completed v1 implementation tickets.
- `../../CONTINUATION.md` — fresh-session live handoff.

## Status

Council v1 is implemented and FULL PASS. Start/reopen ergonomics are the active next design/implementation area.
