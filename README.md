# GPT Dive

GPT Dive is an MCP runtime that lets GPT operate the user's local WSL2 development environment with a small, stable Web-facing surface and extensible local execution behind it.

## Primary path

The normal operating path is:

```text
bootstrap -> code_mode -> registered capabilities -> WSL2
```

`code_mode` is the **primary execution root**. It is the harnessable surface where GPT can be constrained, extended, composed, parallelized, and made to reduce intermediate output before it reaches model context. Prefer adding reusable behavior and workflow rules to its capability registry instead of teaching GPT to bypass the harness with direct shell tools.

`wsl2_sync` and `wsl2_async` are lower-level direct-control paths for cases where the code-mode harness is unnecessary or explicit lifecycle control is needed.

## MCP Surface v1

- `bootstrap`: first call in every fresh ChatGPT Web session; loads trusted local Wiki context.
- `code_mode`: **primary execution root**. Pydantic Monty-backed programmable mode for parallel work, registered local capabilities, filtering, transformation, and compact aggregation. Inspect `CAPABILITIES` at runtime to discover the current registry.
- `wsl2_sync`: lower-level synchronous shell path for short commands that need an immediate result.
- `wsl2_async`: lower-level durable background-job lifecycle path. Use `action="capabilities"` to discover current actions.

This four-tool MCP surface is intentionally small. Prefer growing reusable behavior behind `code_mode`; extend `wsl2_async` only for durable-job lifecycle needs instead of adding new top-level tools.

## Enforcement layers

GPT Dive deliberately separates two kinds of control:

1. **Core execution policy** — hard rules such as `guard-bin` command restrictions apply below the tool surface and therefore remain active through `code_mode`, `wsl2_sync`, and durable async jobs. For example, direct native `python` execution is blocked regardless of which execution path reaches the shell.
2. **Harness policy** — orchestration rules, capability shaping, parallel composition, local preprocessing, and output/context reduction live primarily in the `code_mode` registry. This is where GPT should normally be guided and extended.

That separation keeps critical safety/operational rules difficult to bypass while allowing the main GPT workflow to evolve as a harness.

## Execution model

`code_mode` currently exposes registered local capabilities for short guarded execution plus durable-job start/status/result/cancel. These adapters reuse the same `_run_command` / `JobManager` engine as the lower-level tools; there is no second execution engine.

Jobs use transient user `systemd` services when available, survive MCP server restarts, and keep terminal state/logs for 5 days under `~/.local/state/gpt-dive/jobs/`. A guarded detached-process fallback is used when user systemd is unavailable.

Existing command guards remain active through `guard-bin`. `code_mode` mounts the local WSL2 filesystem read-write and is stateless between calls; large intermediate output should be filtered or aggregated inside Monty before returning it to the model.

When the client negotiates `io.modelcontextprotocol/tasks` on protocol `2026-07-28`, `wsl2_async(action="start")` can use the standard MCP Tasks lifecycle.


## Service reload caution

Do not restart the active GPT Dive MCP/tunnel service from inside the same live MCP call that depends on it. Restarting the transport before the current response returns can leave the call pending indefinitely. Return control first, then reload the service out-of-band or through a delayed mechanism.

## Development

```bash
uv sync --python 3.14
uv run --python 3.14 python -m pytest -q
uv run --python 3.14 python gpt_dive.py
```
