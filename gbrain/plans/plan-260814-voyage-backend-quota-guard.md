# Voyage Browserless Free-Quota Guard

Date: 2026-08-14 KST
Status: implementation substantially complete; durable credential enrollment/refresh finalization pending; blocks Stable Index real embedding

> Canonical source-ID note (2026-08-16): the historical short IDs were re-keyed in place to `pydantic-ai` and `pydantic-ai-harness`. At the user's request, this historical plan now uses the current canonical IDs throughout; quota-guard observations and corpus counts remain the original 2026-08-14 evidence.

## Goal / Why

Correct the Voyage free-quota guard so it matches the original operating intent:

```text
stored credential
  -> Voyage backend API directly
  -> fresh server-side free-token balance
  -> validate voyage-code-3 quota
  -> PASS/BLOCK
  -> only then allow GBrain corpus embedding
```

The guard must work with **no browser, no Edge tab, no CDP/Playwright bridge, and no dashboard page open**.

The previous implementation preserved the important fail-closed invariant, but solved authentication by borrowing an already authenticated browser session. That is the wrong dependency for unattended/local backend operation and is now treated as an implementation error to replace.

This correction is the current blocker for the already-built Stable Index candidate. Do not start real candidate embedding until this plan's live acceptance passes.

Related prior plan:

```text
~/gbrain/plans/plan-260814-stable-index-upgrade.md
```

## Current State

### Stable Index state

Verified live on 2026-08-14:

```text
Production brain
  pydantic-ai          818 pages / embed 100%
  pydantic-ai-harness  326 pages / embed 100%
  total         1144 pages
  known chunks  21262 / embedded 21262

Candidate brain
  GBRAIN_HOME   ~/.cache/gbrain-stable-index-v1
  pydantic-ai          885 pages / embed 0%
  pydantic-ai-harness  319 pages / embed 0%
  total         1204 pages
  known chunks  21368 / embedded 0
```

Production remains untouched. Candidate is pre-embedding only.

Current GBrain checkout:

```text
repo        ~/gbrain
branch      local/voyage-free-quota-guard
HEAD        9ee4ba1d  feat: add stable index refresh pipeline
tag         local-stable-index-20260814-v1
runtime     gbrain 0.45.9.0
```

Relevant history:

```text
ae3bc5b3  local-voyage-guard-20260814-v2  current browser-dependent guard base
205c677b  parser fix for backtick inferred frontmatter titles
9ee4ba1d  stable index refresh pipeline
```

A GBrain product upgrade is a separate task and is not part of this correction.

### Current guard behavior

Tracked source:

```text
~/gbrain/local-patches/voyage-free-guard
```

Runtime copy:

```text
~/.local/bin/voyage-free-guard
```

GBrain integration:

```text
~/gbrain/src/commands/embed.ts
  -> runEmbedCore()
  -> validateEmbeddingCreds()
  -> assertVoyageFreeQuotaGuard()
  -> voyage-free-guard --json
```

For a configured `voyage:*` embedding model, a non-zero guard exit, invalid JSON, or payload without `guard == PASS` throws before embedding. This fail-closed placement is desirable and should be preserved unless a better common seam is proven.

### What is wrong in the current implementation

The current guard depends on:

```text
Edge / authenticated Voyage Usage page
  -> GPT Dive Edge bridge socket
  -> page /auth/access-token
  -> dashboard access token inside browser realm
  -> GET prod.dashboardbackend.voyageai.com/api/org/get_free_token/<ORG_ID>
  -> free-token result
```

Concrete browser dependencies in the current source include:

```text
VOYAGE_GUARD_SOCKET
VOYAGE_GUARD_PAGE
/tmp/gpt-dive-council-edge.sock
Voyage Free Usage page
bridge_request()
```

With no matching Voyage page open, live guard execution currently returns exit `70` and blocks embedding. The blocking behavior is correct, but the reason it cannot verify quota is the unwanted browser dependency.

