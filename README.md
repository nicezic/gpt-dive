# GPT Dive

GPT Dive connects ChatGPT Web to the user's local WSL2 environment through a small MCP surface and a Pydantic-based execution harness.

```text
ChatGPT Web
  -> Secure MCP Tunnel
  -> GPT Dive
       -> bootstrap
       -> code_mode      # default programmable execution root, requires label
       -> task           # lifecycle operations (list, get, cancel, dismiss)
       -> wsl_exec       # emergency raw-shell fallback
```

Fresh structured sessions begin with `bootstrap`. Preload files come from `~/wiki/bootstrap/preload.json`. Periodic reminder cadence and whole-file/section sources come from `~/wiki/bootstrap/reminder.json`; the current map re-emits the full `USER_RULES.md` plus focused GPT Dive / Code Mode sections every 11 non-bootstrap `@dive` tool calls, and an explicit `bootstrap` resets that connection's counter. `ERROR_CASE.md` is read only after MCP/Dive failures. Reusable execution and orchestration behavior belongs behind `code_mode`; `wsl_exec` is reserved for emergency raw-shell access.

Code Mode enforces deterministic server-side execution deadlines (not AI arguments):

- **Always-Durable Execution:** All `code_mode` executions start with durable lifecycle tracking backed by SQLite, identified by a compact 6-character URL-safe `execution_id`, and require a descriptive `label`.
- **Inline Wait & Publication:** A fixed server-side response deadline, divided into a bounded inline delivery wait and an MCP response reserve. Live values live in [`docs/runtime/timeouts.md`](docs/runtime/timeouts.md).
  - If execution completes within the inline wait, the structured outcome (`completed` or `error`) is returned directly.
  - If execution exceeds the inline wait, the same continuing Execution keeps running uninterrupted in the background up to the work cutoff and is published as a tracked Task for subsequent `task` tool retrieval.
- **Direct Shell Execution:** Direct shell execution capability `run_command` is available within `code_mode` with bounded spool files and process-group containment, inheriting the full Execution work budget.

The full lifetime and cleanup contract is in [`docs/runtime/timeouts.md`](docs/runtime/timeouts.md).

## OpenAI Codex subscription

GPT Dive uses Pydantic AI's official `openai-codex` model/provider for ChatGPT subscription-backed Codex models. Authentication, credential refresh, transport, and Responses adaptation are upstream Pydantic AI responsibilities; GPT Dive only maps local aliases to provider/model identities.

## Documentation architecture & ownership

새 세션 작업이나 인수인계 시 아래 계층 구조와 읽기 경로를 따른다.

```text
[1. 세션 연결 / 현황]        CONTINUATION.md ── 최근 작업 delta 및 로컬 검증 상태
                                   │
                                   ▼
[2. 현재 동작 SSOT]     docs/runtime/architecture.md  ── 런타임 수명 / 프로세스 경계
                        docs/pydantic/code-mode.md    ── 15개 Capability 계약 / FS 경계
                                   │
                                   ▼
[3. 설계 근거 / Why]    docs/runtime/adr/             ── 아키텍처 결정 기록 (ADR 0004 ~ 0011)
```

| 문서 역할 | 경로 | 소유 권위 |
| :--- | :--- | :--- |
| **인수인계 (SSOT)** | [`CONTINUATION.md`](CONTINUATION.md) | 현재 목표, 최근 변경 delta, 검증 통과 상태 |
| **현재 아키텍처** | [`docs/runtime/architecture.md`](docs/runtime/architecture.md) | Durable Execution, 프로세스 격리, 파일시스템/명령 경계 |
| **Capability 계약** | [`docs/pydantic/code-mode.md`](docs/pydantic/code-mode.md) | Outer catalog stubs, `read_file` raw 계약, 샌드박스 정책 |
| **결정 기록 (ADR)** | [`docs/runtime/adr/`](docs/runtime/adr/) | 왜 그렇게 설계했는가 (ADR 0004~0011, 폐기 대안, 장애 계보) |
| **운영 & 재시작** | [`docs/runtime/operations.md`](docs/runtime/operations.md) | Systemd 터널 서비스 관리, 지연 안전 재시작 절차 |
| **Council** | [`docs/council/README.md`](docs/council/README.md) | 다자 협업 Room 아키텍처 및 Svelte 프론트엔드 |

Registered Code Mode capability signatures and callable docstrings are model-visible live contracts exposed through `CAPABILITIES` inside `code_mode`; the public MCP schema owns the outer tool contract. `bootstrap` loads the configured Wiki preload packet, not capability signatures. When capability behavior changes, keep its signature and docstring concise and accurate; detailed AI usage/routing policy belongs in the Wiki rather than being duplicated here.

## Evolution

```text
v1  Local MCP Runtime
     -> programmable Code Mode root / durable Task domain

v2  Pydantic AI Harness
     -> code_mode / background execution / subagents

v3  Council
     -> human-steered shared USER / SOL / OPUS room
```

These labels describe architecture generations, not package semantic versions.

Council grew from the user's successful manual SOL + User + Opus review workflow. Its purpose is to automate transport while preserving human steering, shared reasoning context, independent judgment, and the Why behind decisions.

Council v1 is implemented / FULL PASS. The current next product area is start/reopen ergonomics.

## Council

Start here:

- `docs/council/README.md` — compact current architecture and documentation map.
- `docs/council/history.md` — reasoning lineage: manual Council → Web SOL bridge → Shared Room → v1 → startup friction.
- `docs/council/startup.md` — approved post-v1 start/reopen direction and `init.md` context shape.
- `specs/council.md` — Council v1 implementation/decision SSOT and acceptance evidence.
- `plans/council/` — historical experiments and completed implementation plans.
- `CONTINUATION.md` — fresh-session live handoff.

## Development

```bash
uv sync --python 3.14
uv run --python 3.14 python -m pytest -q
uv run --python 3.14 python -m gpt_dive
```

For live MCP operations, see [`docs/runtime/operations.md`](docs/runtime/operations.md) — **how to restart**, reload safely, and handle durable jobs.

```text
systemd (system scope)
└─ gpt-dive-tunnel.service  # enabled: multi-user.target; Restart=always (2s)
   ├─ unit: /etc/systemd/system/gpt-dive-tunnel.service
   ├─ env:  /home/nicezic/.config/tunnel-client/wsl2-exec-u26.env
   └─ /home/nicezic/.local/bin/tunnel-client run --profile wsl2-exec-u26
      └─ /home/nicezic/gpt-dive/.venv/bin/python -m gpt_dive  # MCP server
```

One service restart replaces tunnel + MCP; `enabled` means WSL distro startup, not Windows boot. Code Mode executions use transient `gpt-dive-execution-*` user units.

Standard MCP restart handoff:

```bash
nohup bash -lc 'sleep 3; sudo systemctl restart gpt-dive-tunnel.service' >/tmp/gpt-dive-mcp-restart.log 2>&1 &
```

After dispatching this restart, **do not automatically verify or probe the restarted MCP from the same turn/session**. Return control to the user and wait for an explicit follow-up before checking PID, bootstrap, schema, or runtime state.

## Source layout

```text
src/gpt_dive/   # Python MCP runtime + harness + Council backend
web/            # Council UI: Svelte 5 + Vite + TypeScript
```
