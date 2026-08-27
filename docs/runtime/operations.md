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
nohup bash -lc 'sleep 3; sudo systemctl restart gpt-dive-tunnel.service' >/tmp/gpt-dive-mcp-restart.log 2>&1 &
```

- `sleep 3` gives the initiating MCP response time to clear the transport.
- Do not wrap this restart handoff in detached Code Mode; its transient execution may clean up the detached child before the restart runs. Run the restart command directly in local bash.
- **Do not automatically verify after dispatch.** Return control to the user and wait for an explicit follow-up before checking PID, bootstrap, schema, or runtime state.

## Durable Executions

Durable execution state and logs live under:

```text
~/.local/state/gpt-dive/executions/
```

Completed execution logs are retained for 5 days. The normal backend is `systemd --user`; a detached-process fallback exists for environments where user systemd is unavailable.

## Council Browser Bridge

Council v1 routes SOL input through `gpt_dive.council.SolBridge` -> the named `msedge` Playwright CLI session -> the official Playwright Extension -> the user's existing logged-in Edge tab. `SolBridge` reuses an already-open CLI session or attaches it through the stored Extension token, and it gates each send on the ChatGPT composer being READY before inserting text and pressing Enter. Playwright remains input-only; SOL output returns explicitly through `code_mode -> council_emit`.

The historical feasibility experiment used direct Edge CDP plus a Unix-socket bridge and exposed a 600-second generic async-execution timeout and stale-socket failure. That transport is historical evidence only. The integrated Council runtime uses the current Extension transport and owns only its `SolBridge` lifecycle; if it created the `msedge` session it detaches it on close, while a pre-existing shared session is left alive. Keep `experiments/council_web_sol_e2e/` as historical evidence rather than production operations guidance.

Current manual Council startup remains `gpt-dive-council --council-dir <path> --sol-url <exact ChatGPT conversation URL>` until the post-v1 start/reopen capability is implemented. See `docs/council/startup.md`.