`~/gbrain/local-docs/reconstruction.md` now explicitly marks the browser/CDP path as **legacy current implementation** and records browser-independent backend lookup as the required next architecture. After live acceptance, update that section again with the proven concrete credential/refresh mechanism and final runtime contract.

## Verified Authentication Evidence

### Existing credential

`creds` currently reports:

```text
voyage.primary    ai,human    present
```

`creds run ai` successfully injects `VOYAGE_API_KEY`; a secret-presence probe returned `KEY_PRESENT` without exposing the key.

### Important negative result

The known dashboard backend endpoint was called directly with the existing `VOYAGE_API_KEY` as Bearer authentication.

Endpoint shape:

```text
GET https://prod.dashboardbackend.voyageai.com/api/org/get_free_token/<ORG_ID>
Authorization: Bearer <VOYAGE_API_KEY>
```

The first HTTP/2 attempt ended with a transport `PROTOCOL_ERROR`, so it was not used as authentication evidence. Retrying over HTTP/1.1 returned:

```text
HTTP 401
response keys: code, errorCode, message
```

Therefore the existing Voyage embedding API key is **not proven usable as the dashboard-backend bearer credential**, and the HTTP/1.1 401 is current evidence that it is rejected on this endpoint.

Do not paper over this by assuming the wrong credential type or weakening the quota check.

### Auth0 browserless-auth investigation

Verified on 2026-08-14 without exposing user secrets:

```text
Auth provider   Auth0
issuer          https://voyageai.us.auth0.com/
client_id       REzfFrADBcRGAbcl4LZb0cHbxTruV3Qp
audience        https://apiauth0.voyageai.com
flow            Authorization Code + PKCE
scope           openid profile email offline_access
redirect_uri    https://dashboard.voyageai.com/auth/callback
```

The dashboard login UI publicly exposes both Email/Password and Google login. The Auth0 tenant OIDC metadata advertises `refresh_token`, `password`, and device-code grant types plus `offline_access`. However, a direct device-code probe against this Voyage dashboard client returned `403 unauthorized_client`, so device login is not currently available for this client.

A fake-credential password/password-realm probe reached `401 access_denied / Unauthorized` rather than `unauthorized_client`; this does **not** prove the user's real account can use password grant, but it means the next implementation step should determine the actual account login type and the correct refreshable credential path rather than assuming browser session reuse.

Current local `creds` inventory contains only `voyage.primary` (`VOYAGE_API_KEY`); no separate dashboard/Auth0 credential is registered yet.

The unresolved authentication question is therefore narrow: identify a durable, browser-independent Voyage dashboard credential/refresh path suitable for `creds`, then use it to obtain a fresh access token and call the backend quota endpoint directly.

### Implementation/live evidence added 2026-08-14

Subsequent live work narrowed and implemented the runtime path without exposing authentication values:

```text
actual account connection   google-oauth2
browser auth cookie         __session (HttpOnly + Secure + SameSite=Lax)
observed session roll       authenticated dashboard GET -> Set-Cookie __session; Max-Age=86400
access-token endpoint       GET https://dashboard.voyageai.com/auth/access-token -> HTTP 200
quota backend               GET .../api/org/get_free_token/<ORG_ID> -> HTTP 200
model                       voyage-code-3
totalFreeToken              200000000
live remainingToken         195443218 at acceptance time only
```

The balance above is historical evidence only and is never authorization for a later embedding run.

A direct WSL2 HTTP chain using a locally held dashboard session successfully reached `/auth/access-token` and then the quota backend with no browser request involved in that chain. The guard was then rewritten to perform this HTTPS path itself, including dashboard-session rotation and strict response validation.

The decisive source acceptance was performed by capturing the already-authenticated session locally, detaching Playwright until `playwright-cli list --all` reported `(no browsers)`, and then invoking the rewritten `fresh_quota()` path. It returned the same fresh accounting result and `guard=PASS` at the configured floor. The installed runtime now matches the tracked source exactly.

The session credential is intended to be a separate managed identity:

```text
id       voyage.dashboard-session
binding  ai:VOYAGE_DASHBOARD_SESSION
store    GNOME Keyring / creds
```

