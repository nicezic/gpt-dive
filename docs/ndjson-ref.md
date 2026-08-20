# NDJSON / ACP / Tunnel References

Recent reference implementations relevant to Conduit. Focus: **ChatGPT Web + tunnel** and **ACP over NDJSON/stdio bridged through WebSocket/tunnels**.

## Quick map

```text
ChatGPT Web / existing agent runtime
            │
      domain / session
            │
        ACP adapter
            │
      stdio / NDJSON
            │
    WS bridge / tunnel
            │
       remote client
```

NDJSON is framing/transport, not the canonical conversation domain. ACP is an external protocol projection; keep session/domain semantics below it.

## ChatGPT Web + tunnel

### miuuyy/codex-chatgpt-web ⭐ primary reference

https://github.com/miuuyy/codex-chatgpt-web

```text
Codex app / CLI
  → local Responses/SSE bridge
  → controlled ChatGPT Web
  → ChatGPT custom connector
  → outbound OpenAI tunnel-client
  → local Codex harness/tools
```

Why it matters:
- Uses **ChatGPT Web as the model backend**, not the OpenAI API.
- Full-harness mode returns ChatGPT tool calls to the current local Codex task through the official OpenAI tunnel-client.
- Strong prior art for browser-turn binding, session/task correlation, completion, cancellation, tool lifecycle, and tunnel capability binding.
- Local upstream reference: `~/ref/codex-chatgpt-web` with project-local CodeGraph index.

Architecture:
https://github.com/miuuyy/codex-chatgpt-web/blob/main/docs/architecture.md

### Dalomeve/codex-chatgpt-bridge

https://github.com/Dalomeve/codex-chatgpt-bridge

```text
ChatGPT Web
  → MCP App / connector
  → OpenAI Secure MCP Tunnel or HTTPS tunnel
  → local bridge
  → local files / Codex
```

Why it matters:
- Direction is close to Conduit: **ChatGPT Web remains the reasoning surface; local execution lives behind a tunnel**.
- Explicitly prefers OpenAI Secure MCP Tunnel when available.
- Useful reference for connector setup and tunnel-facing local bridge boundaries.

## ACP + NDJSON / tunnel

### openclaw/openclaw — ACP facade over an existing gateway ⭐

https://github.com/openclaw/openclaw/blob/main/docs/cli/acp.md

```text
ACP IDE/client
  → ACP over stdio
  → openclaw acp
  → WebSocket
  → existing OpenClaw Gateway/session
```

Why it matters:
- Very close to the desired Conduit layering: **existing canonical runtime/session stays intact; ACP is a bridge/facade**.
- Maps ACP sessions to Gateway session keys.
- Implements initialize/newSession/prompt/cancel and streaming updates without making ACP the internal domain.

Gateway protocol:
https://github.com/openclaw/openclaw/blob/main/docs/gateway/protocol.md

### MattKotsenas/uplink — ACP NDJSON + Dev Tunnel ⭐

https://github.com/MattKotsenas/uplink

```text
browser / phone
  ↔ HTTPS/WSS via Microsoft Dev Tunnel
  ↔ Node bridge
  ↔ WebSocket ⇄ NDJSON
  ↔ copilot --acp --stdio
```

Why it matters:
- Direct example of **ACP wire NDJSON wrapped by a WebSocket bridge and exposed through a tunnel**.
- Good reference for remote ACP transport, streaming, and browser/mobile access.

### formulahendry/acp-ui — stdio-to-ws + Dev Tunnels

https://github.com/formulahendry/acp-ui

```text
ACP agent stdio
  → @rebornix/stdio-to-ws
  → WebSocket
  → Microsoft Dev Tunnel
  → remote ACP UI
```

Why it matters:
- Useful operational reference for reconnect/session persistence.
- Documents `--persist` and grace-period behavior so an ACP child survives WebSocket disconnects.
- Dev Tunnel integration is moving toward being collapsed into the stdio↔WS bridge itself.

### aptove/bridge — ACP stdio + remote transports

https://github.com/aptove/bridge

```text
ACP agent stdio
  → StdioBridge
  → WebSocket
  → Local / Cloudflare Zero Trust / Tailscale
  → remote client
```

Why it matters:
- Clean transport separation around an ACP agent.
- Useful reference for remote transport, reconnect/security boundaries, and embedded-vs-subprocess bridge design.

### mmonad/codex-acp-gateway — protocol translation + raw ACP proxy

https://github.com/mmonad/codex-acp-gateway

```text
remote ACP client
  ↔ WebSocket
  ↔ gateway
  ↔ stdin/stdout NDJSON
  ↔ ACP agent
```

Why it matters:
- `acp-proxy` mode explicitly bridges **WebSocket frames ⇄ stdin/stdout NDJSON** without changing ACP semantics.
- Separate `codex` mode demonstrates protocol translation between Codex app-server and ACP.

### rebornix/Agmente — persistent remote ACP sessions

https://github.com/rebornix/Agmente

Setup:
https://github.com/rebornix/Agmente/blob/main/setup.md

```text
remote client
  → proxy / tunnel
  → localhost WebSocket
  → stdio-to-ws
  → ACP agent stdio
```

Why it matters:
- Practical reference for keeping ACP subprocess/session identity alive across reconnects.
- Explicitly recommends persistent child processes when agents cannot reload sessions themselves.

## Conduit takeaway

```text
ChatGPT Web SOL
      ↕
OpenAI Secure Tunnel / Conduit
      ↕
canonical Conduit session + events
      │
      ├─ Redis / NDJSON observers
      │
      └─ ACP projection
            │
         stdio / NDJSON
            │
       VS Code / Zed
```

Highest-value prior art:
1. `codex-chatgpt-web` — ChatGPT Web + official OpenAI tunnel + real local harness.
2. `openclaw acp` — ACP facade over an existing non-ACP gateway/session domain.
3. `uplink` — ACP NDJSON ↔ WebSocket ↔ tunnel transport.
4. `acp-ui` / `Agmente` — reconnect and persistent-session behavior.

Do not infer that Redis events, NDJSON records, or ACP messages should become Conduit's canonical domain. They are transport/projection evidence unless observed workflow pressure proves otherwise.
