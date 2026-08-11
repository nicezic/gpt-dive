# Council Evolution

> Historical reasoning for GPT Dive Council. Preserve the **why** behind changes, not only the latest conclusion.

## Origin — Manual Copy/Paste Council

Before Council existed as a GPT Dive feature, the working pattern was manual:

```text
USER <-> Web SOL
USER <-> Opus peer reviewer
```

The User copied relevant reasoning between the two AI conversations, supplied real-world constraints, and decided when another opinion was useful.

This repeatedly produced useful disagreement and refinement. SOL and Opus often reached different conclusions even after seeing each other's arguments, then debated the reasons well. The valuable property was therefore not strict context isolation; it was **independent judgment under human steering**.

The pain was transport. Manual copy/paste worked, but it was tedious and made the User act as both moderator and message bus.

## First Design Council — Background Code Mode

The first explicit Design Council reviewed whether `code_mode` should support detached execution.

An early Opus review challenged the proposal because the review packet contained the proposed architecture but not enough causal context. After the User added quota economics, platform constraints, already-implemented infrastructure, and the actual workflow pain, Opus changed its verdict and improved the API from action-style execution to `background=True`.

This produced a durable lesson:

> **A decision without its Why is incomplete context.**

Council participants need the history, observed pain, constraints, rejected alternatives, and reasons that produced a proposal. Otherwise a strong reviewer may correctly challenge the wrong problem.

## From Review Pattern to Product Idea

The successful manual Council suggested automating the repetitive transport while keeping the User in control of judgment and turn-taking.

A key boundary emerged:

> **Automate transport, not judgment.**

The User remains the moderator/domain owner. SOL remains the primary engineer. Opus remains an independent peer. No autonomous SOL <-> Opus debate loop is required.

## Web SOL Transport Experiment

Web SOL lives inside the real ChatGPT Web product and cannot simply be instantiated inside the local Pydantic runtime. Council therefore needed an adapter to the existing browser conversation.

The experiment intentionally split the path:

```text
Input:  local Council -> Playwright -> existing ChatGPT Web SOL
Output: Web SOL -> MCP council_emit -> Git
```

Playwright was kept input-only. It does not scrape SOL output, inspect streaming completion, click Copy, or read the clipboard.

The first E2E probe passed. A one-shot CDP attach worked but triggered an Edge approval prompt for each new connection. Keeping one persistent CDP WebSocket for the session removed the repeated prompt. The final probe reached the real Web SOL conversation, SOL invoked `council_emit`, and one append-only `# SOL` turn became one Git commit.

Detailed evidence is preserved in `plans/council/2026-08-11-web-sol-e2e.md`.

## Private Lanes Considered

An intermediate design treated SOL and Opus as private lanes whose contexts were isolated. Cross-lane information would be explicitly relayed by the User.

This protected context independence, but it created routing metadata, relay semantics, selective visibility, and synchronization complexity that did not match the successful manual workflow.

The User clarified the intended experience: Council should feel like one shared discussion room. When a participant is asked to speak, its prompt should reflect the chronological USER/SOL/OPUS conversation so far.

## Shared Room — Current Direction

The architecture reframed from private lanes to a shared room:

```text
USER / SOL / OPUS
       -> one chronological Council conversation
```

The User decides who speaks next. Participants see the shared discussion and can build on or challenge each other's reasoning.

The principle changed from **Context Independence** to **Judgment Independence**:

- participants may see each other's reasoning;
- they should not follow an earlier opinion merely because it appeared first;
- material disagreement should be explicit;
- positions may change when evidence warrants it;
- the Why behind proposals, disagreement, and decisions must remain visible.

For rare cases where fresh eyes are valuable, an Independent Challenge mode may later provide only the background plus a focused question. It is not the default Council model.

## Preserve Why

Council's logical context is not merely a list of final decisions. It is the reasoning lineage that explains them.

Important context includes:

- Why the Council exists;
- observed pain and real-world constraints;
- proposals and their rationale;
- disagreement and counterarguments;
- rejected alternatives and why they were rejected;
- changed positions and what evidence caused the change.

Premature summarization is intentionally avoided in the early Council design because compression tends to erase precisely this causal context.

## Current Minimal State Direction

The current design discussion has converged on a small Git-backed model:

```text
Council repo
├── init.md      # Why / background / problem / constraints
├── chat.md      # append-only chronological USER / SOL / OPUS transcript
└── .git/
    ├── commits  # one speaking event per commit
    └── refs/council/context/
        ├── sol
        └── opus
```

`chat.md` should remain a dumb human-readable transcript. Protocol state should not be encoded by parsing the most recent `# SOL` or `# OPUS` heading.

The context refs are explicit participant cursors: each ref identifies the commit through which that participant's native/model context is known to be synchronized. The unread transcript can be derived from Git snapshots while preserving the append-only invariant.

The v3 direction was subsequently formalized by Matt-P `/to-spec` as [`specs/council.md`](../../specs/council.md). This history remains the causal record for why the spec has its current shape.

## Current Product Naming

The feature name is **Council**.

- Code and filesystem naming: `council`
- Long conceptual name when useful: Design Council
- Natural Korean trigger: "회의", "카운실", or "Council"

Council is intentionally broader than architecture review. It is meant for difficult debugging, brainstorming, design, and technical decision-making.

## Council Web UI Stack

Council UI uses **Svelte 5 + Vite + TypeScript**.

The main reason is **AI friendliness**. Svelte 5 has unusually strong AI coding support, while also offering fast development and a lightweight frontend.