Automatic Web-SOL transfer of the browser session into Keyring was blocked by the platform safety layer, so that enrollment was not bypassed. The installed guard therefore currently fails closed with exit `70` when `VOYAGE_DASHBOARD_SESSION` is absent.

A further durability refinement is still worth resolving: Auth0 officially supports Authorization Code + PKCE + `offline_access` refresh tokens, and the Voyage authorize client did return an authorization code for a custom PKCE attempt. Before token exchange could be safely completed, an unsafe raw `playwright-cli tab-list` diagnostic exposed the Extension connection token and the one-time OAuth callback code in model-visible output. That authorization code was abandoned, Playwright was detached, and the generic `/edge-playwright` skill was immediately hardened to forbid raw tab listings and require Extension-token rotation after exposure. **Do not resume browser work with that exposed Extension token.** After the operator regenerates it and updates `playwright.extension`, the PKCE token-exchange probe may be repeated with all callback/token material filtered locally. If direct refresh-token ownership is unavailable for this Voyage client, the accepted fallback credential remains the rolling dashboard `__session`, with explicit local re-enrollment on its eventual absolute expiry; this is not a runtime browser fallback.

## Scope

### In scope

1. Determine the correct **browserless authentication path** for fresh Voyage free-token usage data.
2. Prefer a direct backend/API mechanism that can run from WSL2 with credentials supplied by `creds`.
3. Replace browser/CDP/socket/page dependencies in `voyage-free-guard`.
4. Preserve fresh server-side verification and fail-closed behavior.
5. Preserve the configured free-quota floor, currently `5,000,000` remaining tokens unless a deliberate policy change is separately approved.
6. Preserve model validation for `voyage-code-3` and strict response-schema checks.
7. Keep secrets out of stdout/stderr/logs/files and out of plan/Wiki documentation.
8. Add the smallest useful automated test seam for the guard behavior.
9. Perform live acceptance with the browser dependency absent.
10. Update reconstruction/operator documentation after the new path is proven.
11. Only after guard acceptance, return to the Stable Index plan for explicit candidate embedding authorization.

### Non-goals

- Do not run the 21,368 candidate chunk embedding as part of fixing the guard.
- Do not cut over the candidate brain during this task.
- Do not modify Index Filter v1 or stable source scope.
- Do not upgrade GBrain itself.
- Do not change Voyage embedding model or dimension.
- Do not auto-switch embedding provider/model on any failure.
- Do not add a cached quota fallback that can authorize spending from stale data.
- Do not require the operator to keep Edge, a Voyage tab, CDP, Playwright, or the GPT Dive Edge bridge alive.
- Do not expose or permanently write short-lived access tokens merely because that is convenient.

## Key Decisions

### Decision 1 - Browserless operation is an acceptance boundary

**Decision:** A guard that needs any browser state is not accepted.

**Reason:** The intended guard protects backend embedding operations. Safety must not depend on a human having a specific page open or a UI automation service remaining attached.

**Rejected alternative:** Keep the current browser bridge because it can obtain a valid dashboard access token. It works only when the browser/session/page preconditions happen to be satisfied and therefore violates the original operational goal.

**Consequence:** Authentication discovery may require a dedicated backend credential, refresh mechanism, or a different supported usage endpoint. That uncertainty must be resolved rather than hidden.

### Decision 2 - Fresh server truth remains mandatory (superseded)

> **Superseded 2026-08-15:** this was the original browserless-guard decision and is retained as historical design context. The accepted runtime contract now uses a local authoritative snapshot plus an append-only successful-call ledger, warns at 80% estimated usage, and blocks new corpus embedding when the snapshot reaches its 30-day reauthentication deadline. Explicit dashboard reauthentication/refresh replaces the baseline with current server truth. See `README.md` and `~/gbrain/local-docs/reconstruction.md` for the current operator contract.

**Original decision:** Preserve:

```text
no fresh verified free-quota result = no Voyage corpus embedding
```

