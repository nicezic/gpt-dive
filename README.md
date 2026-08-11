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
- `code_mode`: **primary execution root**. Pydantic Monty-backed programmable mode for parallel work, registered local capabilities, filtering, transformation, and compact aggregation. Long programs can be detached with `background=True` and later managed with `action="status"`, `"result"`, or `"cancel"`. `CAPABILITIES` is discovery metadata only; invoke discovered capabilities directly by async name.
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


## ChatGPT session / service reload caution

ChatGPT Web caches the MCP tool schema for the current chat session. If GPT Dive changes a tool signature or other MCP schema, the existing session may keep the old schema; perform live schema acceptance in a fresh ChatGPT session.

Do not restart the active GPT Dive MCP/tunnel service while the current ChatGPT session is using it for an in-flight tool call. The call can remain pending until the user manually interrupts it. During implementation, validate source/schema changes through a separate local process first, return control to ChatGPT, and only reload the service out-of-band when live acceptance is actually needed.

When a reload is required from the active ChatGPT session, schedule it after the current MCP call has had time to return:

```bash
nohup sh -c 'sleep 5; systemctl --user restart chatgpt-wsl2-mcp.service' \
  >/tmp/gpt-dive-restart.log 2>&1 &
```

The delayed `nohup` restart is preferred over restarting the service inline: the tool call returns first, then the tunnel/MCP process is replaced a few seconds later. Check `/tmp/gpt-dive-restart.log` and the service state after reconnecting if verification is needed.

## Development

```bash
uv sync --python 3.14
uv run --python 3.14 python -m pytest -q
uv run --python 3.14 python -m gpt_dive
```

> Note: `pydantic-ai-slim` is temporarily pinned to a specific Git commit that provides the Codex subscription provider required by GPT Dive. This pin can be removed once the required support is available in an upstream release.

## Source layout

GPT Dive uses a standard Python `src` package layout:

```text
src/gpt_dive/
├── __init__.py
├── __main__.py
├── app.py
├── code_runtime.py
├── code_mode_worker.py
├── job_manager.py
├── subagent_runtime.py
├── subagent_worker.py
├── tasks_extension.py
└── guard-bin/
```

Workers are launched as package modules (`python -m gpt_dive.code_mode_worker` and `python -m gpt_dive.subagent_worker`) rather than by repository-relative script paths. This keeps imports stable and makes the installed package the same code exercised by tests and runtime.

### Workspace subagents

`subagent_call` inherits the parent Code Mode `cwd` unless an explicit `cwd` is supplied. A workspace-enabled child uses the official Pydantic AI Harness coding bundle rather than bespoke one-off tools:

- `FileSystem`: scoped read/write/edit/list/search/find/create/info with sensitive-path protection.
- `Shell`: generic command and background-process execution rooted at the workspace; Dive `guard-bin` stays first on `PATH`, and AI-provider credential variables are stripped from spawned commands.
- `RepoContext`: repository instruction/context discovery while traversing files.
- `ToolOutputLimits`: bounds oversized tool returns in the child history.

`FileSystem` enforces workspace path containment. `Shell` is intentionally broader and is not an OS sandbox; its denylist is defense-in-depth, not a hard isolation boundary.
