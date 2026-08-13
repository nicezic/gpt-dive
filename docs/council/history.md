# Council Evolution

> Historical reasoning for GPT Dive Council. Preserve the **why** behind changes, not only the latest conclusion.

## 1. Origin — Manual USER / SOL / OPUS Council

The pattern existed before the product.

```text
USER <-> Web SOL
USER <-> Opus peer
```

The user manually carried arguments between the two conversations, added real-world constraints, decided who should speak next, and remained the final decision owner.

This worked surprisingly well. SOL and Opus could see each other's arguments and still disagree materially, refine assumptions, or change position when evidence changed. The useful property was therefore not hidden context. It was **independent judgment under human steering**.

The pain was transport. The user was simultaneously moderator and copy/paste message bus.

## 2. First Design Council — Missing Why Changed the Review

The first explicit Council reviewed background execution for `code_mode`.

An early peer review challenged the proposal as potentially unnecessary because the review packet described the candidate architecture better than it described the causal context that created the need.

The user then supplied the missing reality:

- Web SOL quota/economics;
- the desire to keep one SOL reasoning flow productive during long work;
- ChatGPT Web's missing MCP Tasks negotiation;
- already-existing JobManager and Code Mode infrastructure;
- the actual workflow pain.

The peer changed its verdict and improved the API from an action-heavy `sync/start` shape to the simpler `background=True` execution flag.

This produced the most important Council lesson:

> **A decision without its Why is incomplete context.**

A strong reviewer can correctly challenge the wrong problem when history, economics, constraints, and observed pain are absent.

## 3. Product Idea — Automate Transport, Not Judgment

The manual pattern suggested a product boundary:

> **Automate transport, not judgment.**

Council should remove repetitive relay work without turning SOL and Opus into an autonomous debate loop.

```text
USER = moderator / domain owner
SOL  = primary engineer
OPUS = independent peer
```

The user still decides:

- who speaks next;
- what real-world information matters;
- when to redirect the discussion;
- when enough evidence exists to make a decision.

## 4. Web SOL Transport Constraint

The real SOL lives in ChatGPT Web and cannot simply be instantiated inside the local Pydantic runtime.

The smallest useful bridge therefore became asymmetric:

```text
Input : local Council -> Playwright/CDP -> existing ChatGPT Web SOL
Output: Web SOL -> MCP/code_mode -> council_emit -> Git
```

Playwright is deliberately **input-only**. It does not scrape assistant output, inspect stream completion, click Copy, or read the clipboard.

The E2E probe passed. A persistent CDP connection also removed the repeated approval prompt seen with one-shot browser attachments.

Evidence: `../../plans/council/2026-08-11-web-sol-e2e.md`.

## 5. Private Lanes Were Considered and Rejected as the Default

An intermediate design treated SOL and OPUS as separate private contexts with explicit user relay.

That protected context separation, but created routing metadata, selective visibility semantics, and synchronization complexity that did not match the successful real workflow.

The user clarified the intended experience: **one Council room**.

```text
USER / SOL / OPUS
       -> one chronological conversation
```

This changed the governing idea from **Context Independence** to **Judgment Independence**:

```text
Context Independence
= hide another participant's reasoning

Judgment Independence
= see the shared reasoning but do not follow it merely because it appeared first
```

For rare fresh-eye work, an Independent Challenge can deliberately hide prior AI discussion. It is a special review mode, not the normal Council room.

## 6. Preserve Reasoning Lineage

The Council's durable knowledge is not just a list of final decisions.

Important context includes:

- why the Council exists;
- observed pain and real-world constraints;
- proposals and their rationale;
- disagreement and counterarguments;
- rejected alternatives and why they were rejected;
- evidence that changed a participant's position.

This is why early Council intentionally avoids automatic transcript summarization/compression. Compression tends to erase the causal information that made the first Council review useful.

## 7. Git-backed Shared Room

The protocol converged on a small Git repository:

```text
Council room
├── init.md
├── chat.md
└── .git/
    ├── commits
    └── refs/council/context/
        ├── sol
        └── opus
```

`chat.md` is append-only and human-readable:

```markdown
# USER

...

---

# SOL

...

---

# OPUS

...

---
```

One speaking event becomes one commit.

The participant refs are explicit synchronization cursors. They mean that the corresponding participant's native/model context is synchronized through that commit. They are not access-control markers.

The cursor decision matters because “last visible role block” and “context actually synchronized through this point” are different concepts when delivery or generation can fail.

## 8. Logical Context vs Physical Transport

Council logically preserves the shared conversation, but does not have to retransmit the whole transcript every turn.

```text
Logical context
= initial Why/background + full chronological Council reasoning

Physical transport
= participant native/model history + unread Council suffix
```

Git identifies where the unread suffix begins; `chat.md` supplies the actual pure appended text. Raw Git patch syntax is not model context.

Cursor advancement happens only after a successful participant response commit. Failure therefore leaves unread context recoverable for retry.

## 9. Council v1 — FULL PASS

Council v1 implemented:

- Git-backed room protocol;
- OPUS through the real Pydantic `opus5` path;
- Web SOL through persistent input-only Edge/CDP + `council_emit`;
- Svelte 5 + Vite + TypeScript room UI;
- Starlette/Uvicorn REST backend;
- failure-safe retry without duplicate USER turns.

Final acceptance passed Python, frontend, repo-protocol, real OPUS, real UI, and real Web SOL E2E checks. The implementation/decision SSOT is `../../specs/council.md`.

## 10. Post-v1 — Startup Friction Becomes the Next Problem

The delivered runtime still requires:

```text
gpt-dive-council --council-dir <path> --sol-url <exact existing ChatGPT URL>
```

That exposes mechanics the user should not need to remember.

The next direction now has several approved decisions:

- current ChatGPT Web conversation remains SOL;
- Council rooms live under `~/council/<YYMMDD-title>/`;
- SOL authors the initial `init.md` from live context and source evidence;
- `init.md` separates compact background knowledge from original references;
- reusable start/reopen mechanics belong behind a registered `code_mode` capability, not a fifth top-level MCP tool.

The detailed reopen/rehydration behavior remains a design area because a fresh Web SOL session can have correct Git room state while still lacking the native conversational context of the earlier session.

See `startup.md`.

## 11. Current Product Meaning

Feature name: **Council**.

Natural triggers may include “회의”, “카운실”, or `Council`, but the product is broader than architecture review. It is intended for difficult debugging, brainstorming, research interpretation, and consequential technical decisions where a strong independent peer adds value.
