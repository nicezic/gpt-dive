# GPT Dive Runtime Architecture

> 현재 구현 지도. Domain language는 `CONTEXT.md`, 결정 근거는 ADR 0004, 정확한 deadline 산식은 `timeouts.md`가 소유한다.

## 목적

GPT Dive는 하나의 불안정한 MCP 응답에 로컬 작업의 수명을 맡기지 않고 ChatGPT Web이 사용자의 WSL2 환경을 다루게 한다. ChatGPT Web은 이 workflow에 필요한 native MCP Tasks contract를 아직 제공하지 않으므로, GPT Dive가 실행을 로컬에서 durable하게 유지하고 bounded awareness layer만 공개한다.

```text
ChatGPT Web
      │ MCP
      ▼
bootstrap / code_mode / task
      │
      ▼
SQLite Execution control plane ───────────────┐
      │ accepted                              │ published Task
      ▼                                       ▼
Worker claim CAS                         TrackedTasks
      │                                       │
      ▼                                       └─ get / cancel / dismiss
Monty + 15 capabilities
      │
      ▼
local WSL2 + retained artifacts
```

MCP connection은 결과를 잠시 기다릴 수 있지만 작업 소유자가 되지는 않는다.

## Web MCP surface

```text
bootstrap
└─ 신뢰하는 fresh-session context 적재

code_mode(label, code, payload?, cwd?, mode=auto|task)
├─ durable Execution 하나 생성
├─ auto → bounded inline wait 뒤 result 또는 Task
└─ task → Task를 즉시 publish

task(request)
├─ list
├─ get       비파괴 조회
├─ cancel    명시적 cancellation만 수행
└─ dismiss   terminal awareness만 제거
```

고정 input object는 알 수 없는 property를 모두 거부한다. `code_mode`에는 `label`과 `code`가 필수이며 모델은 runtime deadline을 넘길 수 없다. Output은 `kind=completed|task|error`인 discriminated union(식별 필드로 variant를 고르는 합 타입)이다. `task`도 action-discriminated request와 action별 output을 사용한다. `execution_id`가 유일한 lifecycle identity다.

## 수락과 실행

```text
request artifact를 원자적으로 기록
        │
        ▼
SQLite에 accepted row commit
        │
        ▼
generic Execution Worker spawn
        │
        ▼
accepted → running CAS
   ├─ 거부 → 사용자 code 없이 종료
   └─ 성공 → request 적재 후 command spawn
                         │
                         ├─ stdout / stderr artifacts
                         ├─ outcome marker
                         └─ terminal SQLite transition
```

SQLite가 lifecycle 권위다. File은 request, log, bounded capability spill, 복구 증거를 담지만 독립적으로 state를 정의하지 않는다.

정상 backend는 `KillMode=control-group`을 적용한 transient `systemd --user` service다. User systemd가 없을 때는 Popen backend를 사용한다. Popen Worker는 Linux child subreaper가 되어 daemonized descendant까지 직접 종료하므로 `setsid`가 Execution 경계를 몰래 벗어날 수 없다. 어느 backend도 복구 중 사용자 code를 replay하지 않는다.

## Lifecycle과 awareness

```text
Execution state                         Task awareness

accepted                               unpublished
   │                                        │
running                                    published
   ├─ completed                             │
   ├─ failed(reason)                        dismissed
   ├─ cancelled
   └─ lost
```

두 축은 독립적이다. Publication은 작업을 재시작하거나 deadline을 바꾸지 않는다. Terminal Task는 명시적으로 dismiss할 때까지 남고, result 조회는 Task를 없애지 않는다.

Runtime 시작 시 non-terminal row를 Worker와 outcome evidence에 맞춰 reconcile(권위 있는 증거와 대조)한다.

- claim되지 않은 stale `accepted` → `failed(reason=launch_interrupted)`
- claim 이후 Worker와 outcome을 더는 확정할 수 없음 → `lost`
- 모든 state → 자동 replay/retry 없음

## Code Mode

각 Execution은 fresh Pydantic Monty program을 실행한다. 환경에는 `CWD`, live `CAPABILITIES` metadata, 그리고 caller가 제공했을 때만 `PAYLOAD`가 들어간다.

```text
FileSystem 8
├─ read_file / write_file / edit_file
├─ list_directory / search_files / find_files
└─ create_directory / file_info

Agent and model 3
├─ agy_worker
├─ subagent_call
└─ peer_review

Other 4
├─ repo_search
├─ council_emit
├─ run_command
└─ deadline_remaining
```

