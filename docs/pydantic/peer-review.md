# GPT Dive Peer Review

> Status: **Draft / experimental**
> Updated: 2026-08-17
> Scope: GPT Dive Pydantic integration

## Purpose

GPT Dive's Code Mode-facing `bare(...)` capability is currently an **independent peer-review lane**. It gives a selected Pydantic model a compact reviewer instruction plus read-only Harness `FileSystem + CodeMode`, so Web SOL can send a focused review packet and let the peer inspect referenced evidence when needed.

The name is transitional. The underlying `invoke_bare(..., peer_review=False)` primitive remains genuinely tool-less because `m3_evidence()` depends on that behavior. Only the outer Code Mode `bare(...)` route enables peer-review mode.

```text
Web SOL
  -> code_mode
       -> bare(model, prompt, cwd)
            -> invoke_bare(peer_review=True)
                 -> Pydantic Agent
                      -> read-only FileSystem
                      -> CodeMode(run_code)
                 -> independent review
```

## Current contract

Implementation:
- `src/gpt_dive/app.py` exposes `bare(model, prompt, timeout, output_tokens_limit, cwd)` as the peer reviewer.
- `src/gpt_dive/bare.py` owns the worker, reviewer instruction, capabilities, subprocess isolation, timeout, and usage summary.
- `src/gpt_dive/model_registry.py` owns provider/model routing. Do not hard-code provider economics in this document.

The current reviewer instruction is intentionally small. Its job is not to teach a frontier model how to review; it explains the packet/evidence economics and the escape hatch when context is still insufficient:

For the Kunavo cached multi-round path, the current policy is deliberately asymmetric: a decisive read-only tool call is allowed when it prevents reasoning from a false premise, while broad exploratory research should normally be requested as focused next-packet evidence. Web SOL may gather that evidence itself or delegate suitable factual research to the cheaper `agy_worker` lane. Prompt-cache reuse lowers stable-prefix replay cost; it does not make premium reasoning/tool output free.

```text
Act as an independent peer reviewer.
The packet carries causal context and may include a first-run Code Mode evidence loader.
Treat that supplied packet as the primary evidence path.
Keep extra tool turns rare because third-party gateways may replay expensive uncached input.
If evidence remains insufficient, identify what is missing and suggest focused questions
or a better next packet instead of exploratory browsing unless the gap blocks judgment.
```

This follows the current frontier-model lesson: prefer a strong model plus good evidence/tools over a large behavioral harness. It also reflects the current provider reality rather than pretending every tool call is economically free.

## Safety boundary

Peer review is read-only. Its Harness `FileSystem`:
- is rooted at the supplied `cwd`;
- rejects a workspace that is itself a credential/secret path;
- applies GPT Dive's shared credential/secret deny patterns;
- cannot write through the reviewer capability.

Choose the **narrowest common workspace root** that contains every reference the packet needs. A review spanning `~/wiki` and `~/gpt-dive` may use the user's home as the common root; ordinary repo review should use the repo root.

## Review Packet

The **workflow policy SSOT** for packet composition is:

- `~/wiki/skills/web/peer-review.md` — runtime review procedure;
- `~/wiki/skills/web/peer-review-adr.md` — rationale, external research, and change triggers.

This GPT Dive document owns the implementation/evidence-loader boundary and current provider economics. Do not duplicate or override the Wiki's evolving DRAFT review policy here.

The current workflow distinguishes:

```text
Ground Truth / Problem Why
        +
Review Target
        -> independent judgment

Prior Opinion / Verdict
        -> normally withheld until a later informed challenge
```

This still preserves the original Council lesson: incomplete causal context can make a strong reviewer reason correctly about the wrong problem. The change is that **Problem Why** and original evidence are front-loaded while avoidable prior-opinion framing is not treated as ground truth.

### Evidence loader

For GPT Dive peer review, comments carry the compact task/causal context and Code Mode carries known evidence. The current `opus5` route is a third-party gateway where useful prompt-cache reuse has not been reliable, so known relevant references are normally loaded together in one deliberate `run_code` turn rather than discovered piecemeal.

