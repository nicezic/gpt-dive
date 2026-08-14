# Edge Playwright CLI Web Skill

- Date: 2026-08-14
- Status: Implemented / Live Acceptance PASS
- Owner: Web SOL

## Goal / Why

Replace the current generic browser-automation path that depends on a custom persistent Edge CDP Unix-socket bridge with a much thinner operating model: Web SOL calls the official Playwright CLI through Dive `wsl2_sync`, while a trusted Wiki Web Skill teaches the exact CLI usage and lifecycle rules.

The immediate use case is reliable automation against the user's already logged-in Microsoft Edge session, including authenticated provider usage/quota inspection, without exposing browser credentials unnecessarily or growing another custom browser API inside GPT Dive.

## Current State

- The official Microsoft Playwright Extension is installed in the user's normal Microsoft Edge profile and is the **primary attach transport**.
- Extension authentication is stored in `creds` as `playwright.extension` -> `ai:PLAYWRIGHT_MCP_EXTENSION_TOKEN`; only the token value is stored.
- The former Wiki route `~/wiki/skills/web/edge-cdp.md` documented a custom long-lived Playwright `connect_over_cdp()` attachment behind `/tmp/gpt-dive-council-edge.sock`; it was explicitly removed before CLI implementation so it cannot remain an active competing route.
- Generic bridge implementation currently lives in `~/gpt-dive/experiments/council_web_sol_e2e/edge_bridge.py`.
- `~/gpt-dive/src/gpt_dive/council/bridge.py` is also used by Council/Web-SOL transport and must not be removed as part of this change without separate acceptance.
- `@playwright/cli` is installed globally through `pnpm` (local WSL policy blocks direct `npm`). Live acceptance observed version `0.1.18`, but that version is evidence only, not a pin; normal operation follows rolling latest because Edge itself auto-updates.
- From WSL2, Extension attach uses the Windows Edge executable explicitly through `PLAYWRIGHT_MCP_EXECUTABLE_PATH=/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe` and `playwright-cli attach --extension=chrome --session=msedge`.
- Live acceptance is complete: the profile token skipped the browser approval dialog, Extension attach succeeded, the named session persisted across separate `wsl2_sync` calls, a public tab could be created/inspected, and detach -> reattach succeeded without another user approval.
- Direct CDP via Windows `DevToolsActivePort` remains a tested fallback/recovery path only. It can require Edge's manual **Allow remote debugging** approval and is not the normal route.

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

Use the installed runtime contract, not only upstream `main` docs. Primary attach is the official Extension with a profile token from `creds`:

```bash
pnpm add -g @playwright/cli@latest || true
playwright-cli --version
playwright-cli list --all

PLAYWRIGHT_MCP_EXECUTABLE_PATH='/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' \
  creds run ai -- playwright-cli attach --extension=chrome --session=msedge

playwright-cli -s=msedge snapshot --depth=8
playwright-cli -s=msedge --raw eval '() => document.title'
playwright-cli -s=msedge requests --filter='/api/.*usage|quota|billing/'
playwright-cli -s=msedge detach
```

The Extension token removes the repeated browser approval step. The browser's Playwright/automation indicator should be left open during active automation rather than dismissed by habit.

Direct CDP is fallback only. Plain `playwright-cli attach --cdp=msedge` searches Linux Edge state from WSL; the tested recovery path reads Windows `DevToolsActivePort` and attaches the explicit WebSocket endpoint. A fresh CDP attach may still require manual Edge approval.

### 2. Create the trusted Web Skill

Target:

`~/wiki/skills/web/edge-playwright.md`

The skill should be concise and cover:

- Trigger/use cases.
- `playwright-cli list --all` / attach discovery.
- Primary WSL2 attach via the official Playwright Extension + `PLAYWRIGHT_MCP_EXTENSION_TOKEN` + explicit Windows Edge executable path, bound to `--session=msedge`.
- CDP/Windows `DevToolsActivePort` only as fallback/recovery, including why plain WSL `--cdp=msedge` is not the local route.
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

**Given** the user's normal Edge profile has the Playwright Extension installed and `playwright.extension` exists in `creds`.

**When** Web SOL checks CLI session state and performs Extension attach only if needed.

**Then** the existing Edge profile is reused without requiring CDP remote-debugging approval.

### B. Attach + reuse

**Given** the running Edge has the official Extension and valid profile token.

**When** the CLI attaches with `--extension=chrome --session=msedge` using the explicit Windows Edge executable path.