기존 내부 `task_*` capability는 제거했다. Task lifecycle은 top-level `task` tool이 소유한다. 모든 Execution이 수락 시점부터 durable하므로 `BACKGROUND`도 없다.

`agy_worker`, `subagent_call`, `peer_review`는 서로 다른 model-facing contract를 유지한다. 공개 signature에는 `timeout`이 없고 Runtime이 effective child budget을 공급한다.

### Filesystem 경계

Relative path는 `cwd`에서 해석한다. FileSystem과 Monty의 host-backed OS는 일반 OS permission 범위에서 host read/write를 허용하되, 공통 credential/secret pattern은 차단한다. Recursive search는 너무 넓은 root인 `/`와 `/mnt/c`를 거부한다.

### Direct command 경계

`run_command(command)`는 awaited capability 하나다. Execution의 cwd, sanitized environment, guard-bin `PATH`, 남은 work budget을 상속한다. 실행 중 output을 stream별 8 MiB까지 spool하고, model context에는 합계 8,000자 이하만 반환하며, 잘린 경우 bounded spill path를 함께 돌려준다. Stdout/stderr whitespace를 보존하며 결과는 다음과 같다.

```text
exit_code / stdout / stderr / duration_ms / truncated / spill_path?
```

`start_command`, `check_command`, `stop_command` mode는 없다.

## Runtime 밖으로 명시적으로 넘기는 작업

`systemd-run --user`를 명시적으로 호출하면 GPT Dive Runtime 밖의 sibling unit에 작업을 위임할 수 있다.

```bash
systemd-run --user --unit=gd-detached-<name> --collect \
  bash -lc '<long command>'
```

이는 운영자가 선언한 경계이며 untracked Runtime lane이 아니다. Sibling unit은 GPT Dive의 Execution, Task, TrackedTasks, retention, deadline 보장을 받지 않는다. Popen emulation은 만들지 않는다.

## Conduit

Conduit는 같은 `ExecutionManager`와 Task projection을 사용한다.

```text
@dive code_mode ─┐
                 ├─ SQLite executions ─→ shared TrackedTasks
@c start ────────┘
```

Conduit는 두 번째 Task store를 소유하거나 별도 ID를 만들지 않는다. `start/get/cancel/dismiss` lifecycle은 `execution_id`를 사용하며, Redis는 lifecycle 권위가 아니라 event fan-out 경계로 남는다.

## Retention

Terminal artifact는 5일 보존한다. 아직 dismiss하지 않은 Task의 retained outcome이 만료되면 `lost(reason=retention_expired)`로 계속 보이게 한다. Dismiss됐거나 publish되지 않은 terminal Execution은 retention 뒤 row와 artifact를 함께 제거한다. 장기 실행 server에서는 정상 API activity 중 시간당 최대 한 번 이 정리를 수행한다.

## Source map

```text
src/gpt_dive/
├─ app.py                 MCP tools, strict schemas, inline delivery, middleware
├─ execution_store.py     SQLite lifecycle and awareness transitions
├─ execution_manager.py   launch, observe, cancel, recover, retain
│                         Code Mode result normalization (envelope projection)
├─ execution_worker.py    claim-before-code and process-tree containment
├─ code_mode_worker.py    durable Monty worker envelope
├─ code_mode_protocol.py  worker envelope protocol version constant
├─ code_runtime.py        Monty runtime and capability registry
├─ code_capabilities.py   15 Code Mode capabilities
├─ command_runtime.py     awaited bounded run_command
│                         (TrackedTasks projection lives in app.py)
└─ conduit/               Runtime 위의 별도 conversation/event surface
```

## 참고 문서

- `docs/runtime/adr/0004-always-durable-code-mode-runtime.md`
  - Clean-break 설계와 폐기안의 accepted authority.
- `docs/runtime/adr/0005-post-renewal-simplification.md`
      - 리뉴얼 이후 구현 구조 단순화(간접층 제거)의 결정 기록.
- `docs/runtime/timeouts.md`
  - Response, work, cleanup, child-budget clock의 정확한 값.
- `docs/runtime/operations.md`
  - State 위치, 검증, service reload, failure 진단.
- `docs/pydantic/code-mode.md`
  - Monty와 capability programming contract의 상세 설명.
