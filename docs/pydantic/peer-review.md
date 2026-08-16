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

The packet preserves the **Why** before optimizing token count. Council experiments showed that incomplete causal context can make a strong reviewer reason correctly about the wrong problem.

It is intentionally a compact causal model rather than a pile of imperatives. The reviewer should understand **why the problem exists, why the current position exists, why the constraints are real, and why each reference is relevant** before exercising independent judgment. Hard commands are reserved for actual boundaries.

Useful packet material, only when relevant:

```text
Why / causal chain
Background Knowledge
Current Reality
Focused Question / Goal
Constraints / Invariants + why they matter
Current Position + Reason
Rejected Alternatives + why rejected
Uncertainty
Original References + why each matters
Review Lens
```

Do not mechanically fill every heading. Missing material context is bad; unrelated context flooding is also bad.

### Background Knowledge vs Original References

- **Background Knowledge** is SOL's compact map that helps the peer understand the situation quickly.
- **Original References** are source code, plans, ADRs, experiments, logs, or docs that the peer can inspect directly.

Keep both when useful. SOL's paraphrase should not become the only source of truth.

### Code-shaped packet

For GPT Dive peer review, comments carry the causal model and Code Mode carries the known evidence. The format exists for a reason: the current `opus5` route is a third-party gateway where useful prompt-cache reuse has not been reliable, so **known relevant references are front-loaded into one deliberate evidence-loading turn** rather than discovered one-by-one later.

> **Cheap reads, expensive turns. Optimize for decision completeness per model turn, not minimum input size.**

```python
# PEER REVIEW PACKET
# Why this review exists: <causal chain that produced the decision/problem>
# Background: <compact knowledge needed to understand that causal chain>
# Current reality: <runtime/economics/platform/policy facts that change the answer>
# Goal: <what success must accomplish and why it matters>
# Review question: <the focused judgment whose answer changes the next decision>
# Constraints: <invariants + why those constraints are real>
# Current position: <SOL's current answer>
# Why this position: <evidence/reasoning that led there>
# Rejected alternatives: <real alternatives + why they were rejected>
# Uncertainty: <where an independent judgment path has the most value>
# Review lens: Independent Peer
#
# Evidence plan: these sources are already known to be relevant, so they are loaded
# together in the first run_code round instead of being discovered across later turns.
# Economics: reads are cheap relative to another model turn on the current route.
# Favor enough relevant evidence for a sound first judgment over minimizing packet size.
docs = await asyncio.gather(
    read_file(path="/path/to/background.md"),
    read_file(path="/path/to/review-target.md"),
    read_file(path="/path/to/decision-or-council-context.md"),
    read_file(path="/path/to/provider-or-runtime-evidence.md"),
)

# NOTE: REQUIRED — do not remove this final expression. Without it, run_code returns {}.
docs

# Evidence boundary: project facts are reliable when supported by supplied or directly
# inspected evidence; unsupported possibilities belong in hypotheses/proposals.
# Material disagreement is useful output; consensus is not a completion requirement.
#
# If the packet is insufficient, useful output includes the exact missing information,
# focused follow-up questions, and a suggested next packet composition: what to add,
# what to retain, and what to omit because it was redundant or noisy.
#
# Extra tool turns are expensive on the current gateway because each one creates another
# provider request without useful prompt-cache reuse. Additional investigation is therefore
# reserved for a material blocker that prevents a sound judgment from this packet.
```

> **IMPORTANT:** Keep `docs` as the final expression. If it is removed, `run_code` returns `{}` and the peer does not receive the loaded evidence.

The packet is reviewer-facing intent. The model may issue an equivalent `run_code` program rather than copying it literally. The comments are mostly explanatory rather than imperative: they build the reviewer's world model and make the evidence economy explicit.

Independent reads should normally be grouped into one `asyncio.gather(...)` inside a single `run_code` call. This is not only parallel I/O; it keeps known evidence acquisition inside one provider round-trip. If evidence is still insufficient after that load, the reviewer should usually propose the next packet instead of browsing out of curiosity.

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
