# GPT Dive Peer Review

> Status: **Draft / experimental**
> Updated: 2026-10-08
> Scope: GPT Dive implementation contract. Workflow policy SSOT is `~/wiki/skills/web/peer-review.md`.

## Purpose

GPT Dive exposes outer Code Mode `peer_review(...)` as the current peer-review lane:

```text
Web SOL
  -> code_mode(label="Peer review: …", delivery="task")
       -> Task / TrackedTasks awareness
       -> peer_review(alias, prompt, cwd)
            -> invoke_model_call(peer_review=True)
                 -> Pydantic Agent
                 -> independent review
```

Internal `invoke_model_call(..., peer_review=False)` remains available as a tool-less model call primitive. Anthropic-compatible exact model ids may be soft-verified against the provider `/v1/models` listing before inference; OpenAI Codex uses Pydantic AI's official provider contract.

## Implementation ownership

```text
src/gpt_dive/code_capabilities.py  Code Mode-facing peer_review(...) capability
src/gpt_dive/model_call.py      worker, reviewer instruction, capabilities, subprocess, usage
src/gpt_dive/model_registry.py  provider/model routing + model output-token metadata
```

Do not duplicate workflow policy here. Packet composition, approval gates, resend rules, and result consumption belong to the Wiki skill.

## Reviewer runtime

Peer-review mode gives the model scoped Harness capabilities:

```text
FileSystem(read/write, root=cwd, secret denies)
CodeMode
```

They are an **escape hatch**, not the normal packet transport. The normal path does not require the peer to read or write workflow files through model tool turns.

The reviewer instruction stays deliberately small: use the supplied packet as primary evidence, return the complete review in the final response, and use tools only when a material evidence gap genuinely blocks judgment.

## Two-file transport

Canonical workflow state is exactly:

```text
peer_packet.md  -> complete accumulated input
peer_answer.md  <- latest answer only
```

Normal path:

```text
host local read peer_packet.md
        ↓
peer_review(alias=<approved registry alias | provider:model | provider-default>, prompt=<complete packet>)
        ↓
peer final review text
        ↓
host local write peer_answer.md
```

Local packet reads and answer writes add **zero provider round-trips**. In Monty, use `await read_file(...)` (raw by default per ADR 0011) for packet transport. Do not use `Path.read_text()`, `open()`, or other CPython filesystem APIs. Only use `read_file(..., line_numbers=True)` when formatted line-number inspection is explicitly required.

For another round:

```text
peer_answer.md -> append to peer_packet.md
peer_answer.md -> delete
new evidence/question -> append to peer_packet.md
resend the complete peer_packet.md
```

There is no round-file tree, recovery state, reconstructed conversation, or additional history store.

## Why host-local output write

A 2026-08-21 live low-cost peer-model test first let the reviewer write the output file itself. The model returned `completed`, but `peer_answer.md` did not exist afterward:

```text
model             claude-haiku-4-5
provider requests 3
input tokens      9,197
output tokens       732
model final        completed
answer file        missing
```

The normal path was therefore simplified: the reviewer returns review text; outer Code Mode persists it locally.

With that change, the same live route used one provider request:

```text
Round 1
provider requests 1
input tokens      2,584
output tokens       177
result             correct rejection of price + qty vs required price * qty

Round 2 after answer -> packet rollover
provider requests 1
input tokens      2,845
output tokens       191
result             correctly updated judgment after requirement changed to price + qty
```

This is the current acceptance evidence for the two-file transport.

## Token settings

Peer review does not set a default `max_tokens` or `UsageLimits.output_tokens_limit`: the Pydantic AI model and provider determine request defaults. The outer `peer_review(...)` capability does not expose a caller-supplied token limit.

Other model call interfaces may pass an explicit `output_tokens_limit` to Pydantic AI `UsageLimits`; no model-specific limit is automatically injected.

## Current peer aliases

## Reviewer selection boundary

The user chooses the provider and model. SOL resolves that choice before approval without substitution. The current outer capability accepts one `alias` argument: a registry alias, `provider:model`, or provider default. For exact user-selected routes, prefer `provider:model`. Anthropic-compatible routes may soft-check `/v1/models`; OpenAI Codex uses Pydantic AI's official subscription provider contract.

## Cache

Cache behavior is provider economics, not workflow architecture.

- Kunavo has shown useful repeated-prefix cache reuse in local testing.
- AIAPIFLOW previously showed unreliable useful-prefix reuse.
- A cache hit may reduce cost, but a miss does not trigger recovery/fallback logic.

The two-file workflow stays the same either way. Current provider economics belong in the user/provider docs and provider-lab evidence.

## Canonical outer Code Mode shape

The Wiki skill owns the full commented sample. Implementation shape is:

```python
packet = await read_file(path="peer_packet.md")
if not packet.strip():
    raise RuntimeError("peer_packet.md is empty")

# The Wiki workflow re-checks the recorded packet identity before this call.
result = await peer_review(
    alias="provider:model",  # or an explicitly approved registered alias
    prompt=packet,
    cwd=CWD,
)

# Persist outside the paid call after inspecting the returned result shape.
```

The actual paid route runs only in an outer `code_mode(label="Peer review: …", delivery="task")` call after the skill's provider/model preflight and explicit user approval gate. The outer call returns the Execution's single `execution_id`; Web SOL continues its own work and ordinary GPT Dive traffic surfaces the review through TrackedTasks. `task(get)` reads the result non-destructively, `task(cancel)` is the explicit cancellation path, and `task(dismiss)` removes terminal awareness after handling. No peer-review-specific tracker or execution runtime is added. `peer_review` has no caller-supplied timeout; exact capability ceilings and child budgets are Runtime-owned and must be read from the current live contract rather than copied into workflow docs.

## Failure semantics

- No provider/model fallback.
- No synchronous fallback for `/peer-review`.
- Preserve full failure diagnostics from `peer_review(...)`.
- `finish_reason == "length"` is reported as truncated / unsuccessful.
- Secret/credential paths remain denied inside the peer FileSystem.
- Missing evidence should normally become a focused next-packet request rather than an automatic exploratory premium loop.

## References

- Workflow SSOT: `~/wiki/skills/web/peer-review.md`
- Design rationale: `~/wiki/skills/web/peer-review-adr.md`
- Model routing: `~/gpt-dive/src/gpt_dive/model_registry.py`
