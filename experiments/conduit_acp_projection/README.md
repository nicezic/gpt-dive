# Conduit ACP Projection Probe

Disposable schema-pressure probe for the first ACP bridge slice.

## Target

- ACP wire protocol: stable protocol version `1`
- ACP schema artifact observed during the probe: `v1.20.0`
- ACP v2 is alpha and is used only as a forward-compatibility check.

## Input

The probe reads the latest real Conduit `emit` event from `/tmp/conduit-events.ndjson`.

## Source conversation-plane canary

The projection probe is grounded in a real ChatGPT Web turn, not a synthetic event:

```text
ChatGPT Web final
  -> @c emit(full assistant text)
  -> emitted: true
  -> Redis Stream
  -> /tmp/conduit-events.ndjson
  -> identical result.text
```

Observed evidence:

- conversation-plane Mirrored Full Output canary: **PASS**
- Redis ID: `1787235113300-0`
- event action: `emit`
- `result.text` contained the complete assistant answer and ended with `Turn Marker: 7`
- the same event also carried the automatic `tasks` snapshot; that is task-awareness/transport evidence, not proof that `tasks` belongs in the canonical conversation domain
- this event predates ACP correlation and therefore has no `session_id`

`Turn Marker: 7` was temporary canary correlation only; it is not ACP or Conduit domain semantics.

## Result

The legacy canary event predates ACP correlation, so direct projection fails only because it has no `session_id`.

```text
projection probe             PASS
legacy event direct mapping  FAIL: session_id only
```

Deterministic normal-turn mapping:

```text
event.session_id
  -> ACP session/update.sessionId

event.result.text
  -> ACP agent_message_chunk.content.text

Conduit action=emit
  -> complete Mirrored Full Output
  -> ACP prompt stopReason=end_turn
```

The ACP ingress adapter owns user prompt content/direction, session creation, and active-prompt state; those do not need to be duplicated into the Web SOL output event merely to make the first bridge work.

Cancellation remains a separate live acceptance because a fake/no-op `session/cancel` mapping would not be ACP-correct.

Observed but deliberately excluded from the conversation domain without further evidence:

```text
redis_id
transport timestamp
automatic tasks snapshot
```

For the first ACP canary, a complete Conduit output may map to one `agent_message_chunk` followed by `end_turn`. This does not prevent later streaming chunks.

## Minimum production slice

The observed schema pressure required only optional top-level `session_id` correlation on Conduit `emit`. It is implemented in the production Conduit runtime/server while preserving legacy `emit(text=...)` behavior and the existing `result.text` shape.

Validation after that slice:

```text
focused Conduit tests  9 passed
ruff                   PASS
pyright                0 errors / 0 warnings
```

A fresh ChatGPT Web session remains the authority for live acceptance of the changed MCP field after restart/refresh.

## Run

```bash
uv run --python 3.14 python experiments/conduit_acp_projection/probe.py
```

## Primary references checked

- `agentclientprotocol/agent-client-protocol`: current stable wire `protocolVersion` is `1`.
- `agentclientprotocol/typescript-sdk/src/examples/agent.ts`: minimal `session/new`, `session/prompt`, `agent_message_chunk`, `stopReason`, and cancellation behavior.
- `google-gemini/gemini-cli/packages/cli/src/acp/README.md`: NDJSON stdio transport separated from RPC dispatch and session management.