**Original reason:** The free allowance was being treated as a spending boundary. At this stage of the design, a remembered or cached balance was not accepted to authorize a later embedding run.

**Originally rejected alternatives:** remembered balance, estimated balance, stale cache, or optimistic execution after lookup failure. The later local-accounting design supersedes this rejection by bounding estimation drift with a 30-day authoritative refresh requirement.

### Decision 3 - Embedding API key and usage-backend credential are separate until proven otherwise

**Decision:** Do not assume `VOYAGE_API_KEY` is the usage-backend credential.

**Reason:** A live direct call to the known quota backend with `VOYAGE_API_KEY` returned HTTP 401.

**Consequence:** If a separate credential is needed, store it through `creds` under a purpose-specific identity/binding. Do not hard-code it in GBrain config, source, Wiki, or shell history.

The exact credential type and refresh strategy remain an implementation-time fact to discover, not a pre-decided design.

### Decision 4 - Keep the GBrain common embedding gate

**Decision:** Preserve the pre-embedding check in the common `runEmbedCore()` path unless repository evidence shows a better single common seam.

**Reason:** It currently protects direct CLI embedding and internal corpus-embedding paths that reuse the core, and it already fails before provider spending.

### Decision 5 - No browser fallback

**Decision:** If the backend authentication or usage API fails, BLOCK. Do not silently fall back to the old browser path.

**Reason:** A fallback would keep the unwanted dependency alive and make unattended behavior non-deterministic.

## Implementation Direction

### 1. Discover the backend auth contract from evidence

Start by identifying how a non-browser client can authenticate for the free-token balance query.

Use the narrowest authoritative evidence available:

```text
current Voyage public API/docs if a usage endpoint exists
known dashboard backend request contract
network/auth behavior already observed
local credentials and previous implementation history
```

Do not assume a browser session token is long-lived or suitable for storage. Determine whether the backend supports one of these or another verified mechanism:

```text
dedicated API credential
refreshable machine credential
session/refresh credential usable without UI
supported usage/account endpoint authenticated by API key
```

The result must be reproducible after browser shutdown.

### 2. Define a credential boundary

If a new credential is required:

- store it with `creds`, not plaintext config;
- use a purpose-specific binding/environment variable;
- never print the secret to prove it exists;
- return only status/balance fields from probes;
- document how to reconstruct the credential binding without recording the secret value.

Do not reuse the `ai:VOYAGE_API_KEY` binding for a semantically different credential merely to reduce configuration count.

### 3. Rewrite `voyage-free-guard`

Target architecture:

```text
creds-provided backend auth
  -> direct HTTPS request
  -> validate HTTP success
  -> parse JSON
  -> locate voyage-code-3 row
  -> validate totalFreeToken / remainingToken
  -> compare floor
  -> JSON PASS or fail-closed exit
```

Remove runtime dependencies on:

```text
Edge
CDP / Playwright
GPT Dive Edge bridge
Unix socket
VOYAGE_GUARD_PAGE
VOYAGE_GUARD_SOCKET
browser /auth/access-token
```

Keep the output intentionally small. A successful `--json` result may expose non-secret accounting fields such as model, total, remaining, used, floor, and guard state. It must not expose authentication material.

### 4. Preserve failure semantics

Retain or clearly map the current useful distinction:

```text
auth/network/API/JSON/schema/model verification failure  -> BLOCK / non-zero
valid quota below configured floor                       -> BLOCK / distinct non-zero
fresh valid quota at or above floor                      -> PASS / zero
```

Current codes are `70` for verification failure and `42` for below-floor block. Preserve them unless implementation evidence gives a strong reason to change them, because callers/docs may already rely on the distinction.

### 5. Install/runtime consistency

After source tests pass:

```text
tracked source  ~/gbrain/local-patches/voyage-free-guard
runtime copy    ~/.local/bin/voyage-free-guard
```

Verify the runtime copy matches the tracked source before live acceptance.

### 6. Documentation correction

After acceptance, update at minimum:

```text
~/gbrain/local-docs/reconstruction.md
```

