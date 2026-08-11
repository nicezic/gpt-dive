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

When a live reload must be initiated from the active ChatGPT session, schedule it out-of-band with a buffer:

```bash
nohup sh -c 'sleep 5; systemctl --user restart chatgpt-wsl2-mcp.service' \
  >/tmp/gpt-dive-restart.log 2>&1 &
```

The five-second delay is intentionally conservative. Live acceptance showed that a shorter three-second boundary could coincide with reconnect timing.

## Durable Jobs

Durable job state and logs live under:

```text
~/.local/state/gpt-dive/jobs/
```

Completed job logs are retained for 5 days. The normal backend is `systemd --user`; a detached-process fallback exists for environments where user systemd is unavailable.

## Council Transport Experiment Note

The current Council Web SOL probe uses a persistent Edge CDP connection because reconnecting Playwright for every message triggers repeated browser approval friction.

A bridge launched through the generic async-job path inherits that job's timeout. The first experiment used the default 600 seconds and therefore exited after ten minutes, leaving a stale Unix socket path. The final Council lifecycle has not yet been specified; do not treat the experimental bridge command as production operations guidance.
