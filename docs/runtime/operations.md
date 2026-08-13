# GPT Dive Runtime Operations

## Development

```bash
uv sync --python 3.14
uv run --python 3.14 python -m pytest -q
uv run --python 3.14 python -m gpt_dive
```

`pydantic-ai-slim` is currently pinned to a Git commit that provides the Codex subscription provider required by GPT Dive. The pin can be removed when the needed support is available in an upstream release.

## ChatGPT Web Schema Cache

ChatGPT Web can cache the MCP tool schema for the current conversation. After a schema-changing server update, an existing conversation may continue to expose the old signature.

Validate source changes locally first. Use a fresh ChatGPT Web session for live schema acceptance when the top-level MCP schema changes.

## Safe MCP Service Reload

Do not restart the active GPT Dive MCP/tunnel service inline while the current MCP call is still returning. Doing so can cut the transport underneath the response and leave the Web call pending.

When a live reload is initiated from the active ChatGPT session, dispatch it through `wsl2_async(start)` and let a detached `nohup` command perform the actual restart after a short delay:

```text
wsl2_async(
  action="start",
  command="nohup sh -c 'sleep 3; systemctl --user restart chatgpt-wsl2-mcp.service' >/tmp/gpt-dive-restart.log 2>&1 &",
)
```

Treat a successful `wsl2_async(start)` dispatch as the handoff boundary. Do not perform an in-session confirmation round-trip before or after the restart; the three-second delay exists only to let the initiating MCP response clear the transport before the service is replaced.

## Durable Jobs

Durable job state and logs live under:

```text
~/.local/state/gpt-dive/jobs/
```

Completed job logs are retained for 5 days. The normal backend is `systemd --user`; a detached-process fallback exists for environments where user systemd is unavailable.

## Council Browser Bridge

Council v1 owns a persistent Edge CDP connection through `gpt_dive.council.SolBridge` because reconnecting Playwright for every message triggers repeated browser approval friction. Playwright is input-only; SOL output returns explicitly through `code_mode -> council_emit`.

The historical feasibility experiment exposed a 600-second generic async-job timeout and stale-socket failure. The integrated Council runtime no longer uses that generic job lifetime as its effective session lifetime; the room owns bridge start/close. Keep `experiments/council_web_sol_e2e/` as historical evidence rather than production operations guidance.

Current manual Council startup remains `gpt-dive-council --council-dir <path> --sol-url <exact ChatGPT conversation URL>` until the post-v1 start/reopen capability is implemented. See `docs/council/startup.md`.