Remove the browser/Edge/CDP/socket requirements from the reconstruction SSOT and record the verified backend-auth reconstruction procedure without secrets.

Update `~/wiki/infra/gbrain.md` only if retrieval/operator routing materially changes. It should remain retrieval-focused rather than duplicating maintenance detail.

Update the Result section of this plan with actual credential/auth mechanism, validation, commit/tag, and remaining follow-up.

## Failure Policy

- Cannot identify a verified browserless authentication mechanism: **BLOCK**. Do not restore browser fallback as acceptance.
- Existing `VOYAGE_API_KEY` continues returning 401 for the quota backend: treat as expected evidence of credential mismatch, not as permission to bypass quota verification.
- Auth/network timeout or non-2xx response: **BLOCK**.
- Response is not valid JSON or expected model/token fields are missing: **BLOCK**.
- `modelName != voyage-code-3`: **BLOCK**.
- Token values are non-integers, negative, total <= 0, or remaining > total: **BLOCK**.
- Remaining free tokens below floor: **BLOCK**, no embedding.
- Secret appears in output/log/test fixture: **FAIL** and remove/redact before proceeding.
- Browser/CDP/socket is required for a supposed PASS: **FAIL**.
- Provider failure: never switch provider automatically.
- Stable Index candidate remains unembedded until this plan passes plus a separate explicit embedding authorization is given.

## Test Contract

No dedicated Voyage guard test currently exists under `~/gbrain/test` based on a live search on 2026-08-14, so add a narrow seam rather than a large speculative test suite.

Minimum behavioral tests:

1. **Valid quota response**
   - Given a verified response for `voyage-code-3` with remaining >= floor
   - When the guard evaluates it
   - Then exit 0 and `guard=PASS` with expected accounting fields.

2. **Below floor**
   - Given valid quota data with remaining < floor
   - Then exit 42 and no wrapped command executes.

3. **Authentication/API failure**
   - Given non-2xx or request failure
   - Then exit 70 and no wrapped command executes.

4. **Schema/model failure**
   - Given missing/wrong model or invalid token values
   - Then exit 70.

5. **Secret hygiene**
   - Failure output must not include bearer/API/refresh credentials.

6. **No browser dependency regression**
   - The accepted guard path must not require the Edge bridge socket, dashboard page, CDP, or Playwright.

7. **GBrain integration**
   - Use a controllable fake guard binary or equivalent seam to prove `runEmbedCore()` rejects guard failure before embedding and accepts guard PASS without weakening existing credential validation.

Avoid making real paid embedding requests in automated tests.

## Live Acceptance

The defining acceptance is browser independence.

### A. Browserless quota lookup

Precondition:

```text
No Voyage Usage tab required.
No Edge/CDP bridge dependency required.
```

Run the installed runtime guard through the intended credential scope.

Expected:

```text
exit 0
model == voyage-code-3
totalFreeToken is a positive integer
remainingToken is an integer in [0, totalFreeToken]
guard == PASS when remaining >= floor
no secret material in output
```

### B. Fail-closed live negative probe

With an intentionally unavailable/invalid auth input or isolated request seam, prove that lookup failure returns the verification-failure exit and does not invoke any wrapped command.

Do not damage or delete the real credential for this probe.

### C. GBrain preflight integration

Prove a Voyage-configured GBrain embedding path reaches the guard and blocks on guard failure **without issuing a real embedding request**. Prefer an injected/fake guard seam for this negative test.

### D. Runtime source parity

Verify:

```text
~/.local/bin/voyage-free-guard == ~/gbrain/local-patches/voyage-free-guard
```

### E. Documentation truth

`~/gbrain/local-docs/reconstruction.md` must describe the accepted browserless mechanism, not the superseded Edge/CDP implementation.

## Stable Index Resume Gate

Only after this plan is PASS:

```text
Browserless quota guard PASS
  + fresh real quota PASS
  + explicit operator authorization for this embedding run
      -> candidate 21,368 chunk embedding
      -> 100% / stale=0
      -> retrieval probes
      -> production cutover
      -> final production counts in ~/gbrain/local-docs/reconstruction.md
```

