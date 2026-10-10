# Conduit — ACP / NDJSON Reference Notes

> Comparative upstream notes only, not an implemented Conduit ACP contract.

~~~text
ChatGPT Web / agent runtime → optional ACP adapter
                               → stdio / NDJSON framing
                               → WebSocket / tunnel
                               → remote UI or client
~~~

**Boundary:** NDJSON frames are a transport, not canonical conversation state. An ACP or WebSocket proxy should project existing Runtime/Conduit semantics rather than create a duplicate session/Task authority.

## Prior art

| Source | Relevant observation |
|---|---|
| [miuuyy/codex-chatgpt-web](https://github.com/miuuyy/codex-chatgpt-web) | ChatGPT Web as the model surface, with secure MCP tunnel and local Codex execution; relevant browser-turn correlation and completion contracts. |
| [Dalomeve/codex-chatgpt-bridge](https://github.com/Dalomeve/codex-chatgpt-bridge) | ChatGPT Web connector through tunnel to a local bridge. |
| [openclaw/openclaw](https://github.com/openclaw/openclaw) | ACP facade over a pre-existing gateway; reuse the lower domain model. |
| [MattKotsenas/uplink](https://github.com/MattKotsenas/uplink) | ACP NDJSON + development tunnel composition. |
| [formulahendry/acp-ui](https://github.com/formulahendry/acp-ui) | UI proxy between local stdio and WebSocket. |
| [aptove/bridge](https://github.com/aptove/bridge) | ACP stdio and remote transport adaptation. |
| [mmonad/codex-acp-gateway](https://github.com/mmonad/codex-acp-gateway) | Gateway as a protocol adapter, not an agent replacement. |
| [rebornix/Agmente](https://github.com/rebornix/Agmente) | Persistent remote session client patterns. |

Conduit currently implements an `@c` MCP transport with Redis events and a separate Git Room. ACP support is **experimental**, not a reason to add alternate protocol and session layers now. Experiments are in `experiments/conduit_acp_stdio/` and `experiments/conduit_acp_projection/`.