**Then** no browser approval click is required, and subsequent `wsl2_sync` calls from the same `~/gpt-dive` cwd can target the same `msedge` session without another attach.

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
- [x] Official Playwright Extension installed in the user's normal Edge profile.
- [x] `playwright.extension` credential registered as `ai:PLAYWRIGHT_MCP_EXTENSION_TOKEN`, with token-only storage verified.
- [x] Extension attach through the explicit Windows Edge executable path with `--extension=chrome --session=msedge` PASS.
- [x] Approval-dialog bypass PASS: detach -> reattach succeeded with zero user approval clicks.
- [x] Direct Windows `DevToolsActivePort` CDP attach retained only as tested fallback; plain WSL `--cdp=msedge` remains the wrong local discovery route.
- [x] Same `msedge` session reused across multiple `wsl2_sync` calls from `~/gpt-dive`.
- [x] Snapshot/read-only browser inspection PASS.
- [x] Minimal read-only eval PASS (`Example Domain` / `example.com`).
- [x] Network/request contract checked and validated on public `example.com`: filtered request list -> GET 200 -> bounded `response-body` read.
- [x] `detach` leaves the external Windows Edge running; zero-click Extension reattach also PASS.
- [x] Coexistence PASS: with the then-current GBrain legacy bridge active, CLI attach -> tab-list -> detach succeeded and the bridge still answered `ping -> pong` afterward.
- [x] No cookies/auth tokens/session secrets returned to SOL during acceptance.
- [x] `~/wiki/skills/web/edge-playwright.md` created and marked trusted.
- [x] `~/wiki/skills/INDEX.md` updated.
- [x] `~/wiki/bootstrap/intro.md` updated to route browser help to the new skill.
- [x] Obsolete generic `edge-cdp.md` route removed outright; active bootstrap/index references removed.
- [x] Council browser transport source code unchanged.
- [x] Relevant Wiki/log documentation updated for the durable operating model.

## Follow-up / Explicitly Separate Work

- [ ] Evaluate whether Council's `SolBridge` can later move from direct Playwright CDP ownership to the same CLI/session model.
- [x] GBrain Voyage free-quota guard replaced by a **browser-independent direct backend runtime**. Normal quota lookup no longer depends on Edge, Playwright, Extension, CDP, a dashboard tab, or `/tmp/gpt-dive-council-edge.sock`; enrollment/recovery is separate and the guard remains fail-closed.
- [x] Provider-specific Voyage quota logic remains separate from the generic browser skill.
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
- Finalized the WSL2/Windows boundary around the official Extension: Web SOL sets `PLAYWRIGHT_MCP_EXECUTABLE_PATH` to the Windows Edge executable, injects `PLAYWRIGHT_MCP_EXTENSION_TOKEN` through `creds`, and attaches with `--extension=chrome --session=msedge`. Direct `DevToolsActivePort` CDP remains fallback only.
- Found an execution-boundary constraint during acceptance: a Playwright CLI daemon spawned inside Harness `code_mode -> run_command()` is cleaned up with that systemd/cgroup boundary, so the session does not survive into the next call. Direct Dive `wsl2_sync` preserves the CLI daemon and successfully reused `msedge` across separate calls. The trusted Web Skill now makes `wsl2_sync` + consistent `cwd=~/gpt-dive` the browser-session rule.
- Live attached through the official Playwright Extension with the user's existing Edge profile and no re-login or credential extraction. The token bypassed the repeated browser approval dialog.
- Reused the same session across calls; validated tab listing, bounded snapshot, read-only eval, filtered network listing, GET 200 observation, and bounded response-body read using a temporary public `example.com` tab.
- Closed only the temporary test tab and detached. The external Edge browser remained running, and a fresh Extension reattach succeeded without another approval click.
- Added trusted `~/wiki/skills/web/edge-playwright.md`, registered it in `skills/INDEX.md`, and routed bootstrap browser help to it.
- Removed the obsolete `edge-cdp.md` Web Skill outright.
- No Council browser transport source was modified.

Temporary compatibility dependency discovered during migration:

- Historical compatibility checkpoint: during the original browser migration, GBrain still depended on `/tmp/gpt-dive-council-edge.sock`, so coexistence with that bridge was live-validated. Later on 2026-08-14, GBrain's Voyage guard was replaced by a browserless direct-backend runtime; the old bridge is no longer a quota-guard dependency.
