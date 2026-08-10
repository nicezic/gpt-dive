# GPT Dive — Current Continuation

> Updated: 2026-08-10
> Purpose: compact fresh-session handoff. Durable design history lives in `plans/` and `docs/`.

## Current Verdict

- MCP Surface v1: **FULL PASS ✅**
- Background Code Mode: **FULL PASS ✅**
- Full test suite before package refactor: **33 passed**
- Source layout refactor: `src/gpt_dive/` **FULL PASS ✅**

## Stable Web MCP Surface

Exactly four top-level tools:

```text
bootstrap
code_mode
wsl2_sync
wsl2_async
```

`code_mode` is the primary harnessable execution root. It supports foreground execution plus detached execution through `background=True` and lifecycle actions `status`, `result`, and `cancel`.

## Background Architecture

```text
code_mode(background=True)
        ↓
custom JobManager
        ↓
durable worker process
        ↓
fresh Monty runtime + registry rebuild
        ↓
strict JSON result envelope
```

`JobManager` is GPT Dive's custom durable process lifecycle manager, normally backed by `systemd --user`; it is not a Pydantic feature.

Fresh ChatGPT Web E2E acceptance completed with a real detached job: start returned `running`, status reached `completed`, and result returned `3`.

## Source Layout

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

Package entrypoints:

```text
python -m gpt_dive
gpt-dive
```

Workers use module execution rather than repository-relative script paths.

## Current Validation

After the `src/gpt_dive/` refactor:

```text
uv sync --python 3.14       PASS
pytest                      33 passed
uv lock --check             PASS
git diff --check            PASS
real systemd background     PASS, result=3
uv build                    PASS (sdist + wheel)
wheel guard assets          PASS
```

## Runtime Reload Rule

When changing the active MCP runtime, do not restart the service inside the same in-flight MCP call. Schedule an out-of-band/delayed restart so the current call returns first. Schema-changing acceptance should be done in a fresh ChatGPT session because Web may cache MCP schemas.

## Key Documents

```text
plans/2026-08-10-code-mode-background.md
plans/2026-08-10-src-layout.md
docs/architecture-context.md
docs/design-council-log.md
docs/meeting-notes.md
```

## Current Runtime

The tunnel launches `.venv/bin/python -m gpt_dive`. Safe delayed reload completed and a post-reload live Web MCP background smoke returned `result=3`. No acceptance gate remains for this refactor.
