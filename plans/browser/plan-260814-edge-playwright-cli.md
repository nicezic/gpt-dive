# Edge Playwright CLI Web Skill

- Date: 2026-08-14
- Status: Implemented / Live Acceptance PASS
- Owner: Web SOL

## Goal / Why

Replace the current generic browser-automation path that depends on a custom persistent Edge CDP Unix-socket bridge with a much thinner operating model: Web SOL calls the official Playwright CLI through Dive `wsl2_sync`, while a trusted Wiki Web Skill teaches the exact CLI usage and lifecycle rules.

The immediate use case is reliable automation against the user's already logged-in Microsoft Edge session, including authenticated provider usage/quota inspection, without exposing browser credentials unnecessarily or growing another custom browser API inside GPT Dive.

## Current State

- Microsoft Edge remote debugging is already enabled on the user's existing Edge Stable instance.
- The former Wiki route `~/wiki/skills/web/edge-cdp.md` documented a custom long-lived Playwright `connect_over_cdp()` attachment behind `/tmp/gpt-dive-council-edge.sock`; it was explicitly removed before CLI implementation so it cannot remain an active competing route.
- Generic bridge implementation currently lives in `~/gpt-dive/experiments/council_web_sol_e2e/edge_bridge.py`.
- `~/gpt-dive/src/gpt_dive/council/bridge.py` is also used by Council/Web-SOL transport and must not be removed as part of this change without separate acceptance.
- The official Playwright CLI now supports attaching to a running Edge by channel with `playwright-cli attach --cdp=msedge`, automatically using an `msedge` session when no explicit session is supplied, and detaching without closing the external Edge instance.
- `@playwright/cli` is installed globally through `pnpm` (local WSL policy blocks direct `npm`). Live acceptance observed version `0.1.18`, but that version is evidence only, not a pin; normal operation follows rolling latest because Edge itself auto-updates.
- Runtime drift matters: installed 0.1.18 `list --all` lists CLI-managed sessions but did not discover the Windows Edge before attachment, while current upstream `main` documents broader system-browser discovery.
- `playwright-cli attach --cdp=msedge` from WSL resolves Linux `~/.config/microsoft-edge/DevToolsActivePort` and therefore cannot directly discover the user's Windows Edge. The local route must read the Windows `DevToolsActivePort` under `/mnt/c/Users/...` and pass its explicit WebSocket endpoint with `--session=msedge`.
- Live acceptance is complete. A fresh Edge launch produced a new `DevToolsActivePort` WebSocket endpoint; explicit attach succeeded, and persistent session reuse was validated across separate `wsl2_sync` calls.

## Scope

### In scope

1. Validate official Playwright CLI against the user's currently running, logged-in Edge.
2. Adopt Playwright CLI as the default generic Web SOL browser-control path through existing Dive shell execution.
3. Replace the current generic Edge CDP Wiki guidance with a new trusted Web Skill under `~/wiki/skills/web/`.
4. Register that Web Skill in `~/wiki/skills/INDEX.md` so fresh Web SOL sessions discover it from bootstrap.
5. Document compact commands for attach/reuse, session discovery, snapshot/interaction, evaluation, network inspection where supported, and detach.
6. Document credential/privacy rules and fail-closed behavior for authenticated usage/quota inspection.
7. Update other Wiki references that still route generic browser automation to the old persistent Unix-socket bridge.
8. Record the result and validated command set in this same plan after implementation.

### Non-goals

- Do not add a new GPT Dive `edge_browser()` MCP capability.
- Do not add Chrome DevTools MCP or Playwright MCP as another nested MCP layer.
- Do not create a new custom browser RPC protocol.
- Do not delete or rewrite Council's browser-input transport during this task.
- Do not migrate provider-specific quota/business logic into the generic Web Skill.
- Do not expose cookies, auth headers, access tokens, refresh tokens, or unrelated page/session data to Web SOL.

## Key Decisions

### Decision 1 — Use official Playwright CLI directly through Dive

**Decision**

Web SOL will invoke `playwright-cli` through existing Dive `wsl2_sync` rather than adding a new Dive browser capability. Persistent browser-session commands intentionally do not use Harness `code_mode -> run_command()` because live acceptance showed that execution boundary cleans up the spawned Playwright CLI daemon.

**Reason**

