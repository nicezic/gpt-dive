# Council Chat / Session Context Architecture

> Status: **draft issue / design investigation**
> Discovered: 2026-08-13
> Scope: AI chat/session context fundamentals, Pydantic AI/Harness mechanisms, and the Council OPUS participant path.
> This document is **not** an implementation spec or an approved migration plan.

## Why This Is a Real Architecture Issue

Council looks like a simple human-steered three-party chat room:

```text
USER / SOL / OPUS
       -> one chronological Council conversation
```

But an LLM does not inherently own a durable chat session. At inference time the model receives a context and produces a response. The product or harness around the model must decide how conversation state is stored, reconstructed, compacted, cached, and resumed.

That makes a long-running AI chat more than a UI concern. It affects:

- input-token growth and cost;
- prompt-cache effectiveness;
- context-window pressure;
- stale or contradictory reasoning remaining in context;
- process restart / resume behavior;
- provider portability;
- what is authoritative durable history versus disposable model working state.

The issue is especially important for Council because SOL and OPUS currently have **different context transports**.

## 1. Basic Mental Model: LLM vs Chat Session

### LLM inference

A simplified model call is:

```text
current input/context
        |
        v
      model
        |
        v
     output
```

The neural model itself does not need a product-level `session_id` to generate a response.

### Chat / session

A chat product adds a state-management layer around repeated model calls:

```text
persistent conversation state
        |
        +-- prior USER messages
        +-- prior AI responses
        +-- tool calls/results
        +-- instructions / relevant files
        |
        v
context construction
        |
        v
      model
```

Therefore "the AI remembers the conversation" usually means that a client, harness, or provider reconstructs enough prior state for the next inference.

### Terms that must not be collapsed into one idea

| Term | Meaning |
|---|---|
| **Transcript** | Durable chronological record of what participants actually said/did. |
| **Model context** | The tokens/items actually available to the model for the current inference. |
| **Chat/session** | Application-level continuity across multiple model calls. |
| **Prompt cache** | Reuse of an unchanged prompt prefix to reduce repeated processing/cost; it is not durable conversation memory. |
| **Compaction** | Rewriting/trimming/summarizing accumulated working history so later model calls stay bounded. |
| **Provider-native conversation/state** | Server-side continuation mechanism supplied by a provider, when that API supports it. |
| **Pydantic `conversation_id`** | Conversation correlation identity carried across Pydantic message history; by itself it is not a magic server-side history store. |

## 2. Why Long Chats Become Expensive and Noisy

If every follow-up call replays the growing conversation, one turn can conceptually look like:

```text
USER 1
AI 1
USER 2
AI 2
...
USER N
        |
        v
     next call
```

So the current user message may be tiny while the actual model input is large.

If turn sizes are roughly stable and the complete history is replayed each time:

- per-turn input grows approximately linearly with conversation length;
- cumulative input across many turns can grow approximately quadratically;
- old rejected ideas, corrections, and obsolete tool output remain potential context noise unless managed.

A 1M-token context window therefore gives **capacity**, not automatically clean reasoning or cheap continuation.

## 3. What Pydantic AI Already Provides

Pydantic AI provides the building blocks for chat continuity, but the application still chooses the persistence and context policy.

### 3.1 Message history

`Agent.run*()` accepts `message_history` for continuing a coherent conversation.

Results expose:

- `all_messages()` / `all_messages_json()`;
- `new_messages()` / `new_messages_json()`.

Basic shape:

```python
result1 = await agent.run("first turn")
result2 = await agent.run(
    "next turn",
    message_history=result1.all_messages(),
)
```

This is ordinary **client/harness-managed chat continuity**. Previous USER and model-response messages are part of the reusable history.

### 3.2 `run_id` vs `conversation_id`

Pydantic messages carry both:

- `run_id`: unique per agent run;
- `conversation_id`: inherited across runs that build on the same `message_history`.

`conversation_id` is useful for correlation, tracing, and application thread identity. Continuity still depends on the history round-trip unless a provider-specific server-side continuation mechanism is explicitly used.

### 3.3 History processing

`ProcessHistory` can modify the history before each model request. Documented uses include:

- keep only recent messages;
- redact content;
- summarize older messages;
- custom cost/context policy.

For richer control, the same lifecycle can be implemented with `before_model_request` hooks.

### 3.4 Anthropic prompt caching

Pydantic AI exposes Anthropic cache controls including:

- `anthropic_cache=True` for automatic caching where the provider supports it;
- `anthropic_cache_messages=True` for Anthropic-compatible gateways/proxies that accept per-message cache control but not the top-level automatic form;
- explicit `CachePoint` markers;
- cache usage via normalized `cache_read_tokens` / `cache_write_tokens`.

