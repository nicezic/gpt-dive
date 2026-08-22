# GPT Dive — Current Continuation

> Updated: 2026-08-14
> Purpose: compact fresh-session handoff. Durable Why/history belongs in `docs/`; implementation decisions/evidence belong in `specs/` and `plans/`.

## Completed External Work — GBrain Voyage Guard + Stable Index

The GBrain-side work that motivated the browser investigation is complete. Do not carry its old implementation TODOs into a fresh GPT Dive session.

- Voyage free-quota runtime is browserless: managed `voyage.dashboard-session` -> direct backend HTTPS quota lookup -> strict `voyage-code-3` PASS/BLOCK. Edge/Playwright/CDP/dashboard tabs/socket are not runtime dependencies.
- Enrollment/recovery may use the generic Edge Playwright Extension, but normal quota lookup does not.
- Stable Index Filter v1 is now production: `1204 pages / 21368 chunks / 21368 embedded`, stale `0`, source FAILS/QUEUE `0`.
- Production `~/.gbrain` is a symlink to `~/.cache/gbrain-stable-index-v1/.gbrain`; previous production is preserved at `~/.gbrain.rollback-pre-stable-index-20260814`.
- GBrain authorities: `~/gpt-dive/gbrain/docs/reconstruction.md`, `~/gpt-dive/gbrain/plans/plan-260814-stable-index-upgrade.md`, and clean upstream `~/ref/gbrain`.
- Generic Edge automation remains a separate completed browser capability. Do not route Voyage quota runtime back through it.

## Immediate Handoff — ToolOutputLimits Study / Live Validation

Purpose: verify and understand the **already-integrated** Pydantic Harness `ToolOutputLimits` before designing any GPT Dive-specific output-limiting code.

### Verified state

- Study authority: `~/wiki/pydantic/study/patterns/tool-output-failure-policy.md`.
- Upstream authority: `~/ref/pydantic-ai-harness/docs/tool-output-limits.md`, `docs/guardrails.md`, implementation under `pydantic_ai_harness/tool_output_limits/`, and its tests.
- `src/gpt_dive/subagent_worker.py::_build_worker_capabilities()` already includes `ToolOutputLimits()` after `FileSystem`, `Shell`, and `RepoContext`.
- `tests/test_subagent_worker_capabilities.py` verifies that `ToolOutputLimits` is present in the default coding-worker capability bundle, but no GPT Dive test found yet proves real spill/read-back behavior.
- Current study evidence says the Harness default reduces oversized successful tool returns at production time using `Spill(then=Truncate())` at 10,000 characters; failure/retry signals are intentionally treated differently. Re-verify exact current behavior from the installed/upstream source before relying on this remembered threshold.

### Exact remaining task

1. Read the current Harness `ToolOutputLimits` public API, source, and tests to establish exact defaults, spill storage/lifecycle, `read_tool_result`, structured/binary behavior, and interaction/order with `ToolGuardrail`.
2. Trace how the existing default `ToolOutputLimits()` behaves inside GPT Dive's real `subagent_worker` capability bundle. Distinguish the Harness Shell `max_output_chars=50_000` boundary from `ToolOutputLimits`; they operate at different layers.
3. Run the smallest controlled local acceptance that produces a successful tool result above the ToolOutputLimits threshold and verify what the subagent/model actually sees, whether a spill handle is exposed, whether `read_tool_result` is usable, and whether persistent model-visible context stays bounded.
4. Separately verify an error/retry path so output limiting does not hide recovery diagnostics.
5. Report whether GPT Dive should use the Harness behavior **as-is**, configure it differently, compose it with another existing Harness capability, or only then consider a thin local adaptation.

### Constraints / non-goals

- Start read-only and evidence-first. Do **not** add a new custom output-limiter merely because the feature is unfamiliar.
- Do not modify GPT Dive code/config until the existing behavior and any actual gap are demonstrated; use `/grill-me` before a consequential design change.
- Do not conflate `ToolOutputLimits` with compaction: output limiting shapes a tool result when produced; compaction rewrites already accumulated history.
- Preserve full failure diagnostics needed for recovery; bounded-context policy must not create convincing but unrecoverable failures.
- Do not touch the unrelated current untracked `docs/pydantic/` tree unless its contents are explicitly needed and verified.

