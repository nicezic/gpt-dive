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