`wsl2_sync` is already a direct WSL shell boundary and preserves the Playwright CLI daemon across calls. The Playwright CLI owns browser/session lifecycle and exposes browser actions directly, so another local API would only duplicate schema, wrappers, validation, documentation, and maintenance.

**Rejected alternatives**

- New `edge_browser()` Dive capability.
- Expanding the custom Python Unix-socket bridge for generic browser work.
- Adding a nested Playwright MCP or Chrome DevTools MCP server.

**Consequences / tradeoffs**

- Web SOL must follow the Wiki skill precisely rather than rely on a typed browser MCP schema.
- Browser commands use consistent `cwd=~/gpt-dive` through `wsl2_sync` so the named CLI session remains discoverable.
- CLI drift is handled by rolling-latest update-on-use plus the installed runtime `--help`/behavior.
- The implementation stays very small and upstream-owned.

### Decision 2 — Register the operating guide as a trusted Web Skill

**Decision**

Create/rename the browser guidance as a trusted Web Skill under `~/wiki/skills/web/` and register it in `~/wiki/skills/INDEX.md`.

Preferred name: `edge-playwright.md`.

**Reason**

This is procedural knowledge for Web SOL: when to attach, how to reuse a session, which commands are safe, and how to avoid leaking credentials. It belongs in the progressive-disclosure Web Skill layer rather than a generic infra note.

**Rejected alternatives**

- Keep the main instructions only in `infra/`.
- Encode the procedure in MCP server descriptions.
- Rely on Web SOL's generic Playwright knowledge.

**Consequences / tradeoffs**

- `skills/INDEX.md` becomes the stable discovery point.
- The skill should stay compact and command-oriented, with provider-specific recipes elsewhere.

### Decision 3 — Reuse one CLI attach session instead of repeated attaches

**Decision**

Normal operation reuses the existing `msedge` Playwright CLI session. Attach is a lifecycle operation, not a per-command operation.

**Reason**

Repeated browser-level attachments were the failure mode behind duplicate owners/approval prompts in the previous implementation. The CLI's named attach session already provides the persistent identity we need.

**Consequences / tradeoffs**

The skill must teach how to detect/reuse the current session and when `detach` is appropriate.

### Decision 4 — Keep Council bridge migration separate

**Decision**

Do not remove `src/gpt_dive/council/bridge.py` or change the Council Web-SOL input transport in this spec.

**Reason**

That code participates in an already accepted Council E2E path. Generic browser automation and Council message transport have different acceptance contracts. Coupling them would turn a small browser-tool simplification into a risky Council refactor.

**Rejected alternative**

Retire all Edge bridge code immediately after Playwright CLI smoke acceptance.

**Consequence**

There may temporarily be two browser-related mechanisms: Playwright CLI for generic Web Skill automation and the existing Council-specific bridge. A later focused task may assess whether Council can also migrate.

### Decision 5 — Separate generic browser skill from provider-specific usage recipes

**Decision**

`edge-playwright.md` documents browser mechanics and safety. Voyage or other provider-specific quota/usage extraction remains in the relevant provider/GBrain documentation or dedicated adapter logic.

**Reason**

The browser transport should remain generic. Provider DOM/API shapes are volatile and should not make the base browser skill stale.

## Implementation Direction

### 1. Smoke-test official CLI across the WSL2 -> Windows Edge boundary

Use the installed runtime contract, not only upstream `main` docs:

```bash
playwright-cli --version
playwright-cli list --all

DAP=$(find /mnt/c/Users -path '*/AppData/Local/Microsoft/Edge/User Data/DevToolsActivePort' -print)
PORT=$(sed -n '1p' "$DAP")
WS_PATH=$(sed -n '2p' "$DAP")
playwright-cli attach --cdp="ws://127.0.0.1:${PORT}${WS_PATH}" --session=msedge

playwright-cli -s=msedge snapshot --depth=8
playwright-cli -s=msedge --raw eval '() => document.title'
playwright-cli -s=msedge requests --filter='/api/.*usage|quota|billing/'
playwright-cli -s=msedge detach
```

The generic `playwright-cli attach --cdp=msedge` example is not sufficient from this WSL environment because it searches Linux Edge state. Runtime `--help`/behavior is authoritative when upstream docs and the installed package differ.

A fresh Edge CDP attachment may require user approval. Keep exactly one attach attempt alive while approval is pending; do not start a competing direct Playwright bridge or repeated CLI attaches.

### 2. Create the trusted Web Skill