> **Cheap reads, expensive turns. Optimize for decision completeness per model turn, not minimum input size.**

Representative loader shape:

```python
# PEER REVIEW PACKET — exact review framing is owned by the Wiki skill.
# Problem Why / current reality / goal / constraints / uncertainty
# Review Target: the artifact or hypothesis being judged, when ordinary review is intended.
# Evidence plan: these sources are already known to be relevant.
docs = await asyncio.gather(
    read_file(path="/path/to/background.md"),
    read_file(path="/path/to/review-target.md"),
    read_file(path="/path/to/material-evidence.md"),
)

# REQUIRED — without this final expression run_code returns {}.
docs
```

For a fresh-eye **Independent Solver**, the Wiki workflow may deliberately omit the current solution/Review Target until a comparison phase. That is a review-policy choice, not a different GPT Dive capability.

> **IMPORTANT:** Keep `docs` as the final expression. If it is removed, `run_code` returns `{}` and the peer does not receive the loaded evidence.

The packet is reviewer-facing intent. The model may issue an equivalent `run_code` program rather than copying it literally. Independent reads should normally be grouped in one `asyncio.gather(...)` inside a single `run_code` call. This is not only parallel I/O; it keeps known evidence acquisition inside one provider round-trip.

If evidence remains insufficient after that load, the reviewer should usually identify the missing fact or propose a better next packet instead of browsing out of curiosity. Additional investigation is reserved for a material blocker because each extra tool/model turn may replay expensive uncached input on the current provider route.

## Review lenses

Use a lens only when it sharpens the real question:
- **Independent Peer** — default; judge the proposal without obligation to agree.
- **Adversarial Reviewer** — seek concrete weaknesses and counterexamples.
- **Assumption Breaker** — find hidden premises that must be true.
- **Failure-mode Hunter** — focus on crash, timeout, race, stale state, partial failure, recovery.
- **Alternative Designer** — look for a materially simpler/different route to the same goal.
- **Independent Solver** — fresh solve with prior AI reasoning minimized when anchoring bias matters.
- **Algorithm Critic** — correctness, robustness, objective mismatch, regime dependency.

A lens is not an instruction to manufacture disagreement.

## Experimental evidence

### Read-only CodeMode smoke

A 2026-08-17 Sonnet 5 experiment supplied eight Pydantic/Orchestra/provider documents and asked for an architecture review. The model used:

```text
provider requests  2
outer run_code      1
nested read_file    8
```

It correctly grouped all independent reads with `asyncio.gather(...)`, demonstrating that one CodeMode round-trip can gather a multi-document evidence packet efficiently.

### Grounding failure

That same experiment also produced unsupported project claims after reading the documents. This is the important negative result: **successful retrieval does not prove evidence-grounded judgment**.

The draft skill therefore asks the peer to distinguish:
- supported project facts;
- proposals/hypotheses;
- speculative failure modes.

Do not compensate with a giant system prompt. Keep the rule small and improve it only when real peer-review runs show a repeatable failure.

### Opus 5 full-packet acceptance

The first 24-document Opus 5 self-review exposed a packet bug: the `asyncio.gather(...)` result was assigned but not returned as the final `run_code` expression. Harness therefore returned `{}` even though the files had been read, and the model filled the missing evidence with unsupported implementation claims. The packet template now makes the final `docs` expression mandatory.

After that fix, the same review shape loaded 24 selected Wiki/GPT Dive documents (about 150 KB on disk) in one `run_code` evidence round. The successful call used:

```text
provider requests  2
input tokens      55,013
output tokens      4,034
additional retrieval   0
```

The second review correctly referenced the current `bare.py` implementation, provider/cache evidence, Council rationale, and workflow boundaries without needing another evidence turn. This is the current strongest acceptance evidence for the draft rule: **front-load enough relevant evidence, return it explicitly from `run_code`, then spend the expensive model turn on judgment rather than piecemeal discovery.**

