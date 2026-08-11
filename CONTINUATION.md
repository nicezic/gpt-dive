# GPT Dive — Current Continuation

> Updated: 2026-08-12
> Purpose: compact fresh-session handoff only. Durable Why/history belongs in `docs/`; implementation/decision artifacts belong in `plans/` and `specs/`.

## Current Position

- **v1 Local MCP Runtime**: stable
- **v2 Pydantic AI Harness**: stable and extensible
- **v3 Council / Council v1 product slice**: **implemented / FULL PASS**
- Council implementation/decision SSOT: `specs/council.md`
- Final implementation tickets: `plans/council/2026-08-12-council-v3-tickets.md`
- Latest verified local suite: **60 passed**
- Ruff PASS; Council/App Pyright 0 errors; Svelte check 0 errors/0 warnings; Vite build PASS

## Stable Web MCP Surface

Exactly four top-level tools remain:

```text
bootstrap
code_mode
wsl2_sync
wsl2_async
```

Council does **not** add a fifth Web-facing MCP tool. Web SOL returns through the registered `council_emit` Code Mode capability.

## Council — Delivered Mental Model

```text
Shared Council Room
USER = moderator / domain owner
SOL  = primary engineer
OPUS = independent peer
```

Principles remain:

- **Shared Context** — one chronological Council conversation.
- **Judgment Independence** — shared context does not imply agreement.
- **Preserve Why** — keep causal context, disagreement, rejected alternatives, and reasons behind changed decisions.
- **Human Controls Turns** — automate transport, not judgment.
- **No automatic transcript summarization/compression in v1.**

## Delivered Storage / Protocol

```text
init.md
chat.md
.git/commits
refs/council/context/sol
refs/council/context/opus
```

- `chat.md` is append-only and human-readable.
- One USER/SOL/OPUS speaking event becomes one Git commit.
- Participant refs are explicit synchronization cursors.
- Unread input is the pure appended transcript suffix between cursor snapshot and target HEAD.
- Non-append mutation and dirty transcript state are rejected.
- Cursor advances only after a successful participant response commit.
- Git backend intentionally remains the official `git` CLI through a narrow subprocess seam; no GitPython/pygit2/Dulwich dependency was added.

## Delivered Participant Paths

### To OPUS

```text
Svelte / REST
  -> USER Git commit
  -> Pydantic `opus5`
  -> OPUS Git commit
  -> refs/council/context/opus advance
```

Pydantic worker calls are stateless, so the Opus adapter reconstructs previously synchronized transcript context plus the new unread suffix each turn. Failed calls preserve the USER commit and unchanged cursor; retry does not duplicate the USER turn.

### To SOL

```text
Svelte / REST
  -> USER Git commit
  -> persistent input-only Playwright / Edge CDP
  -> existing ChatGPT Web SOL
  -> code_mode -> council_emit(expected_head=...)
  -> SOL Git commit
  -> refs/council/context/sol advance
```

Playwright never scrapes assistant output, Copy buttons, clipboard data, or streaming completion. Git commit is the completion signal. `expected_head` prevents stale/duplicate SOL responses from attaching to the wrong Council state. Late SOL commits can be reconciled before browser resend.

The bridge is an explicit Council-owned `SolBridge` lifecycle rather than a generic 600-second durable job.

## Local UI / Runtime

- Frontend: **Svelte 5 + Vite + TypeScript**, top-level `web/`.
- Backend: **Starlette + Uvicorn REST** in `src/gpt_dive/council/server.py`.
- CLI entry point: `gpt-dive-council`.
- Current invocation shape:

```text
gpt-dive-council --council-dir <path> --sol-url <exact ChatGPT conversation URL>
```

- Default bind: `127.0.0.1:8791` (`8787` is already used by Hermes locally).
- One room / one turn at a time in v1; server serializes participant turns with a lock.

## Final Acceptance — FULL PASS

```text
Ruff                       PASS
pytest                     PASS — 60 passed
Council/App Pyright        PASS — 0 errors, 0 warnings
Svelte check               PASS — 0 errors, 0 warnings
Vite build                 PASS
Repo protocol              PASS
Real OPUS provider E2E     PASS
Real Svelte To OPUS E2E    PASS
Real Web SOL E2E           PASS
```

Final integrated SOL acceptance traversed Svelte -> Python -> persistent CDP -> current Web SOL -> `council_emit` -> Git -> SOL cursor. Throwaway-room evidence: USER HEAD `fad1287790170b5962ec877a3c6516a3e13a403b`, SOL commit `d4a998a761f033b96cbf9cc5ec8779aa683c4dc9`, final `HEAD == refs/council/context/sol`.

## Key Implementation Commits

```text
597f79e docs: define Council v3 implementation tickets
e4713ec feat: implement Council repo protocol
afcbf07 feat: scaffold Council room UI
3423723 feat: implement Council Opus turn
79484ad fix: retry Council Opus turn without duplicate user commit
d4aa608 feat: implement Council Web SOL turn
80ac9fe feat: integrate Council shared room UI
a8fdf9f fix: preserve subagent failure diagnostics
```

## Runtime Reload Rule

Do not restart the active GPT Dive MCP service inline during its own in-flight call. Schedule live reload out-of-band with the documented 5-second buffer. See `docs/runtime/operations.md`.

## Deferred / Not Approved by v1 Success

- Independent Challenge mode
- transcript/context compression
- richer history/navigation
- multiple rooms
- automatic room naming/management
- more participants
- autonomous debate/routing
- speculative bridge hardening

## Next Candidate

The next useful product step is **Council start/reopen ergonomics**: reduce the current manual `--council-dir` + `--sol-url` startup into a convenient everyday flow (create/reopen repo, resolve/remember SOL target, start server, open UI). Treat this as the next candidate for consultation, not as already-approved implementation scope.

Do not redo the completed Council design interview, transport feasibility probe, or v1 implementation acceptance unless new evidence exposes a real regression.
