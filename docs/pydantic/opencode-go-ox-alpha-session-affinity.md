# OpenCode Go / ox-alpha-free — `x-opencode-session` Session Affinity Notes

Investigated: 2026-08-24 (OpenCode v1.18.21, Linux, bun runtime)
Purpose: enable reliable tool calling on `ox-alpha-free` from an external Pydantic-AI harness.

## TL;DR

OpenCode Go gateway routes requests by consistent hash over the `x-opencode-session`
header value. Without the header, `ox-alpha-free` requests containing `tools[]`
currently fail ~100%. With a header value whose hash lands on a healthy backend
(~60% of values right now), tool calls work fine. Format does not matter;
only the raw string value (and its stability) matters.

Minimal recipe: send `x-opencode-session: <stable UUID per conversation>`.
On 503 / `finish_reason:"network_error"` / empty completion: retry same value ×2,
then rotate to a fresh UUID and keep the new one on success.

## Background

- Model: `ox-alpha-free` @ `https://opencode.ai/zen/go/v1/chat/completions`
  (OpenAI-compatible, `@ai-sdk/openai-compatible`, models.dev metadata: `tool_call: true`)
- Bug class: any request with `tools[]` → HTTP 503 "Upstream request failed:
  Endpoint is unavailable" (non-stream) or HTTP 200 stream ending with
  `finish_reason:"network_error"` + empty content (stream).
- Tracked upstream: anomalyco/opencode #44300 (canonical), #44382, #44379.
- Same payload works on other Go models (kimi-k3, deepseek-v4-flash,
  muse-spark-1.2-contributor, nemotron-3-ultra-free) → Ox-specific route issue.

## Confirmed facts (runtime experiments, 2026-08-24)

All tests identical body/key/endpoint; only headers varied.

| Test | x-opencode-session | Result |
|---|---|---|
| baseline ×10+ | none | FAIL (503 / network_error) 100% |
| random UUID ×8 | various | 7 OK / 1 FAIL |
| hex32 | value A | OK; repeat same value → OK (deterministic) |
| base62 mixed | value B | FAIL; repeat same value → FAIL (deterministic) |
| numeric-only | | OK |
| word-like strings | 2 tested | 1 OK / 1 FAIL |
| fake `ses_...` low entropy | | FAIL (unlucky slot, not format check) |
| real live OpenCode session ID | ses_fd043eed2ffe... | OK |
| streaming + good UUID | | OK, real `tool_calls` returned |
| empty header value | | FAIL |

Interpretation:
- Presence of the header switches routing path (headerless = currently dead route for ox tools).
- Value determines backend deterministically ⇒ consistent-hash session affinity.
- Currently ~40% of hash slots are broken for ox-alpha tools (11 fail / 27 tests).
- OpenCode internal calls always carry this header (source below), which is why
  they succeed while external clients fail; v1.18.20/21 retries absorb bad slots.

## Source evidence

- Header injection (opencode-* providers only):
  https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/llm/request.ts
  ```ts
  "x-opencode-project": <projectID if available>,
  "x-opencode-session": input.sessionID,
  "x-opencode-request": input.user.id,
  "x-opencode-client": input.flags.client,
  "User-Agent": `opencode/${InstallationVersion}`
  ```
  Non-opencode providers instead get `x-session-affinity` / `X-Session-Id`.
  Optional extra headers observed in binary but not required for success.
- network_error handling:
  https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/llm/ai-sdk.ts
  (`rawFinishReason === "network_error"` → provider failure → auto-retry per
  changelog v1.18.20/v1.18.21)
- Session ID generation:
  https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/id/id.ts
  ```
  now = ms * 0x1000 + counter
  sessions use "descending" → timePart = hex(48-bit ~now)   // 12 chars
  id = "ses_" + timePart + base62(14)                        // crypto.randomBytes
  ```
  Format is irrelevant to the gateway (proven experimentally); any unique
  opaque string works. Empty value fails.
- Session lifetime: one ID per conversation, created once, reused across all
  turns including small/title sub-model calls. DB evidence: single session row
  used continuously 17:47→18:42+ UTC. OpenCode never rotates it on provider
  errors (retry reuses the conversation's sessionID by construction).

## Recommended external algorithm

Session value format: `str(uuid.uuid4())` (or `secrets.token_hex(16)`; both verified).
Scope/lifetime: one value per logical conversation/thread; reuse across turns
and models; persist with thread state so restarts keep affinity.

Failure signals ("bad_route"):
- HTTP 408 / 429 / 500 / 502 / 503 / 504
- streamed `finish_reason == "network_error"` or missing/unknown finish reason
- completion with no content AND no tool_calls AND no reasoning

Policy mirrors OpenCode then improves on it:

```python
import time, uuid


def new_sid():
    return str(uuid.uuid4())


def classify(resp) -> str:  # ok | bad_route
    if resp.status in (408, 429, 500, 502, 503, 504):
        return "bad_route"
    fr = resp.finish_reason  # last chunk if streaming
    empty = not (resp.content or resp.tool_calls or resp.reasoning)
    if fr == "network_error" or fr is None:
        return "bad_route"
    return "ok" if fr in ("stop", "tool_calls", "length") and not empty else "bad_route"


def call_with_affinity(request_fn, state, max_same=2, max_rotate=4):
    sid = state.session_id  # persisted per thread
    delay = 0.5
    for _ in range(max_same):  # same-id retries (OpenCode-style)
        r = send(request_fn, sid)
        if classify(r) == "ok":
            state.session_id = sid  # keep binding
            return r
        time.sleep(delay)
        delay *= 2
    for _ in range(max_rotate):  # rotate on persistent bad route
        sid = new_sid()
        r = send(request_fn, sid)
        if classify(r) == "ok":
            state.session_id = sid  # re-bind to new healthy slot
            return r
        time.sleep(delay)
        delay *= 2
    raise ProviderUnavailable
```

Headers to send:
```http
x-opencode-session: <stable uuid>
Authorization: Bearer $OPENCODE_API_KEY
Content-Type: application/json
```
Optional (not required for success): `x-opencode-client: tui`,
`x-opencode-project: <opaque id>`, `User-Agent: opencode/<version>`.

Ops tips:
- Preflight once ("Say OK") when binding a new thread to avoid first-turn slot luck.
- Pool health drifts over time (#44382 showed working→broken windows within hours);
  the rotation path absorbs this automatically.
- Keep `toolCalling: true` viable again for UCP/Copilot via this header, but note
  this rides an undocumented routing behavior — watch #44300 for the server-side fix.
- Do not reuse another client's live session value long-term (works today, but
  pointless coupling); generate your own.

## References

- anomalyco/opencode #44300 — canonical: any tools[] → 503/network_error (open)
- anomalyco/opencode #44382 — UA matrix + timeline repro (open)
- NousResearch/hermes-agent #81584 — x-opencode-session changes outcome
- opencode changelog v1.18.20/v1.18.21 — retry on network_error / unknown finish
- Local verification: opencode.db message parts (bash tool_call by ox-alpha-free),
  ~/.local/share/opencode/log/opencode.log, binary strings of installed v1.18.21
