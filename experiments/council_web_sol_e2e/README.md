# Council Web SOL E2E Experiment

> Historical feasibility experiment. Council v1 later promoted the proven input-only CDP + MCP/Git output pattern into `src/gpt_dive/council/`; current architecture lives in `docs/council/README.md`.

This experiment proves the input/output transport boundary for the real ChatGPT Web SOL session.

## Proven path

```text
Local send
  -> persistent Playwright / Edge CDP bridge
  -> existing ChatGPT Web SOL conversation
  -> code_mode -> council_emit
  -> append-only chat.md block
  -> Git commit
```

Playwright is **input-only**. It does not scrape assistant output, inspect streaming completion, click Copy-response controls, or read the clipboard.

## Edge prerequisite

Use the normal Edge profile and enable remote debugging from:

```text
edge://inspect/#remote-debugging
```

Edge writes connection information to the normal profile's `DevToolsActivePort` file. The bridge discovers that file and keeps one CDP WebSocket connection alive for the Council session.

A new CDP attachment can trigger an Edge approval prompt. Keeping the bridge persistent avoids a new approval prompt for every message.

## Start the persistent bridge

The bridge is intentionally an experiment, not a production daemon. Give it an explicit lifetime when launching it through GPT Dive; the normal async-job default of 600 seconds is too short for a long Council session.

```bash
uv run experiments/council_web_sol_e2e/edge_bridge.py
```

It listens locally on:

```text
/tmp/gpt-dive-council-edge.sock
```

## Send one message

```bash
uv run --python 3.14 python experiments/council_web_sol_e2e/send_to_web_sol.py \
  --url '<exact ChatGPT conversation URL>' \
  --message '<Council message>'
```

The URL match is exact and must identify exactly one open tab.

## SOL output

The proven local primitive is the registered Code Mode capability:

```text
council_emit(council_dir=..., message=...)
```

It appends one `# SOL` block to `chat.md` and creates one Git commit. The commit is the local completion signal.

## Known lifecycle finding

A bridge launched through `wsl2_async` with the default 600-second timeout exits at ten minutes and can leave a stale socket path. A future Council runtime should own explicit bridge start/stop/session lifecycle rather than relying on that default timeout.