### Provider/cache note

The current default `opus5` alias routes through AIAPIFLOW, a third-party Anthropic-compatible gateway. A repeated fixed-prefix cache probe on 2026-08-17 produced the same pattern on all three runs:

```text
input_tokens       3031
cache_read_tokens    86
cache_write_tokens 2928
```

The useful 2,928-token prefix was cache-created again on every request instead of becoming a cache read, and `/v1/usage` balance/`actual_cost` deltas matched the charged requests. This is the concrete reason the draft reviewer front-loads known evidence and treats extra tool turns as expensive.

A control test against Kunavo produced `WRITE -> READ -> READ` for the same style of repeated prefix, confirming that the probe can observe working cache reuse and that the behavior is provider-specific rather than a Pydantic/Anthropic telemetry assumption.

Treat cache support and effective price as runtime/provider evidence, not as a permanent peer-review semantic contract. If the `opus5` route changes, re-test before preserving or relaxing the one-round evidence policy. Current provider facts belong in:
- `~/wiki/user/models-and-providers.md`
- `~/wiki/user/aiapiflow-provider.md`
- provider-lab profiles/results

### Kunavo repeated-review path

For a multi-round premium review, GPT Dive also exposes `kunavo-opus5` as a **bare-only** alias. It routes `claude-opus-5` through the verified Kunavo Anthropic-compatible endpoint and is intentionally disabled for the ordinary subagent lane.

The repeated-review cache shape stays inside the existing `bare()` capability rather than adding another MCP tool. Web SOL sends:

```text
<stable base packet>
<!-- GPT_DIVE_PEER_CACHE_BREAK -->
<round-specific delta>
```

For `kunavo-opus5` peer-review mode, `bare.py` splits that marker and calls Pydantic AI with:

```python
[stable_base, CachePoint(ttl="5m"), round_delta]
```

This matters because `bare()` is stateless across calls: there is no durable provider conversation to reuse. Cache reuse therefore depends on preserving the **same stable prefix** across review rounds. The review target's stable `PEER-REVIEW.md` content belongs before the cache point; new answers, corrections, or challenges belong after it as the round delta.

Local provider testing previously observed Kunavo cache reuse as `WRITE -> READ -> READ` for a repeated prefix. The 5-minute TTL is the currently verified conservative choice. Do not infer 1-hour support or build a fallback path until live evidence justifies it. If a round misses the cache because the TTL expired, ordinary input billing is acceptable; the workflow does not add recovery complexity merely to force a hit.

## Invocation

Inside GPT Dive Code Mode:

```python
result = await bare(
    model="opus5",
    prompt=INPUT,
    cwd=CWD,
    output_tokens_limit=4096,
)
```

Use `INPUT` for the multiline review packet. Set `CWD`/`cwd` to the narrowest common root containing the referenced evidence.

`output_tokens_limit` is a Pydantic usage budget, not the provider's `max_tokens` request setting.

## After the review

The peer answer is advisory, not authority.

Web SOL should:
1. verify material factual claims against source/runtime evidence;
2. separate confirmed flaws from speculative concerns;
3. accept, reject, or modify the current position with a reason;
4. preserve consequential disagreement or evidence that changed the decision in the relevant plan/ADR/context artifact;
5. when the peer reports missing context, turn that into a focused **next packet**: answer the useful questions, add the missing evidence, retain what mattered, and remove references the peer found redundant/noisy;
6. let the user decide whether another peer turn is worth the cost.

Do not automatically start a debate loop or force consensus. A review that ends with a precise missing-information request can be more useful than an expensive exploratory tool loop.

## Draft follow-ups

This design is intentionally small. Improve it from real usage, not speculation.

Candidates only after evidence justifies them:
- rename the outer Code Mode capability from transitional `bare` to `peer_review` while retaining the true tool-less primitive internally;
- provider selection/cache policy for repeated premium reviews;
- compact structured telemetry for reviewer tool calls;
- packet helpers if repeated manual packet construction becomes genuine friction.
