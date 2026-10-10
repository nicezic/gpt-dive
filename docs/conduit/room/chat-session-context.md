# Conduit Room — OPUS Chat Context Investigation

> **Open design question, not an approved implementation.** Originally discovered 2026-08-13 as Council's long-running chat/session issue.

## Problem

A model receives inference context but does not automatically own a durable **chat session**. Room has two distinct channels:

~~~text
Web SOL: existing ChatGPT Web native conversation
OPUS:    independent Pydantic AI worker invocation
                       │
Git Room transcript (authoritative append-only history)
                       │
               participant context cursors
~~~

Rebuilding `init.md + chat.md` every turn ensures correctness, but history grows, affects input cost/prompt cache, and can include stale reasoning. SOL's Web-native history and OPUS's worker prompts are not symmetrical.

| Concept | Meaning |
|---|---|
| Transcript | Durable record of exactly what was said (Git), not a working prompt |
| Model context | Actual messages/tokens supplied for one inference |
| Chat/session | Client/harness continuity between model calls |
| Prompt cache | Provider-side reuse of prompt prefixes; not durable conversation storage |
| Compaction | Optional alteration of working context, never deletion of room history |
| `conversation_id` / `run_id` | Correlation identifiers; not proof of provider-native durable history |

## Proposed evaluation (not implemented)

For OPUS, investigate storing/restoring Pydantic AI `message_history` between worker lifetimes and sending only the unread Git suffix. The `refs/council/context/opus` cursor must match the model history through the same committed response. As alternatives, test provider-native continuation **only where verified**, or use local model history plus optional provider cache.

Order of optimizations: **dedupe context → verify cache behavior/token costs → measure context size → compact working history only when justified**. Provider compatibility and Anthropic-style cache read/write billing must be probed on the actual routed provider, not assumed.

## Acceptance questions

1. Can history round-trip through process restart and preserve semantics?
2. Does Pydantic history align exactly with the Git cursor after success/failure/retry?
3. Can corrupt model history be rebuilt from `init.md + chat.md` without changing the transcript?
4. What continuation/cache semantics does each actual OPUS provider support, and what does it bill?
5. Do multi-turn token/cost curves improve without introducing stale or duplicate context?
6. Does any compaction affect **only** ephemeral model working state, never durable Git dialogue?

The current room preserves the Git transcript and reconstructs prompt context when calling OPUS. This note does **not** authorize implementing a new database, autosummarizer, or speculative session framework. See [Room spec](spec.md) and `src/gpt_dive/conduit/room/opus.py`.