Target:

`~/wiki/skills/web/edge-playwright.md`

The skill should be concise and cover:

- Trigger/use cases.
- `playwright-cli list --all` / attach discovery.
- WSL2-local attach via the Windows `DevToolsActivePort` explicit WebSocket endpoint with `--session=msedge`; also document why plain `--cdp=msedge` is not the local route.
- Reuse of the `msedge` session.
- Core page inspection / interaction commands validated on the installed CLI.
- `--raw` or equivalent compact-output guidance when available.
- Network/request inspection commands only after runtime verification.
- `detach` semantics and when not to detach.
- Recovery: verify session/Edge state before a new attach.
- Credential/privacy rule: never print secrets or broad authenticated browser state.
- Context rule: filter large browser output locally and return only evidence needed by Web SOL.

### 3. Register discovery

Update `~/wiki/skills/INDEX.md` so bootstrap advertises the new Web Skill.

Update `~/wiki/bootstrap/intro.md` browser-help route if it still points at `edge-cdp.md`.

### 4. Retire only the obsolete generic documentation path

`edge-cdp.md` is removed outright, not superseded in place, so a fresh session cannot follow both the old Unix-socket generic path and the new CLI path. Its active bootstrap/index references are removed until `edge-playwright.md` is installed and registered.

Do not remove Council implementation code in this task.

### 5. Keep provider usage logic fail-closed

Authenticated usage/quota workflows may use the logged-in browser, but the final browser skill should encourage extraction of only the minimal result. If quota/usage cannot be freshly verified, provider-specific guards must fail closed rather than infer a value.

## Failure Policy

- If `playwright-cli` cannot discover/attach to the currently running Edge, stop the migration and diagnose from current Edge remote-debugging state and installed CLI behavior. Do not repeatedly attach or ask for repeated approvals.
- If the CLI runtime contract differs from current upstream docs, trust the installed CLI `--help`/behavior for execution and record the version-dependent difference.
- Do not silently fall back to a new custom direct `connect_over_cdp()` script for generic browser work.
- Existing Council transport remains unchanged on CLI failure.
- Never solve browser-control failure by dumping browser credentials/session storage into model context.

## Test Contract

### A. Discovery

**Given** Edge is already running with remote debugging enabled.

**When** Web SOL runs CLI browser discovery.

**Then** the existing Edge instance is visible without launching a second browser.

### B. Attach + reuse

**Given** the running Edge is attachable.

**When** the CLI attaches to the explicit Windows Edge WebSocket endpoint with `--session=msedge`.

**Then** subsequent `wsl2_sync` calls from the same `~/gpt-dive` cwd can target the same `msedge` session without another attach.

### C. Logged-in session access

**Given** a harmless page/tab already open in the user's logged-in Edge.

**When** Web SOL performs read-only inspection through the attached CLI session.

**Then** the existing browser state is available without re-login and without returning credentials.

### D. Basic browser operations

Prove the smallest useful validated set from the installed CLI:

- list/discover session/browser;
- snapshot or equivalent page inspection;
- minimal read-only evaluation;
- network/request inspection if supported by the installed command set.

### E. Detach safety

**When** Web SOL detaches the attached CLI session.

**Then** the user's external Edge process and tabs remain running.

### F. No regression to Council

**Then** no Council bridge source/service behavior is modified by this task.

### G. Fresh-session discovery

**Given** a fresh Web SOL session bootstraps the Wiki.

**Then** `skills/INDEX.md` advertises `edge-playwright.md`, and bootstrap browser help routes to it rather than the obsolete generic `edge-cdp.md` path.

## Acceptance / Validation

PASS requires all of the following:

