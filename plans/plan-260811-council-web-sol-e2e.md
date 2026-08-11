# Mini Spec — Design Council Web SOL Transport E2E

## Why

The existing Design Council works well as a human-mediated dual conversation:

```text
Web SOL  ↔  User  ↔  Opus
```

The User is not an injection point in an autonomous AI loop. **Human is the loop.**

Today the reasoning workflow is useful, but the User repeatedly copies a SOL response into the Opus conversation, adds steering, copies the Opus response back into the SOL conversation, and repeats. The problem to solve is this manual transport friction, not the quality of either model and not the absence of autonomous AI-to-AI debate.

A key architectural constraint is that the real Web SOL session cannot live inside the local Pydantic runtime. Web SOL remains outside as the Primary Engineer + Conductor. Therefore the Council needs a clean transport boundary between the local runtime and the existing ChatGPT Web conversation.

## Problem

Prove the smallest possible round trip in which:

1. local code sends a User Council message into the existing ChatGPT Web SOL conversation;
2. Web SOL receives and reasons about that message normally;
3. Web SOL intentionally emits its Council response back to local WSL2 through a dedicated MCP primitive;
4. the local side records that response durably in Git.

The experiment must not depend on scraping SOL output from the ChatGPT DOM or detecting when streaming has visually finished.

## Hypothesis

The missing Web SOL transport can be split cleanly into two asymmetric adapters:

```text
Local Council input
      ↓
Playwright
      ↓
ChatGPT Web SOL
      ↓
Council MCP emit
      ↓
Git-backed Council record
```

- **SOL input:** Playwright drives only the existing ChatGPT input surface and sends the message.
- **SOL output:** Web SOL explicitly calls a Council MCP emit primitive with the response to record.
- **Completion signal:** the resulting Git commit, not DOM/stream inspection.

If this one-lane E2E works reliably, the later Council architecture can preserve the real Web SOL session while removing manual copy/paste transport.

## Decision for This Experiment

Build only the **Web SOL one-loop feasibility probe**.

The probe should create or use a throwaway Council Git repository containing at minimum:

```text
init.md
chat.md
.git/
```

`init.md` may contain minimal experiment context. `chat.md` is append-only and uses simple role blocks such as:

```markdown
# SOL

<response>

---
```

Git commit metadata is the timeline; no timestamp is required inside `chat.md`.

The dedicated Council MCP emit operation should:

1. accept the SOL-authored response explicitly;
2. append one `# SOL` block to `chat.md`;
3. create one Git commit for that Council event;
4. return compact success metadata sufficient for Web SOL to know the record was persisted.

Playwright should do only the minimum needed to send one User message to the intended existing ChatGPT Web SOL tab. It must not parse assistant responses, click Copy-response buttons, read the clipboard, infer stream completion, or use the DOM as the SOL output channel.

## Architecture Boundary

This experiment intentionally preserves the following split:

```text
Web SOL
  - real ChatGPT Web conversation
  - Primary reasoning/context remains here
  - outside Pydantic

Local experiment
  - Playwright input adapter
  - Council MCP emit primitive
  - Git persistence
```

Pydantic/Opus is **not required for this experiment**. The current GPT Dive Pydantic/Harness work may later implement the Opus lane, but this E2E must not depend on unfinished Council orchestration machinery.

## Test Contract

Use one externally observable E2E seam.

Send a unique marker such as:

```text
COUNCIL_E2E_<nonce>
```

The experiment is **PASS** only when all of the following are demonstrated:

1. **Input delivery** — Playwright sends the intended User message to the intended existing Web SOL conversation.
2. **SOL receipt** — Web SOL receives the exact unique marker and can respond to the Council instruction.
3. **MCP return path** — Web SOL returns its Council response through the dedicated MCP emit primitive, without DOM response extraction.
4. **Transcript persistence** — `chat.md` contains exactly one new `# SOL` response block for the probe.
5. **Git persistence** — Git `HEAD` advances with exactly one commit representing that SOL response event.
6. **Completion semantics** — local code can treat the successful commit as the response-complete signal; it does not need to inspect ChatGPT streaming state.

Record the exact trigger/input, relevant before/after Git state, resulting `chat.md` block, and PASS/FAIL result.

## Failure Policy

This is a feasibility probe. Do **not** add retries, recovery machinery, alternate transports, or generalized abstractions merely to make the experiment green.

Classify a failure at the smallest useful boundary:

- **A — Playwright input failure:** the message cannot be delivered reliably to the intended Web SOL tab.
- **B — Web SOL / MCP contract failure:** Web SOL cannot or does not reliably emit the response through the Council MCP primitive.
- **C — Local persistence failure:** emit reaches local WSL2 but append/commit semantics are incorrect.
- **D — Turn-model mismatch:** ChatGPT/MCP turn semantics make the proposed request/response protocol fundamentally unsuitable.

A meaningful failure returns to Design Council for redesign rather than silently expanding scope.

## Explicit Non-goals

Do not implement any of the following in this experiment:

- Opus integration or Pydantic Council session management;
- SOL/Opus movable `seen` refs;
- final `init.md` schema;
- full append-only Council protocol;
- Human Relay UI / web server / SSE;
- Council history browser;
- multi-Council management;
- automatic SOL ↔ Opus routing;
- convergence detection or autonomous debate loops;
- Playwright response scraping;
- Copy-response / clipboard extraction;
- DOM-based streaming completion detection;
- production-grade retries, recovery, daemonization, authentication, or browser lifecycle management.

## Implementation Guidance

Keep the experiment disposable and narrow. Prefer existing GPT Dive structure and the smallest new seam rather than introducing a generic browser-automation framework into the MCP surface.

The experiment may use temporary files/scripts where that reduces production coupling. If a new MCP primitive is required for the E2E, keep its semantics Council-specific and minimal until the probe proves the transport is worth promoting.

Preserve unrelated dirty changes in `~/gpt-dive`.

## Decision After the Experiment

A PASS proves only:

> **The Web SOL transport primitive is feasible: Playwright can provide input while MCP + Git provide a clean explicit output/completion path.**

It does **not** approve the full Design Council architecture.

After PASS/FAIL, return the evidence to Design Council before deciding the next layer. Candidate later decisions include:

- Council repo/init schema;
- append-only `chat.md` protocol;
- movable Git refs for `sol_seen` / `opus_seen`;
- Pydantic Opus lane and history semantics;
- minimal Human routing UI;
- operational hardening.

## Result

**PENDING**

Append the actual experiment evidence, deviations, and PASS/FAIL verdict here after execution.