This can make a growing chat much cheaper **when the gateway actually supports and bills cache reuse correctly**. It does not replace persisted conversation history.

### 3.5 Provider-native continuation is provider-specific

Pydantic AI also supports OpenAI Responses-specific server-side mechanisms such as:

- `openai_previous_response_id`;
- `openai_conversation_id`;
- OpenAI server-side compaction.

These demonstrate that server-side continuation is possible, but they are **OpenAI-specific mechanisms** and should not be assumed to exist on an Anthropic-compatible OPUS gateway.

### 3.6 Pydantic AI Harness context controls

The Harness already provides context-management pieces relevant to a future Council OPUS implementation:

- `TieredCompaction`;
- `SlidingWindowCompaction`;
- `ClearToolResults`;
- `DeduplicateFileReads`;
- `SummarizingCompaction`;
- `ReportContextUsage`;
- `WarnOnCacheBusts`.

Important property: Harness compaction edits the **model working history**. Council can keep the full raw `chat.md` and Git history untouched while giving OPUS a smaller working context.

## 4. Current Council Context Architecture

Council's durable room record is:

```text
init.md
chat.md
Git commits
refs/council/context/sol
refs/council/context/opus
```

The Git participant refs are synchronization cursors: **what Council transcript each participant has consumed**. They are not model-native session state.

### SOL today

SOL is the existing ChatGPT Web conversation.

`src/gpt_dive/council/sol.py` sends only the unread Council transcript suffix to that existing Web conversation:

```text
existing ChatGPT Web SOL context
             +
     new unread Council suffix
```

ChatGPT Web owns SOL's native chat/session continuity outside Council.

### OPUS today

OPUS is different.

`src/gpt_dive/council/opus.py::_build_opus_task()` currently constructs each OPUS task from:

```text
init.md
+
previously synchronized Council transcript
+
new unread Council transcript
```

`src/gpt_dive/subagent_runtime.py` starts a child worker process for each call, and `src/gpt_dive/subagent_worker.py` creates a fresh `Agent(...)` and performs a fresh `agent.run(task)`.

Current OPUS path does **not** pass a persisted Pydantic `message_history` between Council turns.

The current `opus5` registry entry builds a plain `AnthropicModel` through the AIAPIFLOW Anthropic-compatible endpoint. No Council/registry/worker `AnthropicModelSettings` cache option is currently configured in this path.

Therefore the current logical flow is approximately:

```text
OPUS turn 1: init + transcript through turn 1
OPUS turn 2: init + transcript through turn 2
OPUS turn 3: init + transcript through turn 3
...
```

The Git OPUS cursor prevents transport synchronization mistakes, but it does **not** prevent the already-known transcript from being placed in the next fresh OPUS prompt again.

## 5. Why This Matters for Council

This is not merely a token-billing optimization.

### Cost

A long Council can repeatedly charge/process a large prefix. Prompt caching could reduce this materially, but only if the actual provider supports it and the prefix remains cacheable.

### Context quality

Council intentionally preserves why, disagreement, rejected alternatives, and changed positions. That durable raw history is valuable evidence, but it does not follow that **every old raw turn should remain in every OPUS inference forever**.

### Restart / resume

A useful Council room should survive process restart. A persistent OPUS working conversation therefore needs either:

- application-persisted Pydantic message history;
- a verified provider-native continuation mechanism;
- or a deterministic rebuild path from Council's durable Git transcript.

### Separation of truth and working memory

The clean architecture is likely to keep these distinct:

```text
Council Git room
= durable canonical transcript / evidence

OPUS working history
= optimized model context that may be cached, trimmed, or compacted
```

Loss or compaction of OPUS working history must never erase Council's durable reasoning record.

## 6. Draft Direction for the OPUS Participant

This is a candidate direction, not yet an approved design.

### Goal

Make OPUS behave like a persistent Council participant instead of a sequence of unrelated one-shot prompts, while keeping Git as the durable room authority.

### Candidate basic flow

```text
first OPUS turn
    init.md + unread Council transcript
            |
            v
       Pydantic Agent
            |
      persist history
            |
            v
       OPUS response
            |
       append to Git
            |
       advance cursor

later OPUS turn
    load persisted Pydantic history
            +
      unread Council suffix only
            |
            v
       Pydantic Agent
            |
      persist new history
            |
            v
       OPUS response
```

Because the OPUS Git cursor advances through its own committed response, the next unread Council suffix should contain only material that arrived **after** the history OPUS already owns. This gives a natural anti-duplication boundary if implemented carefully.

### Persistence candidates

Evaluate, do not pre-select:

