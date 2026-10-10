# MCP stdio lifecycle and diagnostics

This is the operational SSOT for diagnosing the `tunnel-client -> GPT Dive` stdio boundary. Detailed implementation work belongs in `plans/plan-260819-mcp-stdio-cancellation-debug.md`.

## Runtime contract

```text
ChatGPT Web
    -> tunnel-client
    -> GPT Dive MCP server
         -> MCP Python SDK / AnyIO
         -> Pydantic AI / Harness / Code Mode

GPT Dive process
├─ stdout -> MCP JSON-RPC transport only
└─ stderr -> systemd user service -> journald diagnostics
```

- Never use stdout for runtime debug/error logging; it is the MCP protocol channel.
- Preserve runtime diagnostics through Python logging/stderr so `chatgpt-wsl2-mcp.service` journald can retain the real failure.
- `ExceptionGroup: unhandled errors in a TaskGroup` is a wrapper, not the root cause. Inspect its inner exception/lifecycle evidence before diagnosing.
- Upstream references: MCP Python SDK `docs/run/index.md` and `docs/troubleshooting.md`.

## Synthesized 502 semantics

`tunnel-client` uses HTTP `502 Bad Gateway` as a **synthetic outer status** when downstream MCP response forwarding fails before it can deliver a normal response. This does **not** mean GPT Dive returned HTTP 502.

The tunnel failure JSON-RPC data carries the useful provenance:

```text
tunnel_failure.version
tunnel_failure.source
tunnel_failure.transport_error_kind
tunnel_failure.upstream_response_received
tunnel_failure.upstream_status   # only when a real target HTTP response existed
```

Interpretation:

- `source=target_http` + `upstream_response_received=true` → an actual target HTTP status exists; inspect `upstream_status`.
- `source=transport_closed|timeout|dns|tls|connect|protocol` → the tunnel classified a transport/protocol boundary failure.
- `source=client_internal` + `upstream_response_received=false` → no target response was observed and the precise downstream cause is not established by the 502 alone.
- If GPT Dive has no matching `MCP REQUEST START`, do not attribute the failure to `code_mode` or a capability.

The JSON-RPC message may be only `Bad Gateway`; prefer the structured `tunnel_failure` data and local lifecycle logs when available.

## Server-owned model-visible failures

GPT Dive normalizes the failure classes it actually owns; it does not pretend to own tunnel failures:

```text
POLICY.USER_AUTH_REQUIRED   → error.category=policy; default-deny caller assertion guard
CodeModeFailed              → error.category + error.code + error.detail
MCP.SERVER.UNHANDLED        → error.category=mcp_server; unexpected tool failure observed by MCP server
synthetic 502/tunnel_failure → outside GPT Dive error categories; use tunnel provenance
```

MCP 2.0 normally reduces an unexpected tool crash to `Error executing tool <name>`. GPT Dive rewrites that exact generic result to compact JSON carrying `code=MCP.SERVER.UNHANDLED`, `category=mcp_server`, `request_id`, `tool`, and `recovery=inspect_first`. The original exception remains in server diagnostics; the normalizer does not invent or expose a cause it cannot prove. Anticipated detailed tool errors are left unchanged.

This middleware only runs when GPT Dive receives the request and can return an MCP tool result. A synthetic tunnel `502` created before a deliverable GPT Dive response is therefore **not** `MCP.SERVER.UNHANDLED` and cannot be normalized by GPT Dive.

## Known incident: 2026-08-19

ChatGPT Web intermittently surfaced only:

```text
ToolError: UNKNOWN
ExceptionGroup: unhandled errors in a TaskGroup
```

The local journal around 13:44:37 KST showed:

```text
MCP connection TTL reached; stopping response forwarding
stdio MCP command failed; requesting tunnel-client shutdown
reason="stdio MCP command stdin write failed"
error="write |1: file already closed"
```

Confirmed: the tunnel attempted to write to an already-closed GPT Dive stdio pipe and systemd restarted the service. A forked/multi-Web session did not create duplicate tunnel clients, GPT Dive processes, or `tunnel-dive.sock` listeners.

Not established: multi-session use, the tunnel, Pydantic AI/Harness, or AGY is the root cause. The missing fact is why GPT Dive stdio closed first.

## Triage

```text
1. Search current upstream GitHub issues/docs for the exact error pattern.
2. Inspect journald for the underlying exception and lifecycle ordering.
3. Verify current MCP schema, Code Mode CAPABILITIES, and runtime versions.
4. Trace the first failing boundary:
   tunnel -> GPT Dive server -> MCP SDK/AnyIO -> Pydantic/Harness.
5. Retry only from evidence; do not hide the failure behind a weaker fallback.
```

Useful commands:

```bash
journalctl --user -u chatgpt-wsl2-mcp.service --since '-10 min' --no-pager
journalctl --user -u chatgpt-wsl2-mcp.service --since '-10 min' --no-pager \
  | grep -Ei -C 8 'exception|error|traceback|taskgroup|cancel|closed|stdio|failed|exit|ttl'
```

Implementation testing confirmed one concrete lifecycle gap: cancelling an outer Code Mode run did not automatically cancel active async host-capability tasks. GPT Dive now tracks those tasks at the Code Mode registry boundary, cancels/reaps them during runtime cleanup, and lets capability-level cancellation cleanup run. This may explain earlier direct `agy_worker()` failures, but it is not proof that the same gap caused the 2026-08-19 tunnel incident. If the incident recurs, use the triage above and continue at the MCP SDK / AnyIO boundary from fresh journald evidence.