Suggested next skill: `/grill-me` only if live acceptance exposes a real configuration/design choice; otherwise this is primarily a study + acceptance task.


## Immediate Handoff — Code Mode Files + Shell

- Implementation commit: `e0f6f1f` (`feat: expose harness files and shell in code mode`).
- Plan / decision / validation record: `plans/code_mode/plan-260814-files-and-shell.md`.
- Code Mode uses Harness FileSystem 8 tools + Shell 4 tools directly; `run_command()` is the single normal foreground shell path. Shell keeps guard-bin/provider-secret stripping, run-owned background cleanup, and the 50k output cap.
- Validation before commit: targeted Code Mode tests **30 passed**; full suite **78 passed**; touched-file Ruff PASS; `git diff --check` PASS.

### Verified live acceptance state — PASS

Fresh-session acceptance completed on **2026-08-14**.

- The active MCP/tunnel service had already restarted at **06:36:42 KST** (`MainPID=1357599` at acceptance time). The prior 05:28 process state in this handoff was stale historical state, not a reason to restart again.
- Live `CAPABILITIES` exposes all 12 new FileSystem + Shell names with native signatures/descriptions.
- Live smoke PASS: `read_file`, stale-hash `write_file`/`edit_file` rejection with unchanged content, `run_command`, `start_command -> check_command -> stop_command`, and run-end background cleanup.
- No additional MCP restart is pending for this rollout. Re-check live state before proposing any future restart rather than carrying forward this completed reload task.

## Current Position

- **v1 Local MCP Runtime**: stable.
- **v2 Pydantic AI Harness**: stable and extensible.
- **v3 Council / Council v1 product slice**: implemented / FULL PASS.
- Council compact map: `docs/council/README.md`.
- Council implementation/decision SSOT: `specs/council.md`.
- Council causal history: `docs/council/history.md`.
- Current post-v1 start/reopen direction: `docs/council/startup.md`.
- Completed implementation tickets: `plans/council/2026-08-12-council-v3-tickets.md`.

Do not redo the completed Council design interview, Web SOL feasibility probe, or v1 implementation acceptance unless new evidence exposes a regression.

## Stable Web MCP Surface

Exactly four top-level tools remain:

```text
bootstrap
code_mode
wsl2_sync
wsl2_async
```

Council does **not** add a fifth Web-facing tool. Web SOL output continues through the registered `council_emit` Code Mode capability.

The newly approved startup/reopen direction follows the same rule: reusable Council lifecycle mechanics should grow as a **registered `code_mode` capability**.

## Council Mental Model

```text
Shared Council Room

USER = moderator / domain owner
SOL  = existing ChatGPT Web primary engineer
OPUS = independent peer through Pydantic AI
```

Principles:

- **Shared Context**
- **Judgment Independence**
- **Preserve Why**
- **Human Controls Turns**
- **Automate transport, not judgment**
- no automatic transcript summarization/compression in v1

The important historical lesson is that a strong peer can challenge the wrong problem when causal context is incomplete. The first Council materially improved only after the user supplied missing economics, platform constraints, existing implementation facts, and real workflow pain.

## Delivered Storage / Protocol

```text
init.md
chat.md
.git/commits
refs/council/context/sol
refs/council/context/opus
```

- `chat.md` is append-only and human-readable.
- one USER/SOL/OPUS speaking event = one Git commit.
- participant refs are synchronization cursors, not access-control markers.
- unread input is the pure appended transcript suffix between cursor snapshot and target HEAD.
- non-append mutation and dirty transcript state are rejected.
- cursor advances only after a successful participant response commit.
- Git backend remains the official `git` CLI behind a narrow subprocess seam.

## Delivered Participant Paths

### To OPUS

