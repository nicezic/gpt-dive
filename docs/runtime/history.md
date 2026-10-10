# GPT Dive Runtime 변화 기록

> Package semantic version 기록이 아니라 architecture lineage(설계 계보)다. 현재 동작은 `architecture.md`가 소유한다. 이 문서는 지금의 제약이 왜 생겼는지 설명하는 역사만 보존한다.

## Runtime을 만든 압력

```text
ChatGPT Web에 필요한 MCP Tasks negotiation이 없음
        │
        ▼
local sync / async command lane
        │
        ▼
background Code Mode + 별도 Task awareness
        │
        ▼
identity 2개 + store 2개 + launch race
        │
        ▼
clean always-durable renewal
```

약 120초의 tunnel drop은 transport-owned work의 비용을 드러냈지만 유일한 root cause로 확정된 적은 없다. Renewal은 transport 생존을 reality constraint로 취급하고, 고정 execution limit의 지속 가능한 근거는 resource containment에 둔다.

## 1세대 — 직접 WSL2 제어

GPT Dive는 ChatGPT Web에서 Secure MCP Tunnel을 거쳐 사용자의 WSL2 환경을 다루는 작은 bridge로 시작했다.

최초 surface는 transport 형태를 그대로 드러냈다.

- 짧은 blocking command용 `wsl2_sync`
- 긴 process의 start/status/result/cancel용 `wsl2_async`
- quoting이 까다로운 예외 command payload용 `gz64`

Durable async command는 당시 `JobManager`라고 부르던 구성요소를 통해 transient user systemd service로 실행했다. 이 이름과 top-level tool은 모두 역사적 표현이며 현재 MCP surface에는 없다.

## 2세대 — programmable Code Mode

Pydantic Monty 기반 `code_mode`는 공개 interface의 중심을 여러 shell tool에서 하나의 programmable execution root로 옮겼다.

```text
bootstrap → code_mode → registered capabilities → WSL2
```

Web SOL은 한 surface 안에서 독립 호출을 조합하고, 큰 중간 결과를 로컬에서 줄이며, 재사용 동작을 capability 뒤에 둘 수 있게 됐다.

### Background와 awareness 실험

Code Mode가 실행되는 동안 Web SOL이 계속 일하게 하려고 여러 형태를 시험했다.

1. foreground/background flag가 서로 다른 launch path를 골랐다.
2. Lifecycle action을 `code_mode`에 함께 넣었다.
3. 별도 SQLite `TaskStore`가 새 `task_id`를 filesystem-backed `execution_id`에 매핑했다.
4. 보통 tool traffic에 `TrackedTasks`를 붙여 완료 작업을 재발견하게 했다.
5. 이전 background flag 대신 optional `task={label,...}` object를 사용했다.

이 실험은 non-blocking awareness와 비파괴 result 조회의 사용자 가치를 입증했다. 동시에 renewal을 강제한 failure mode도 쌓였다.

```text
foreground path는 non-durable하게 시작
detached path는 다른 방식으로 시작
durable metadata 전에 process가 launch될 수 있음
execution_id → task_id mapping이 나중에 생성됨
filesystem metadata와 SQLite가 모두 authority를 주장
optional action field가 잘못 만든 인자를 조용히 흡수
```

이 시기에 작성한 Runtime ADR 3개는 모두 `status: proposed`였다. Accepted contract로 간주하지 않고 clean break 때 제거했다.

## 2026-08-27 — always-durable renewal

ADR 0004가 replacement model을 accepted로 확정했다.

```text
수락된 모든 Code Mode call
        │
        ▼
t=0부터 durable Execution
        │
        ├─ result inline 전달 → Task 없음
        └─ awareness 필요     → Task publish

Execution 1 → Task 0..1
public identity    = execution_id
control-plane SSOT = SQLite
```

Renewal은 의도적으로 clean break를 택했다.

- MCP tool을 `bootstrap`, `code_mode`, `task` 3개로 정리했다.
- Task lifecycle을 Monty capability 밖으로 옮겼다.
- `TaskStore`, `task_id`, `BACKGROUND`, caller-supplied timeout을 제거했다.
- Worker가 사용자 code 전에 `accepted → running`을 이겨야 한다.
- Transport loss는 work cancellation 대신 awareness를 publish한다.
- Work limit은 3,590초 + cleanup 10초가 됐다.
- Awaited `run_command`는 상속한 Runtime policy 안에서 반환한다.
- 실제 machine의 systemd cgroup 실험 뒤 `setsid nohup`을 거부했다. 명시적 `systemd-run --user` sibling delegation만 Runtime 밖에서 허용한다.

## 바뀌지 않은 것

이번 renewal은 GPT Dive를 workflow engine으로 만들지 않았다.

- 자동 replay/retry 없음
- 하나의 Task 뒤에 숨긴 retry chain 없음
- push-notification subsystem 없음
- unbounded execution lane 없음
- `agy_worker`, `subagent_call`, `peer_review` contract 통합 없음
- 새 `Job` domain term 없음

기존 Council은 단일 Conduit 제품의 `Room` 기능으로 정리되어 `docs/conduit/room/`에서 문서화한다. Conduit는 Runtime Execution/Task를 재사용하면서 대화/이벤트를 소유하고, Room은 Git 대화 기록을 소유한다.

## 참고 문서

- `docs/runtime/adr/0004-always-durable-code-mode-runtime.md`
  - Renewal의 accepted decision과 factual evidence.
- `docs/runtime/CONTEXT.md`
  - 현재 canonical language. 역사적 이름이 새 설계로 새어 들어오는 것을 막는다.
- `docs/runtime/architecture.md`
  - 현재 구현, source ownership, operational boundary.
- 2026-08-27 이전 Git history
  - 제거된 실험 API의 forensic detail이 필요할 때의 권위.
