# Standard `src/gpt_dive/` Package Layout

## Goal / Why

GPT Dive has grown from a small script into an MCP application with Code Mode, durable jobs, workers, subagent runtime, and an extension layer. Move the runtime into a standard Python `src` package so imports, workers, tests, and the live entrypoint all use one explicit package boundary.

## Current State

Before this change the Python modules lived at repository root and workers were launched by repository-relative script paths. The runtime already had 33 passing tests and Background Code Mode had passed fresh-session Web MCP E2E acceptance.

## Scope

- Move runtime Python sources to `src/gpt_dive/`.
- Keep the four-tool MCP surface and behavior unchanged.
- Add package entrypoints and build metadata.
- Make worker execution package-native.
- Keep the command guard policy intact.

Non-goals: runtime redesign, MCP schema changes, JobManager redesign, capability changes.

## Key Decisions

### Decision — real package, not flat `src/`

Use `src/gpt_dive/` with `__init__.py` and `__main__.py`.

**Reason:** gives GPT Dive one namespace, makes installed-package imports explicit, and supports stable module entrypoints.

**Rejected:** placing unrelated top-level modules directly under `src/`; this moves files but does not create a package boundary.

### Decision — `app.py`, not `server.py`

The MCP implementation lives in `src/gpt_dive/app.py`.

**Reason:** avoids the previously disliked generic `server.py` name while avoiding a `gpt_dive.mcp` module name collision with the exported MCP object.

### Decision — module workers

Launch workers with `python -m gpt_dive.code_mode_worker` and `python -m gpt_dive.subagent_worker`.

**Reason:** workers resolve through the installed package rather than depending on the repository-relative script location.

### Decision — package the guard assets

Move `guard-bin/` under `src/gpt_dive/`.

**Reason:** `_run_command` and `JobManager` continue to resolve the same adjacent guard path, and the execution policy ships with the runtime package.

## Failure Policy

If package installation, worker module resolution, guard discovery, or live service startup fails, stop and fix the packaging boundary. Do not add fallback imports or dual root/src execution paths.

## Test Contract

1. `uv sync --python 3.14` installs `gpt-dive` successfully.
2. Full pytest suite remains green.
3. Native command guard tests remain green.
4. A fresh local package process can launch Background Code Mode through the real systemd backend and retrieve `result=3`.
5. `uv build` produces sdist + wheel and the wheel contains `gpt_dive` runtime plus `guard-bin` assets.
6. Live tunnel configuration launches `python -m gpt_dive` and the four-tool MCP surface remains operational after reload.

## Result

**FULL PASS ✅** — package refactor, build, service reload, and live Web MCP acceptance completed.

- `uv sync --python 3.14`: PASS; editable project installed as `gpt-dive==0.1.0`.
- full suite: `33 passed`.
- `git diff --check`: PASS.
- `uv lock --check`: PASS.
- real systemd package smoke: completed, `result=3`.
- `uv build`: sdist + wheel PASS; wheel includes runtime + guard assets.
- tunnel launch command: `.venv/bin/python -m gpt_dive`.
- delayed service reload: PASS; service active after reconnect.
- post-reload live Web MCP Background Code Mode: systemd start → completed → `result=3`.
