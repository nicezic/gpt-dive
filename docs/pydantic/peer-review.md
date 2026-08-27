# GPT Dive Peer Review

> Status: **Draft / experimental**
> Updated: 2026-08-21
> Scope: GPT Dive implementation contract. Workflow policy SSOT is `~/wiki/skills/web/peer-review.md`.

## Purpose

GPT Dive exposes outer Code Mode `peer_review(...)` as the current peer-review lane:

```text
Web SOL
  -> code_mode(task={label: "Peer review: …"})
       -> Task / TrackedTasks awareness
       -> peer_review(provider, model, prompt, timeout, cwd)
            -> invoke_model_call(peer_review=True)
                 -> Pydantic Agent
                 -> independent review
```

Internal `invoke_model_call(..., peer_review=False)` remains a tool-less primitive because `m3_evidence()` uses it. Exact model ids are soft-verified against the provider `/v1/models` listing inside the credentialed worker before inference.

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
peer_review(provider=<approved>, model=<exact ID>, prompt=<complete packet>, timeout=<explicit seconds>)
        ↓
peer final review text
        ↓
host local write peer_answer.md
```

Local packet reads and answer writes add **zero provider round-trips**. Use direct `Path.read_text()` for raw packet transport; GPT Dive `read_file()` adds inspection metadata such as line numbers and must not be fed back as packet text.

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

## Output-token limit

Peer review does not accept a caller-supplied `output_tokens_limit` through outer `peer_review(...)`.

```text
selected alias
   ↓
model_registry model_name metadata
   ↓
output_tokens_limit
   ├─ provider max_tokens
   └─ Pydantic UsageLimits.output_tokens_limit
```

Current metadata includes:

```text
claude-opus-5      128000
claude-sonnet-5    128000
claude-haiku-4-5-20251001    64000
```

If peer-review mode selects a model without output-limit metadata, fail instead of silently falling back to an arbitrary value.

## Current peer aliases

## Reviewer selection boundary

The user chooses the provider and model. SOL resolves that choice to the provider's exact current model ID before approval. Peer-review runtime receives `provider + exact model ID` directly; it does not select another model, add an alias for the choice, or repeat provider-catalog lookup inside inference.

## Cache

Cache behavior is provider economics, not workflow architecture.

- Kunavo has shown useful repeated-prefix cache reuse in local testing.
- AIAPIFLOW previously showed unreliable useful-prefix reuse.
- A cache hit may reduce cost, but a miss does not trigger recovery/fallback logic.

The two-file workflow stays the same either way. Current provider economics belong in the user/provider docs and provider-lab evidence.

## Canonical outer Code Mode shape

The Wiki skill owns the full commented sample. Implementation shape is:

```python
from pathlib import Path

packet = (Path(CWD) / "peer_packet.md").read_text()
if not packet.strip():
    raise RuntimeError("peer_packet.md is empty")

result = await peer_review(
    provider=review_provider,
    model=review_model,
    prompt=packet,
    timeout=review_timeout,
    cwd=CWD,
)

if result.get("ok"):
    await write_file(path="peer_answer.md", content=result["output"])
```

The actual paid route runs only in outer Task-aware `code_mode(task={label: "Peer review: …"})` after the skill's provider/model preflight and explicit user approval gate. The outer call returns a `task_id` immediately; Web SOL continues foreground work and ordinary GPT Dive traffic surfaces the review through TrackedTasks. Result collection uses `task_collect(task_id)` non-destructively, cancellation uses `task_cancel(task_id)`, and explicit handling ends with `task_ack(task_id)`. No peer-review-specific tracker or execution runtime is added. `peer_review` has no timeout default; each review call supplies its timeout explicitly and keeps it within the outer 600-second Task deadline.

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
