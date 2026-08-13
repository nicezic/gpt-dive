# Council Start / Reopen Direction

> Status: approved direction, not yet implemented as the final ergonomic flow.
> Current delivered fallback remains `gpt-dive-council --council-dir ... --sol-url ...`.

## Why This Exists

Council v1 proved the shared-room protocol and both participant transports. The remaining friction is startup:

```text
choose/create room
prepare init.md
provide the exact existing SOL conversation target
start server
open UI
```

The user should not have to remember those mechanics every time.

This work must preserve a crucial property: **the current ChatGPT Web conversation is SOL**. A new Council should not create a fresh SOL conversation and throw away the context that already produced the decision to open Council.

## Approved Boundary

Reusable Council lifecycle behavior should live behind **`code_mode` as a registered capability**, not as a fifth Web-facing MCP tool.

```text
ChatGPT Web SOL
    -> code_mode
         -> Council lifecycle capability
              -> room init/reopen
              -> Council server
              -> UI
```

This follows GPT Dive's stable-surface rule: keep the Web MCP surface small and grow reusable behavior behind `code_mode`.

The exact capability schema/action names are still an implementation detail. Do not invent a larger orchestration framework merely to make startup ergonomic.

## Room Location

New Council rooms use:

```text
~/council/<YYMMDD-title>/
```

Example:

```text
~/council/260813-council-start-ux/
```

Reasoning:

- `~/gpt-dive/` is program source, not user Council data.
- `~/wiki/` is curated durable knowledge, not raw active discussion state.
- a visible `~/council/` root keeps rooms human-inspectable and easy to recover.

Automatic room naming/management beyond this simple convention remains deferred.

## New Council Mental Flow

```text
current ChatGPT Web SOL session
        │
        ├─ already contains the live causal context
        │
        ▼
SOL reconstructs init.md
        │
        ▼
create ~/council/<YYMMDD-title>/ Git room
        │
        ▼
connect this existing SOL conversation
        │
        ▼
start Council server + open local UI
```

The important asymmetry is deliberate:

- SOL supplies the **context interpretation** for `init.md` because it already has the live conversation.
- the lifecycle capability supplies the **deterministic mechanics**: files, Git initialization, process/server/UI operations.

## `init.md` Purpose

`init.md` is the **initial causal-context packet** for the Council. It exists so a participant entering the room can understand why this problem exists, not merely what proposal is currently on the table.

SOL authors it from:

- the current ChatGPT conversation;
- relevant project/source/runtime facts;
- prior plans/specs/ADRs/Wiki when material;
- user-provided real-world facts that cannot be derived from the machine.

It should be concise enough to read, but complete enough to prevent a reviewer from solving the wrong problem.

### Default shape

```markdown
# <Council Title>

## Why
Why this Council exists and what real pain/event caused it.

## Background Knowledge
Concise knowledge required to reason about the problem correctly.

## Current Situation
The real current implementation/runtime/operational state.

## Problem / Questions
The concrete decisions or uncertainties this Council needs to examine.

## Constraints
Technical, economic, platform, operational, or user constraints.

## Decisions Already Made
Material decisions that are already settled, with brief reasons when useful.

## Rejected Alternatives
Important alternatives already considered and why they were rejected.

## Original References
Direct source paths, specs, plans, ADRs, experiments, issues/PRs, or URLs.

## Council Goal
What should be clearer or decided when this Council has done useful work.
```

Required by default:

- `Why`
- `Background Knowledge`
- `Current Situation`
- `Problem / Questions`
- `Constraints`
- `Original References` when source material exists
- `Council Goal`

`Decisions Already Made` and `Rejected Alternatives` are included when meaningful. Do not create decorative empty sections.

### Background Knowledge vs Original References

```text
Background Knowledge
= SOL's compact map for understanding

Original References
= source material that lets a participant verify or go deeper
```

Both matter. A summary is efficient, while the source prevents SOL's paraphrase from becoming the only truth.

## Why a Peer May Ask Questions First

Earlier Council experience showed a concrete failure mode: a strong independent reviewer challenged the proposed architecture before receiving enough information about user economics, platform constraints, existing implementation, and actual workflow pain. Once those facts were supplied, the reviewer materially changed its verdict and improved the API instead.

The lesson is not a rigid instruction such as “always ask questions first.” The lesson is:

> **Incomplete causal context can make an intelligent reviewer reason correctly about the wrong problem.**

Therefore the room should make missing or ambiguous material context easy to surface. If the context is already sufficient, there is no value in ritual clarification.

## `init.md` and Reasoning Lineage

The safest default is to treat `init.md` as the Council's **starting causal snapshot**. New facts, corrections, disagreement, and changed positions that arise after the room starts belong naturally in `chat.md` and Git history so the evolution remains visible.

If a future workflow chooses to mutate `init.md`, it must not erase why the Council originally started or rewrite away changed assumptions. That policy should be decided explicitly before automating such edits.

## Reopen

Reopening is not equivalent to merely restarting Uvicorn.

A reopened Council may run in a fresh ChatGPT Web session whose native history does not contain the room's earlier reasoning. Therefore reopen must distinguish:

```text
room state recovery
    = init.md + chat.md + Git protocol state

SOL native-context recovery
    = rehydrate the chosen/current Web SOL conversation when required
```

The detailed rehydration UX is still an open implementation decision. Do not claim that Git cursors alone make a fresh Web SOL session knowledgeable.

## Current Manual Baseline

Until the ergonomic capability is implemented, the deterministic baseline remains:

1. Use the current ChatGPT Web conversation as SOL.
2. Create/choose a Council Git room.
3. Ensure `init.md`, `chat.md`, and participant refs are initialized.
4. Start with scoped provider credentials when OPUS is needed.
5. Run `gpt-dive-council --council-dir <room> --sol-url <this exact conversation URL>`.
6. Use `http://127.0.0.1:8791` as the Council UI.

This baseline is intentionally documented as a fallback, not the desired everyday UX.

## Non-goals for Startup Ergonomics

- fifth top-level MCP tool;
- autonomous SOL ↔ OPUS routing;
- automatic consensus/convergence;
- multi-room dashboard;
- database-backed room registry;
- hidden browser output scraping;
- transcript compression;
- speculative recovery machinery.