```text
Council UI / REST
  -> USER commit
  -> Pydantic `opus5`
  -> OPUS commit
  -> context/opus advance
```

Pydantic worker calls are stateless across invocations, so the adapter reconstructs the participant context required by the Git synchronization contract.

### To SOL

```text
Council UI / REST
  -> USER commit
  -> persistent input-only Playwright / Edge CDP
  -> existing ChatGPT Web SOL
  -> code_mode -> council_emit(expected_head=...)
  -> SOL commit
  -> context/sol advance
```

Playwright never scrapes assistant output, Copy buttons, clipboard data, or streaming completion. Git commit is the completion signal.

## Local UI / Runtime

- Frontend: Svelte 5 + Vite + TypeScript under `web/`.
- Backend: Starlette + Uvicorn REST in `src/gpt_dive/council/server.py`.
- CLI: `gpt-dive-council`.
- Default bind: `127.0.0.1:8791`.
- One room / one turn at a time in v1.

Current delivered invocation:

```text
gpt-dive-council --council-dir <path> --sol-url <exact ChatGPT conversation URL>
```

## Final v1 Acceptance

```text
Ruff                       PASS
pytest                     PASS — 60 passed
Council/App Pyright        PASS — 0 errors, 0 warnings
Svelte check               PASS — 0 errors, 0 warnings
Vite build                 PASS
Repo protocol              PASS
Real OPUS provider E2E     PASS
Real Svelte To OPUS E2E    PASS
Real Web SOL E2E            PASS
```

Key implementation commits:

```text
597f79e docs: define Council v3 implementation tickets
e4713ec feat: implement Council repo protocol
afcbf07 feat: scaffold Council room UI
3423723 feat: implement Council Opus turn
79484ad fix: retry Council Opus turn without duplicate user commit
d4aa608 feat: implement Council Web SOL turn
80ac9fe feat: integrate Council shared room UI
a8fdf9f fix: preserve subagent failure diagnostics
7118d18 docs: close Council v1 implementation
```

## Post-v1 Decisions — Start / Reopen

These are approved direction but **not yet delivered as the final ergonomic runtime**.

### Room root

```text
~/council/<YYMMDD-title>/
```

### SOL identity

The **current ChatGPT Web conversation remains SOL**. Starting Council must not create a fresh SOL conversation and discard the causal context already present in the current session.

### `init.md` ownership

SOL authors the initial `init.md` from the current conversation plus relevant live/project/source evidence.

Default information shape:

```text
Why
Background Knowledge
Current Situation
Problem / Questions
Constraints
Decisions Already Made       # when meaningful
Rejected Alternatives        # when meaningful
Original References
Council Goal
```

`Background Knowledge` is the compact understanding map. `Original References` point to source material so SOL's paraphrase is not the only truth.

The peer is not forced to ask questions first. The reason to make questions easy is that **incomplete causal context can make an intelligent reviewer reason correctly about the wrong problem**.

### Lifecycle boundary

Startup/reopen mechanics should be implemented behind a **Council capability registered in `code_mode`**. Exact capability action names/schema remain an implementation detail.

### Reopen

Reopen must distinguish room-state recovery from Web SOL native-context rehydration. A fresh ChatGPT session can have correct Git room state while still not knowing the earlier Council reasoning.

See `docs/council/startup.md`.

## Deferred / Not Approved by v1 Success

- Independent Challenge mode
- transcript/context compression
- richer history/navigation
- multiple simultaneous rooms / dashboard
- automatic room naming/management beyond the simple path convention
- more participants
- autonomous debate/routing
- speculative recovery/bridge hardening

## Next Work

Continue `/grill-me` only for the remaining consequential start/reopen decisions, especially:

1. exact `code_mode` Council lifecycle capability API;
2. how to resolve the existing/current SOL conversation without manual URL friction;
3. reopen/rehydration semantics for a fresh Web SOL session;
4. smallest validation boundary for the startup flow.

Do not implement unrelated Council v2 features while these boundaries remain open.
