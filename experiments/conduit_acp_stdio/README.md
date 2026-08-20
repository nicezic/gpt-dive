# Conduit ACP stdio Canary

Disposable normal-turn ACP v1 bridge experiment.

## Shape

```text
ACP client
  -> stdin NDJSON / JSON-RPC
  -> Conduit ACP canary
  -> existing Council SolBridge.send()
  -> logged-in ChatGPT Web SOL
  -> @c emit(session_id, text)
  -> Redis Conduit stream
  -> ACP session/update agent_message_chunk
  -> session/prompt stopReason=end_turn
```

The browser side reuses the existing input-only Council `SolBridge`; this experiment does not add another browser transport and does not scrape assistant output.

## Implemented canary surface

- `initialize` with ACP wire `protocolVersion: 1`
- `session/new` with generated `sessionId`
- text-only `session/prompt`
- one complete Conduit `emit` -> one `agent_message_chunk`
- successful complete `emit` -> `stopReason: end_turn`
- Redis correlation through top-level Conduit `session_id`

`session/cancel` is deliberately not claimed as complete. Real Web cancellation requires its own live acceptance; the canary does not fake cancellation.

## Acceptance status

```text
ACP initialize/session-new handshake       PASS
protocol-only NDJSON stdout                PASS
Conduit session_id production slice        PASS locally
live session/prompt -> Web -> emit -> ACP   NOT RUN yet
session/cancel live behavior                NOT RUN yet
```

The remaining E2E is intentionally not inferred from the local handshake.

## Local handshake evidence

Local stdio acceptance passed with no browser involvement:

```text
initialize -> protocolVersion=1, loadSession=false
session/new -> generated sessionId
stdout      -> NDJSON JSON-RPC only
stderr      -> empty
```

Ruff and Pyright both pass for the canary agent.

The production Conduit side now accepts optional top-level `session_id` on `emit`; focused Conduit validation passed with 9 tests, Ruff PASS, and Pyright 0 errors / 0 warnings. Legacy `emit(text=...)` remains valid.

Prompt ingress deliberately reuses the already-proven Council Edge/Playwright input-only `SolBridge.send()` path. Assistant output is not scraped from the browser; the correlated response must return explicitly through `@c emit(session_id=..., text=...)`.

## Live prompt acceptance prerequisites

- running Conduit MCP with the new optional `session_id` field;
- a fresh ChatGPT Web session that has accepted that live tool schema;
- exact existing ChatGPT conversation URL for `SolBridge.send()`.

The live prompt acceptance is one seam:

```text
session/prompt
  -> Edge input accepted
  -> Web SOL receives control + user payload
  -> Web SOL mirrors identical complete answer with @c emit(session_id=...)
  -> matching Redis event observed
  -> ACP agent_message_chunk
  -> end_turn
```

## Run

```bash
uv run --python 3.14 python experiments/conduit_acp_stdio/agent.py \
  --url '<exact ChatGPT conversation URL>'
```
