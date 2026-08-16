# GPT Dive Runtime Operations

## Development

```bash
uv sync --python 3.14
uv run --python 3.14 python -m pytest -q
uv run --python 3.14 python -m gpt_dive
```

`pydantic-ai-slim` resolves from official stable releases. Subscription-backed Codex behavior is isolated in GPT Dive's local compatibility layer; see `README.patch.openai.provider.md` before changing provider wiring or upgrading Pydantic AI.

## ChatGPT Web Schema Cache

ChatGPT Web can cache the MCP tool schema for the current conversation. After a schema-changing server update, an existing conversation may continue to expose the old signature.

Validate source changes locally first. Use a fresh ChatGPT Web session for live schema acceptance when the top-level MCP schema changes.

## Safe MCP Service Reload

Use a detached delayed restart so the current MCP response can finish before the service exits:

```bash
nohup bash -c 'sleep 2; systemctl --user restart chatgpt-wsl2-mcp.service' \
  >/tmp/chatgpt-wsl2-mcp-restart.log 2>&1 &
```

- `sleep 2` gives the initiating MCP response time to clear the transport.
- Do not wrap this handoff in `wsl2_async`; its transient systemd job may clean up the detached child before the restart runs.
- Return immediately and verify only from a later or reconnected call.

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