The guard fix itself is **not** authorization to perform the candidate embedding.

## Work Board

```text
Voyage Browserless Free-Quota Guard

[✓] ROOT-CAUSE / REQUIREMENT CORRECTION
[✓] BACKEND AUTH CONTRACT — dashboard session -> /auth/access-token -> quota backend verified without browser runtime
[✓] GUARD REWRITE
[✓] TESTS
[✓] BROWSERLESS LIVE ACCEPTANCE — installed `creds run ai -- voyage-free-guard --json` PASS with `playwright-cli list --all == (no browsers)`
[✓] DOCS / COMMIT — final acceptance evidence recorded; helper fix committed as `83952ac7`
[ ] RETURN TO STABLE INDEX ACCEPTANCE — requires separate explicit embedding authorization
```

## Result

**PASS — browserless quota guard complete; Stable Index embedding remains separately gated.**

Completed evidence:

- `VOYAGE_API_KEY` is not the quota-backend credential: direct HTTP/1.1 Bearer use returned `401`.
- The actual dashboard account connection is `google-oauth2`.
- The authenticated dashboard uses an HttpOnly `__session` cookie. A direct authenticated dashboard GET was observed to rotate it with `Max-Age=86400`.
- WSL2 direct HTTPS using that session reached `/auth/access-token` (`200`), then the quota backend (`200`), returning a valid `voyage-code-3` free-token row.
- After Playwright was detached and `playwright-cli list --all` reported `(no browsers)`, the rewritten guard's actual `fresh_quota()` HTTPS path returned a valid fresh balance and `guard=PASS` at the configured floor. This proves the **runtime request path is browser-independent**.
- `local-patches/voyage-free-guard` contains no Edge/CDP/Playwright/socket/page/bridge dependency.
- Runtime copy `~/.local/bin/voyage-free-guard` matches tracked source exactly.
- Missing `VOYAGE_DASHBOARD_SESSION` returns exit `70`; there is no browser or cached fallback.
- Python stdlib guard tests: 6/6 PASS; Ruff: 0 findings.
- Live GBrain fake-guard probe: `embed --all` stopped on the guard before provider work, and candidate sources remained `pydantic-ai 885 pages embed=0%` / `pydantic-ai-harness 319 pages embed=0%`.

Managed credential target:

```text
id       voyage.dashboard-session
binding  ai:VOYAGE_DASHBOARD_SESSION
store    GNOME Keyring via creds
```

Final acceptance:

- The managed `voyage.dashboard-session` credential is enrolled in GNOME Keyring with binding `ai:VOYAGE_DASHBOARD_SESSION`.
- The enrollment helper now reuses an existing Extension session or self-attaches when needed, never prints the cookie value, and detaches any session it created. Helper tests are 7/7 PASS; Ruff and installed/source parity PASS. Commit: `83952ac7`.
- Extension-token recovery is complete: replacement token registered, Edge restarted, and stable attach verified.
- Immediately before the final runtime test, `playwright-cli list --all` reported `(no browsers)`.
- `creds run ai -- ~/.local/bin/voyage-free-guard --json` returned exit 0 with `model=voyage-code-3`, total `200000000`, remaining `195443218`, used `4556782`, floor `5000000`, and `guard=PASS`. These numbers are historical acceptance evidence only.
- The direct Auth0 PKCE experiment remains rejected as unnecessary/unsupported durability research after the callback middleware returned `500 MIDDLEWARE_INVOCATION_FAILED`.
- The earlier raw-tab security incident was remediated by rotating the Extension token and hardening `/edge-playwright`.

Therefore the accepted runtime architecture is **direct backend HTTPS with a separately managed dashboard credential**. Browserless guard acceptance is complete. Stable Index embedding is still prohibited until separate explicit user authorization, and every later real embedding run must obtain a fresh guard PASS.

The guard fix is not embedding authorization. Candidate embedding remains behind the separate explicit operator approval gate.
