# GPT Dive Runtime Evolution

> Why the stable runtime looks the way it does. This is architecture lineage, not package semantic versioning.

## Generation 1 — Local MCP Runtime

### v1 — MCP to Local WSL2

GPT Dive began as a narrow bridge from ChatGPT Web through the Secure MCP Tunnel into the user's own WSL2 environment.

The original need was direct local control: let Web SOL inspect repositories, execute commands, test changes, and operate the development environment without copying shell output between tools.

### v1.1 — `wsl2_sync`

A short synchronous shell path established the simplest direct-control primitive. It remains useful for brief commands where a programmable harness would add no value.

### v1.2 — `wsl2_async`

Long-running commands exposed a different problem: a synchronous MCP call blocks the current SOL reasoning flow until execution finishes.

GPT Dive added durable jobs with start/status/result/cancel semantics and a `JobManager` backend, normally using transient user systemd services. This gave local processes a lifecycle independent of the active MCP request and allowed jobs to survive MCP service restarts.

`wsl2_async` remains the low-level lifecycle escape hatch rather than the preferred high-level workflow API.

### v1.3 — `gz64`

Some shell payloads are awkward to transport directly because quoting, nested delimiters, or transmission filtering can interfere with the command text. `gz64` was added as a narrow encoded-command path for those exceptional cases.

Normal WSL2 execution remains the default; encoding is a transport workaround, not the primary interface.

## Generation 2 — Pydantic AI Harness

### v2 — `code_mode`

The key shift was from "a collection of shell tools" to a **harnessable programmable execution root**.

Pydantic Monty-backed `code_mode` lets SOL compose capabilities, run independent work concurrently, process large intermediate data locally, and return only the evidence that matters. Reusable behavior can grow behind the registry without expanding the Web-facing MCP surface.

This changed the preferred path to:

```text
bootstrap -> code_mode -> capabilities -> WSL2
```

rather than teaching SOL to orchestrate directly with many top-level tools.

### v2.1 — Background Code Mode

Code Mode could already perform internal async/parallel work, but the outer MCP call still blocked Web SOL until the whole Monty program completed.

The actual pain was not a lack of parallelism inside Python. It was that SOL could not continue the same reasoning flow while a long execution was running.

The accepted API preserved the common case:

```text
code_mode(code=...)
```

and exposed the uncommon detached case explicitly:

```text
code_mode(code=..., background=True)
```

The existing `JobManager` was reused; no second scheduler or workflow engine was introduced.

### v2.x — Extensible Harness and Subagents

The registry continued to grow with guarded local execution, durable job lifecycle adapters, `subagent_call`, workspace-scoped coding tools, and local output reduction.

The guiding principle is progressive extension behind Code Mode:

- keep the Web MCP surface stable;
- add reusable capabilities behind the harness;
- use subagents selectively, not as the default path;
- preserve strong local policy below every execution surface;
- avoid heavyweight orchestration infrastructure until a real pain requires it.

## Boundary to Generation 3

Generation 1 made local execution reachable. Generation 2 made it programmable and orchestratable.

Generation 3 introduces a different concern: a human-steered multi-model **Council** where USER, SOL, and OPUS share an evolving conversation and the transport between participants is automated without automating judgment.

Council architecture is documented under `docs/council/`; Council v1 was subsequently formalized in `specs/council.md`, implemented, and accepted end to end.
