# GPT Dive — Current Continuation

> Updated: 2026-08-12
> Purpose: compact fresh-session handoff only. Durable Why/history belongs in `docs/`; implementation artifacts belong in `plans/` and `specs/`.

## Current Position

- **v1 Local MCP Runtime**: stable
- **v2 Pydantic AI Harness**: stable and extensible
- **v3 Council**: design converged enough to enter `to-spec`; implementation has not started
- Last verified local suite before this cleanup: **39 passed**

## Stable Web MCP Surface

Exactly four top-level tools:

```text
bootstrap
code_mode
wsl2_sync
wsl2_async
```

`code_mode` remains the primary execution root. Current registry includes local sync/durable execution, subagent support, `gz64`, and the experimental `council_emit` transport capability.

## Council — Current Decisions

Feature name: **Council**. Korean "회의" / "카운실" / `Council` all refer to the same workflow.

Current mental model:

```text
Shared Council Room
USER = moderator / domain owner
SOL  = primary engineer
OPUS = independent peer
```

Principles:

- **Shared Context** — participants reason over the chronological Council conversation.
- **Judgment Independence** — seeing another participant's argument does not imply agreeing with it.
- **Preserve Why** — keep causal context, disagreement, rejected alternatives, and reasons behind changed decisions.
- **Human Controls Turns** — automate transport, not judgment.
- **No premature summarization** in early v3.

Current minimal storage direction:

```text
init.md
chat.md
.git/commits
refs/council/context/sol
refs/council/context/opus
```

`chat.md` stays append-only and human-readable. Git refs represent participant context cursors; do not infer transport state by parsing the last role heading.

## Verified Web SOL Transport Probe

**FULL PASS**:

```text
local Council input
  -> persistent Playwright / Edge CDP
  -> real ChatGPT Web SOL
  -> code_mode -> council_emit
  -> chat.md
  -> Git commit
```

Playwright is input-only. No assistant-output scraping, Copy button, clipboard extraction, or DOM completion detection is used.

Persistent CDP removed repeated Edge approval prompts. The generic async-job default timeout of 600 seconds was too short for the bridge, so final bridge lifecycle remains a v3 spec/implementation decision.

Evidence: `plans/council/2026-08-11-web-sol-e2e.md`.

## UI Decision

Council Web UI stack is decided:

```text
Svelte 5 + Vite + TypeScript
```

Planned location: top-level `web/` rather than inside the Python `src/` package.

## Current Task Boundary

Pre-v3 documentation restructure is the current cleanup step.

Next workflow after cleanup:

```text
Matt-P to-spec
  -> specs/council.md
  -> User + SOL + Opus review
  -> to-tickets
  -> v3 implementation
```

Do **not** create the Council spec during the cleanup commit.

## Key Documents

```text
docs/runtime/architecture.md
docs/runtime/history.md
docs/runtime/operations.md
docs/council/history.md
plans/council/2026-08-11-web-sol-e2e.md
```

## Runtime Reload Rule

Do not restart the active MCP service inline during its own in-flight call. When live reload is needed, schedule the restart out-of-band with the documented 5-second buffer. See `docs/runtime/operations.md`.