- [x] Official Playwright CLI installed globally through the local approved package manager (`pnpm`).
- [x] Live-accepted CLI version (`0.1.18`) and command contract recorded as historical evidence; runtime policy is rolling latest, not pinned.
- [x] Existing Windows Edge discovered from its live `DevToolsActivePort`.
- [x] Explicit Windows Edge WebSocket attach with `--session=msedge` PASS; plain WSL `--cdp=msedge` was correctly rejected as the wrong local discovery route.
- [x] Same `msedge` session reused across multiple `wsl2_sync` calls from `~/gpt-dive`.
- [x] Snapshot/read-only browser inspection PASS.
- [x] Minimal read-only eval PASS (`Example Domain` / `example.com`).
- [x] Network/request contract checked and validated on public `example.com`: filtered request list -> GET 200 -> bounded `response-body` read.
- [x] `detach` leaves the external Windows Edge running; its `DevToolsActivePort` remained live after detach.
- [x] Coexistence PASS: with the current GBrain legacy bridge active, CLI attach -> tab-list -> detach succeeded and the bridge still answered `ping -> pong` afterward.
- [x] No cookies/auth tokens/session secrets returned to SOL during acceptance.
- [x] `~/wiki/skills/web/edge-playwright.md` created and marked trusted.
- [x] `~/wiki/skills/INDEX.md` updated.
- [x] `~/wiki/bootstrap/intro.md` updated to route browser help to the new skill.
- [x] Obsolete generic `edge-cdp.md` route removed outright; active bootstrap/index references removed.
- [x] Council browser transport source code unchanged.
- [x] Relevant Wiki/log documentation updated for the durable operating model.

## Follow-up / Explicitly Separate Work

- [ ] Evaluate whether Council's `SolBridge` can later move from direct Playwright CDP ownership to the same CLI/session model.
- [ ] Migrate GBrain's current Voyage free-quota guard away from `/tmp/gpt-dive-council-edge.sock`; until then the existing guard fails closed when that legacy bridge is unavailable.
- [ ] Consider provider-specific deterministic usage adapters only after generic browser CLI acceptance.
- [ ] Consider Chrome DevTools MCP only if a future task requires deeper DevTools capabilities that Playwright CLI cannot provide economically/cleanly.

## References

- Microsoft Playwright CLI repository / skill: https://github.com/microsoft/playwright-cli
- Playwright CLI session management: https://github.com/microsoft/playwright-cli/blob/main/skills/playwright-cli/references/session-management.md
- Microsoft Edge DevTools MCP guidance, useful as corroborating Edge remote-debugging/session-state reference: https://learn.microsoft.com/en-us/microsoft-edge/web-platform/devtools-mcp-server

## Result

**Implemented / Live Acceptance PASS.**

Delivered and validated:

- Installed `@playwright/cli` globally with `pnpm`; live acceptance used `0.1.18`, while the operating policy is update-on-use `@latest` so the CLI naturally tracks an auto-updating Edge.
- Verified runtime commands for sessions, attach/detach, snapshot/find/eval, `--raw`, filtered request listing, response-body extraction, and `run-code`.
- Identified and documented the WSL2/Windows boundary: plain `playwright-cli attach --cdp=msedge` searches Linux Edge state and is not the local route. Web SOL reads the Windows Edge `DevToolsActivePort`, attaches its explicit WebSocket endpoint, and names the CLI session `msedge`.
- Found an execution-boundary constraint during acceptance: a Playwright CLI daemon spawned inside Harness `code_mode -> run_command()` is cleaned up with that systemd/cgroup boundary, so the session does not survive into the next call. Direct Dive `wsl2_sync` preserves the CLI daemon and successfully reused `msedge` across separate calls. The trusted Web Skill now makes `wsl2_sync` + consistent `cwd=~/gpt-dive` the browser-session rule.
- Live attached to the user's existing Windows Edge and observed the existing logged-in tabs without re-login or credential extraction.
- Reused the same session across calls; validated tab listing, bounded snapshot, read-only eval, filtered network listing, GET 200 observation, and bounded response-body read using a temporary public `example.com` tab.
- Closed only the temporary test tab and detached. The external Edge browser and its original tabs remained running, with the same live `DevToolsActivePort` afterward.
- Added trusted `~/wiki/skills/web/edge-playwright.md`, registered it in `skills/INDEX.md`, and routed bootstrap browser help to it.
- Removed the obsolete `edge-cdp.md` Web Skill outright.
- No Council browser transport source was modified.

Temporary compatibility dependency discovered during migration:

- GBrain's current Voyage free-quota guard still directly depends on `/tmp/gpt-dive-council-edge.sock`. That provider-specific transport migration remains separate work. To avoid regressing the existing fail-closed guard, the managed legacy bridge service was restored after CLI acceptance and verified READY. Coexistence was then live-validated: Playwright CLI attached/listed tabs/detached while that bridge stayed active, and the bridge still returned `{"ok": true, "action": "pong"}` afterward. Generic Web SOL browser automation uses the new Playwright CLI Web Skill and does not stop the current GBrain guard bridge merely to attach.