1. **Pydantic message-history persistence per Council room**
   - serialize/restore model messages across worker processes;
   - provider-independent baseline;
   - application controls retention and recovery.

2. **Verified provider-native continuation**
   - only if the selected OPUS provider actually exposes a durable continuation API compatible with our needs;
   - do not infer this from a provider response ID or a Pydantic `conversation_id` alone.

3. **Hybrid**
   - local durable Pydantic history as recoverable truth for the model lane;
   - provider prompt cache/server state used opportunistically for efficiency.

### Prompt-cache work

For the current Anthropic-compatible path:

- probe AIAPIFLOW/Kunavo behavior rather than assume official Anthropic semantics;
- compare `anthropic_cache=True` vs `anthropic_cache_messages=True` where accepted;
- record `input_tokens`, `cache_read_tokens`, `cache_write_tokens`, and billed provider usage;
- keep stable instructions/history prefixes byte-stable where practical;
- optionally add `WarnOnCacheBusts` after cache behavior is proven.

### Context management / compaction

Do **not** start by deleting Council history.

Instead separate:

```text
raw Council transcript: never compacted away
OPUS working history: may be compacted when justified
```

Candidate later policy:

1. avoid duplication first;
2. enable/verify prompt caching;
3. report working-context usage;
4. only then add cheap structural compaction;
5. summarize old model history only when cheaper/lossless methods are insufficient.

This matches the local Harness context-economics guidance: prevent unnecessary context first, clear/dedupe stale material second, summarize last.

## 7. Minimum Investigation / Acceptance Questions

Before implementation design is considered settled, answer these with evidence:

1. **History round-trip** — can one OPUS Council conversation be serialized, process-exited, restored in a new process, and continued with Pydantic `message_history` without semantic duplication?
2. **Git/history alignment** — can the OPUS Git cursor and persisted Pydantic history be proven to represent the same synchronization boundary?
3. **Recovery** — if OPUS working history is lost/corrupt, can it be rebuilt from `init.md + chat.md` without altering the Council record?
4. **Provider cache reality** — which OPUS providers accept which Anthropic cache mode, and what do they actually report/bill for cache read/write?
5. **Token curve** — measure current one-shot replay versus persistent history + cache across a multi-turn synthetic Council.
6. **Restart behavior** — restart Council/backend/worker processes and verify OPUS continues the same logical conversation.
7. **Compaction boundary** — if compaction is added later, prove it only changes OPUS working context and never rewrites `chat.md` / Council Git history.
8. **Provider portability** — identify which parts are generic Pydantic chat state and which are provider-specific optimizations.

## 8. Work Size / Boundaries

This should not be treated as a small patch such as "add a session ID".

It contains at least three separate concerns:

```text
A. Chat/session semantics
   transcript vs model context vs session vs cache

B. Pydantic runtime design
   message persistence / resume / history processing / compaction

C. Provider economics
   Anthropic-compatible cache support / TTL / billing / behavior
```

The current document only **makes the issue explicit and maps the solution space**. A concrete implementation should get its own plan/spec only after the investigation questions above resolve the material design choices.

Keep this issue in this single document until that design stabilizes; do not split AI session basics, Pydantic chat mechanics, and Council OPUS work into parallel notes.

## 9. Primary References

### Pydantic AI Core

- `~/ref/pydantic-ai/docs/message-history.md`
  - messages, `message_history`, JSON serialization, `run_id`, `conversation_id`, history processing.
- `~/ref/pydantic-ai/docs/capabilities/process-history.md`
  - `ProcessHistory` capability.
- `~/ref/pydantic-ai/docs/models/anthropic.md`
  - Anthropic prompt caching, gateway-compatible per-message caching, cache usage.
- `~/ref/pydantic-ai/docs/models/openai.md`
  - provider-native continuation examples (`previous_response_id`, durable conversations) and server-side compaction; useful as a contrast, not as an OPUS assumption.

### Pydantic AI Harness

- `~/ref/pydantic-ai-harness/docs/compaction.md`
  - working-history compaction strategies and `ReportContextUsage`.
- `~/ref/pydantic-ai-harness/docs/warn-on-cache-busts.md`
  - cache-hit collapse observation.
- `~/wiki/pydantic/handbook/context-state.md`
  - local verified context-economics guidance and experiments.

### Current Council implementation

- `src/gpt_dive/council/opus.py`
- `src/gpt_dive/council/sol.py`
- `src/gpt_dive/council/repo.py`
- `src/gpt_dive/subagent_runtime.py`
- `src/gpt_dive/subagent_worker.py`
- `src/gpt_dive/model_registry.py`
- `docs/council/README.md`
- `specs/council.md`
