# Conduit Continuation

> Updated: 2026-08-16 KST
> Purpose: current handoff state. Stable background is in `bootstrap.md`; active design ideas are in `adr/0_brainstorm-and-design-draft.md`.

## Status

**Core async canary: PASS.**

Fresh ChatGPT Web session live acceptance observed from one user Enter:

```text
@c start
  → detached task returned immediately: running

SOL reasoning
  → continued in the same turn

@c sync
  → same task snapshot: done
```

This proves the core Conduit hypothesis on the current ChatGPT Web surface:

```text
c1 → SOL reasoning → c2
```

The canary intentionally did not call `collect`; it isolated `start → reasoning → sync`.

## Implemented checkpoint

Conduit implementation commit:

```text
9e70cac feat(conduit): add async canary MCP
```

Current v0:

- `@c` is the permanent Conduit app/namespace.
- `start` launches detached work through GPT Dive `JobManager`.
- `sync` is the short synchronous canary action.
- `collect` reads task results non-destructively.
- `emit` publishes conversation output/events.
- every successful call returns compact task snapshots: `id`, `label`, `status`, `age_sec`.
- Redis Stream `conduit:events` is the fixed event fan-out path.
- `gpt-dive-conduit-log` writes Redis events to `/tmp/conduit-events.ndjson`.

Local validation at implementation time:

```text
Conduit focused tests  6 passed
Redis Stream → NDJSON  PASS
ruff                   PASS
pyright                0 errors / 0 warnings
full pytest             109 passed
```

## Runtime state

Verified at handoff:

```text
chatgpt-conduit-mcp.service      active
gpt-dive-conduit-log.service    active
```

Relevant local paths:

- tunnel profile: `~/.config/tunnel-client/conduit.yaml`
- health/admin socket: `~/.local/run/gpt-dive/tunnel-conduit.sock`
- Conduit MCP: `~/gpt-dive/.venv/bin/python -m gpt_dive.conduit`
- tunnel service: `~/.config/systemd/user/chatgpt-conduit-mcp.service`
- logger service: `~/.config/systemd/user/gpt-dive-conduit-log.service`
- reconstruction templates: `docs/conduit/runtime/`

The `.sock` node is created by the running tunnel-client and is runtime-only; never commit it.

The existing `@dive` tunnel remains separate.

## Settled

Do not reopen without new evidence:

- project: **Conduit**
- Web-facing app/namespace: **`@c`**
- one primary action per call
- every successful call carries a compact task snapshot
- completed results are non-destructive on collect in v0
- Redis is event/fan-out transport, not the owner of Conduit domain semantics
- ordinary `@c` calls / user turns are the intentional task-refresh cadence
- server push is not required for the target workflow
- lack of ChatGPT Web negotiation of `io.modelcontextprotocol/tasks` is not a blocker for this workflow
- avoid speculative fallback trees; fail explicitly unless resilience protects a high-impact boundary
- MCP schema/metadata changes require restart/refresh and fresh-session acceptance

## Completed after canary

1. **Light live semantics checks — PASS**
   - the same completed task was collected twice successfully with the same result;
   - retained completed tasks remained visible in later automatic snapshots, including across later user turns.

2. **Conversation-driven task pull ADR — ACCEPTED**
   - `docs/conduit/adr/0001-conversation-driven-task-pull.md`
   - grounded in the 2026-08-16 fresh-session `start → SOL reasoning → sync` acceptance plus the non-destructive collect/retention check.

## Next

1. **Post-canary protocol design**
   - evolve `@c` only from real workflow pressure;
   - keep the Web-facing surface small;
   - do not prematurely hide all GPT Dive execution behind Conduit.

2. **Later: myWeb / Council generalization**
   - reuse the existing Council Svelte/Starlette work where useful;
   - preserve asymmetric transport: browser/Edge for input, explicit `@c` path for meaningful SOL output.

3. **Later: GBrain pipeline**
   - ingest selected/distilled Conduit events as a separate source/group;
   - do not blindly embed raw logs/tool payloads or pollute the current Pydantic corpus.

## Infrastructure cleanup — complete

Conduit health/admin listener cleanup is complete:

```text
@c → ~/.local/run/gpt-dive/tunnel-conduit.sock   PASS
```

Verified after restart on 2026-08-16: socket exists, `/readyz` returns `ready`, `/healthz` returns `live`, the old `~/.local/run/tunnel-conduit.sock` is gone, and `127.0.0.1:8081` is no longer listening.

The Dive tunnel is also migrated to the same runtime socket directory:

```text
@dive → ~/.local/run/gpt-dive/tunnel-dive.sock      PASS
@c    → ~/.local/run/gpt-dive/tunnel-conduit.sock   PASS
```

Pre-restart `tunnel-client doctor --profile wsl2-exec` passed. After the delayed Dive tunnel restart, a fresh ChatGPT Web session verified both paths with `test -S`/equivalent and confirmed that both are actual Unix domain sockets. That final fresh-session test intentionally did **not** re-check TCP ports or `/readyz` / `/healthz`; do not claim those as part of the final Dive acceptance evidence.

Repo reconstruction templates live in `docs/conduit/runtime/`; runtime socket nodes and secrets do not belong in Git.

Operational note: with the Conduit service already running, `tunnel-client doctor --profile conduit` may report `health_listener` failure because the Unix socket is already bound. For config acceptance, stop the Conduit tunnel service, remove any stale socket node, run `doctor`, then start the service and use `/readyz` + `/healthz` as runtime authority.

Also housekeeping only: the control-plane tunnel display name was created as `wsl2-conuit` (missing `d`). This does not affect operation.

## Known unrelated issue

During code review, `agy_worker()` produced no review output because headless `read_file` permission was auto-denied despite the expected read-only worker contract. This is an `agy_worker` config/contract issue, not a Conduit failure, and was intentionally left out of the canary scope.

## Fresh-session reading order

```text
@dive bootstrap
→ docs/conduit/README.md
→ docs/conduit/bootstrap.md
→ docs/conduit/CONTINUATION.md
→ docs/conduit/adr/0_brainstorm-and-design-draft.md only when active design detail is needed
```

Suggested workflow skills for the next non-trivial slice:

- `/grill-me` for consequential user decisions
- `/to-spec` before implementation
- `/implement`
- `/code-review`
- `/handoff` or `/final` to refresh this file

## Authority

- Stable context: `docs/conduit/bootstrap.md`
- Document map: `docs/conduit/README.md`
- Active pre-ADR draft: `docs/conduit/adr/0_brainstorm-and-design-draft.md`
- Canary plan: `plans/plan-260816-conduit-canary.md`
- Runtime architecture: `docs/runtime/architecture.md`
- Council precedent: `docs/council/README.md`, `docs/council/history.md`
- Model economics/routing: `~/wiki/user/models-and-providers.md`
- GBrain: `~/wiki/infra/gbrain.md`
- Edge/Playwright: `~/wiki/skills/web/edge-playwright.md`
