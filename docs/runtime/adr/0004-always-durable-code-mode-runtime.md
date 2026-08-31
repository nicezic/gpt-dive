---
title: ADR - Always-Durable Code Mode Runtime
created: 2026-08-27
updated: 2026-08-28
type: decision
status: accepted
---

# ADR 0004 — Always-Durable Code Mode Runtime

> 이 문서는 GPT Dive Runtime 리뉴얼의 단일 결정 권위(decision authority)다.
> 설계에 이르기까지의 검증 과정과 폐기된 안의 경위는 `0_design-session-260827.md`에 있다.

## 결정 요약 (Decision summary)

수락된 모든 Code Mode 호출은 **사용자 코드가 실행되기 전에** 하나의 durable Execution을 만든다. MCP 연결은 그 Execution을 잠시 기다릴 수 있을 뿐, 작업을 소유하지 않는다.

```text
code_mode(label, code, mode=auto|task)
                 │
                 ▼
       SQLite Execution: accepted
                 │
                 ▼
              spawn Worker
                 │
                 ▼
      Worker CAS: accepted → running
                 │
                 ├─ CAS 실패 ────────────────→ 사용자 코드 없이 종료
                 │
                 └─ CAS 성공
                          │
                          ├─ inline wait 안에 결과 도착
                          │      └─ completed 결과 반환, Task 없음
                          │
                          └─ 즉시 Task / wait 만료 / transport 절단
                                 └─ 같은 Execution을 Task로 publish
```

공개 모델:

```text
Execution 1 → Task 0..1
Execution 1 → Worker 0..1

공개 lifecycle identity = execution_id
control-plane authority = SQLite
filesystem 책임          = artifact 전용
```

이것은 **clean replacement**다. 기존의 foreground/detached 분리 API, 두 번째 `task_id`, `code_mode` 안의 lifecycle action, 두 저장소가 동시에 권위를 갖던 모델 중 어느 것도 보존하지 않는다.

## 왜 필요한가 (Why this exists)

ChatGPT Web은 현재 GPT Dive 워크플로가 필요로 하는 **MCP Tasks contract를 negotiate하지 않는다**. 그래서 GPT Dive는 자체 sync/async 경로를 만들었고, 비동기 작업을 놓치지 않으려 TrackedTasks를 덧붙였다. 그 결과 실행 수명(execution lifetime)이 **전달 방식(delivery mode)에 묶였고**, 상태가 두 개의 identity와 두 개의 authority로 흩어졌다.

```text
기존 압력
├─ inline MCP 응답이 tunnel 경계 근처에서 사라질 수 있음
├─ 동기 경로와 detached 경로가 서로 다른 방식으로 작업을 시작
├─ Execution 메타데이터는 파일에 존재
├─ Task awareness는 별도 SQLite 저장소에 존재
├─ execution_id 와 task_id 가 mapping gap 을 만듦
└─ durable control state 가 생기기 전에 프로세스가 먼저 시작될 수 있음
```

이 구멍들을 개별적으로 때우면 "**inline 작업은 async가 되기 전까지 durable하지 않다**"는 전제가 그대로 남는다. 리뉴얼은 그 전제를 제거한다. durability는 acceptance에서 시작하고, inline 반환이냐 Task awareness냐는 **전달 결정(delivery decision)일 뿐**이다.

우선순위는 다음 순서로 고정한다.

```text
containment
    > direct CLI ergonomics
    > 용어·문서 정합성
```

관측된 약 120초 tunnel 실패의 근본 원인을 **끝내 찾지 못하더라도** 설계는 옳아야 한다. tunnel은 현실 제약(reality constraint)이지, durable 작업이 존재하는 이유가 아니다.

## 리뉴얼을 강제한 근거 (Evidence)

2026-08-27, 리뉴얼 이전 소스에서 직접 확인한 사실:

- `ExecutionManager.start()`가 filesystem 메타데이터를 쓰기 **전에** 프로세스를 spawn했다.
- background Code Mode는 그 뒤에 Execution 참조 파일을 쓰고 별도 Task row를 만들어, crash window가 추가로 생겼다.
- Task와 Execution이 서로 독립된 UUID와 별도 persistence authority를 사용했다.
- SDK가 생성한 argument model이 unknown field를 무시해서, `timeout` 같은 **지어낸 인자가 조용히 사라졌다**.
- Code Mode 결과가 untyped `dict[str, Any]`여서, 두 가지 전달 결과를 구조적으로 구분할 수 없었다.
- 100초 inline cutoff은 `110 - 10`에서 **파생된 값**이었다. 독립 상수도 아니고, 일반적인 `deadline × 0.8` 계약도 아니었다.
- 기존 Runtime ADR 3건이 모두 `proposed` 상태였다. 하나도 accepted가 아니므로 **migrate·supersede가 아니라 삭제**할 수 있었다.

## 결정 (Decision)

### 1. 도메인과 identity

`Execution`, `Worker`, `Task`, `Task publication`, `Inline wait`, `TrackedTasks`, `Lost`의 의미는 `docs/runtime/CONTEXT.md`를 따른다.

`execution_id` 하나가 Execution을 식별하고, publish된 경우 그 Task까지 식별한다. Runtime은 `task_id`를 발급하지 않으며 identity mapping을 유지하지 않는다.

`Job`은 도입하지 않는다. `Job`이 가리킬 법한 durable control-plane 레코드는 이미 `Execution`이고, OS 프로세스나 systemd unit은 `Worker`다.

### 2. SQLite가 control-plane authority

SQLite가 소유하는 것:

- Execution identity와 필수 label
- lifecycle state와 terminal reason
- accept / claim / start / update / finish 타임스탬프
- runtime이 소유하는 deadline
- Worker claim과 liveness identity
- artifact 참조
- Task publication·dismissal 타임스탬프

filesystem은 request, stdout, stderr, result **artifact만** 저장한다. 파일이나 디렉터리 이름이 독립적인 lifecycle authority가 되는 일은 없다.

Execution 상태:

```text
accepted
    ├─ worker claim 성공 ──────────────→ running
    ├─ launch 완료 불가 ───────────────→ failed(reason=launch_interrupted)
    └─ 명시적 취소 ────────────────────→ cancelled

running
    ├─ 결과 commit ────────────────────→ completed
    ├─ 실행 오류 ──────────────────────→ failed(reason=...)
    ├─ work cutoff 도달 ───────────────→ failed(reason=deadline_exceeded)
    ├─ 명시적 취소 ────────────────────→ cancelled
    └─ backing truth 소실 ─────────────→ lost
```

`timed_out`은 **별도 상태가 아니다**. deadline 만료는 `failed`의 reason이다. `lost`는 Runtime이 결과를 정직하게 확정할 수 없을 때만 쓰며, 일반적인 실패 라벨이 아니다.

Task awareness는 이와 **직교(orthogonal)**한다.

```text
not published → published → dismissed
```

결과를 읽거나 collect하는 것은 dismiss가 아니다. dismiss는 completed / failed / cancelled / lost 도달 이후에만 허용된다.

### 3. Launch는 side effect 이전에 journaling한다

launch 순서는 고정이다.

```text
request artifact 를 atomic 하게 기록
        │
        ▼
SQLite 에 accepted Execution commit
        │
        ▼
Worker spawn
        │
        ▼
Worker 가 accepted → running CAS 로 claim 기록
        │
        ├─ CAS 실패 → 사용자 코드 실행 없이 종료
        └─ CAS 성공 → 사용자 코드 실행
```

부모는 Worker를 spawn했다는 사실만으로 사용자 코드를 authorize하지 않는다. **Worker 자신의 atomic claim이 authorization boundary다.**

복구는 작업을 재실행하지 않는다.

- claim되지 않은 채 남은 stale `accepted` → `failed(reason=launch_interrupted)`
- claim되었으나 Worker와 보존된 결과를 더 이상 관측할 수 없음 → `lost`
- 어떤 백엔드도 대체 사용자 코드를 자동으로 시작하지 않는다

### 4. 전달과 Task publication

모든 launch는 80자 이하의 비어 있지 않은 `label`을 요구한다. label은 Task 전용이 아니라 **Execution 메타데이터**다. Preview가 Task 존재 이전에 label을 필요로 하기 때문이다.

`mode`는 두 값을 갖는다.

```text
auto (기본값)
├─ 정해진 시간만큼 inline 으로 대기
├─ 시간 안에 완료 → completed 결과 반환, Task 생성 안 함
└─ wait/transport 가 먼저 끝남 → Task publish, Execution 은 계속 실행

task
├─ launch 시점에 Task publish
└─ Task 결과를 즉시 반환, Execution 은 계속 실행
```

Task publication은 Execution을 재시작·재생(replay)하지 않으며 deadline도 바꾸지 않는다.

### 5. 모든 deadline은 Runtime이 소유한다

```text
t=0       accepted Execution 존재
t=100s    auto 모드 inline wait 종료; 미전달이면 publish
t=110s    inline MCP 응답 deadline
t≈120s    관측된 외부 tunnel 경계 (Runtime 정책 아님)
t=43190s  Execution work cutoff; bounded 종료·drain 시작
t=43200s  Execution 절대 수명 종료 (12시간)
```

각 work/wait cutoff 이후의 10초는 bounded한 runtime bookkeeping·cleanup을 위한 **reserve**이며, 사용자 코드에 주어지는 추가 시간이 아니다.

모델은 Code Mode timeout도, child capability timeout도 지정할 수 없다. `agy_worker`, `subagent_call`, `peer_review`, `run_command`에 대해 Runtime이 다음을 계산한다.

```text
effective child budget
    = min(capability 정책, Execution 잔여 work budget)
```

`deadline_remaining()`은 현재 잔여 work budget을 **읽기 전용**으로 노출해, 코드가 "다음 단계를 시작할 가치가 있는가"를 판단하게 한다. caller가 timeout을 통제하던 경로를 되살리는 것이 아니다.

### 6. Transport 절단은 취소가 아니다

inline MCP wait이 취소되거나 끊겼는데 Runtime이 사용자 취소와 transport 절단을 구별할 수 없다면, Execution은 **계속 실행되고** Task로 publish된다. 명시적 `task(action="cancel")`만이 유일한 공개 취소 요청이다.

이는 transport 실패를 조용히 프로세스 종료로 바꾸는 것보다, 나중에 다시 찾을 수 있는 결과를 남기는 쪽을 **의도적으로 선호**한 것이다.

### 7. 공개 MCP surface와 엄격한 contract

공개 MCP surface:

```text
bootstrap
code_mode   Execution 하나를 launch 하고 bounded inline wait 수행
task        publish 된 Task 의 list / get / cancel / dismiss
wsl_exec    비상용 bounded raw shell
```

`wsl_exec`은 2026-08-30에 추가된 후속 escape hatch다. 이 ADR의 durable
Execution/Task contract에는 속하지 않으며, 재사용 workflow는 계속 `code_mode` 뒤에 둔다.

`code_mode` 입력(개념):

```text
{
  label: string,
  code: string,
  payload?: string,
  cwd?: string,
  mode?: "auto" | "task"       # 기본값: auto
}
```

`task` 입력(개념)은 엄격한 discriminated union이다.

```text
{action: "list"}
{action: "get",     execution_id: string}
{action: "cancel",  execution_id: string}
{action: "dismiss", execution_id: string}
```

`code_mode` 출력은 `kind`가 `completed` | `task` | `error`인 엄격한 discriminated union이다. 모든 envelope와 고정된 nested object는 unknown property를 거부한다. 열린 JSON으로 남는 것은 **실제 사용자 프로그램 결과뿐**이다.

acceptance 이전에 발생한 validation 실패는 MCP 입력 오류이며 Execution이 필요 없다. acceptance 이후의 결과는 `execution_id`를 갖는다.

옛 action 필드, `task_id`, optional field 남발, 호환 alias, 조용히 버려지는 unknown argument는 clean break에서 하나도 살아남지 않는다.

### 8. Code Mode capability

Task lifecycle은 내부 registry를 떠나 top-level `task` tool에 속한다. 남는 Code Mode 그룹:

```text
FileSystem (8)
Agent / model
├─ agy_worker
├─ subagent_call
└─ peer_review
Retrieval / Council
├─ repo_search
└─ council_emit
Runtime
├─ run_command
└─ deadline_remaining
```

모든 Execution이 처음부터 durable하므로 `BACKGROUND`는 제거한다.

agent/model 3종은 그대로 유지한다. 내부 transport 통합은 **이번 리뉴얼 범위가 아니다.** 바뀌는 것은 timeout 소유권뿐이다.

### 9. `run_command`는 await되는 단일 capability

`run_command(command)`는 소유 Execution 안에서 직접적인 CLI ergonomics를 복원한다. caller timeout이 없고 `start`/`check`/`stop` 모드도 없다.

요구사항:

- Execution의 작업 디렉터리, 정제된 환경, guard-bin `PATH`, effective child budget을 상속한다
- `/bin/bash -lc`를 통해 실행한다
- 명령 프로세스 그룹을 격리하고 bounded TERM → KILL → reap으로 종료한다
- 실행 중 stdout/stderr를 private `/tmp` working file에 stream별 최대 8 MiB까지 spool한다
- `.strip()`을 적용하지 않고 출력 경계를 보존한다
- terminal bounded evidence는 ADR 0008에 따라 SQLite 저장을 시도하며, 저장 실패는 원래 command 결과를 바꾸지 않는다
- Monty/모델 컨텍스트에는 compact preview만 전달한다
- `exit_code`, `stdout`, `stderr`, `duration_ms`, `truncated`를 반환하며 private evidence path는 반환하지 않는다

### 10. 장시간 작업의 명시적 위임은 Runtime 밖이다

12시간 Runtime 상한을 의도적으로 초과하는 작업은 명시적 명령으로 **형제 user unit**에 위임할 수 있다.

```bash
systemd-run --user --unit=gd-detached-<name> --collect \
  bash -lc '<long command>'
```

이것은 다른 supervisor에게 넘기는 **operator에게 보이는 handoff**이지, 무한한 Execution lane이 아니다. GPT Dive는 Task를 만들지 않고, unit을 추적하지 않으며, 결과를 보존하지 않고, 취소나 복구를 약속하지 않는다. 활성 unit은 `systemctl --user`로 조회·중지할 수 있고, 이후 출력 권위는 user journal이다.

`setsid`/`nohup`은 정책이 아니다. 로컬 실측 결과 systemd Execution cgroup **안에 그대로 남아** 해당 unit과 함께 죽었고, 반면 Popen 백엔드에서는 process group을 탈출할 수 있었다. 이 **백엔드 의존적 동작은 수용 불가**다.

`systemd-run --user`를 쓸 수 없는 환경을 위한 Popen 전용 에뮬레이션은 추가하지 않는다. 명령은 정상적으로 실패하고 stderr에 이유가 드러난다.

### 11. TrackedTasks는 bounded change awareness

TrackedTasks는 publish되었고 아직 dismiss되지 않은 Task를 담는다. terminal Task도 명시적 dismiss 전까지 남는다.

Runtime은 **보이는 내용이 변했을 때만** projection을 emit하고, 변화 없는 반복은 생략한다. 렌더링에는 hard byte 상한과 결정적인 limit/order가 있어, awareness가 모델 컨텍스트 안에서 무한히 자랄 수 없다.

TrackedTasks는 SQLite 상태 위의 projection이며, 결코 두 번째 저장소가 아니다.

## 귀결 (Consequences)

- inline 응답이 사라져도 실행 중인 작업의 소유권을 잃지 않는다.
- 가장 위험했던 launch gap이 사용자 side effect가 authorize되기 전에 닫힌다.
- ID 하나와 상태 authority 하나가 mapping·reverse index·reconciliation 로직을 제거한다.
- 한 호출이 두 가지 성공 전달 결과를 갖게 되지만, discriminated result가 그 구분을 명시한다.
- inline으로 완료된 Execution 대부분은 Task가 되지 않는다. 이는 **의도된 것**이다.
- 결과 조회가 비파괴적이므로 명시적 dismiss라는 lifecycle action 하나가 늘지만, 정직한 awareness를 지킨다.
- 12시간 상한은 통상적인 대형 테스트·빌드를 허용하면서 유한한 resource containment를 유지한다.
- 일상적인 명령을 subagent로 우회시키지 않고 직접 shell을 되찾되, 부모 Execution에 의해 여전히 bounded된다.
- clean break이므로 schema·persistence·test·문서 변경이 함께 움직여야 한다.

## 폐기한 대안 (Rejected alternatives)

### `Job` 도입

폐기. durable control-plane identity는 이미 `Execution`이고 OS 구현체는 `Worker`다. `Job`은 경계를 하나도 추가하지 못한 채 용어 마이그레이션만 다시 연다.

### 모든 Execution을 Task로 만들기

폐기. inline 전달과 미해결 awareness는 서로 다른 관심사다. 이미 정상 반환된 작업으로 TrackedTasks가 가득 찬다.

### 공개 ID 2개 유지

폐기. mapping table, 역방향 조회, 또 하나의 생성 gap을 더한다. "하나의 handle 아래 재시도"라는 요구가 현재 없다.

### foreground로 시작한 뒤 나중에 detach

폐기. 모델 자체가 틀렸다. Execution은 acceptance부터 durable하고, inline 경계에서 바뀌는 것은 **전달 채널뿐**이다.

### 불확실한 launch나 lost Execution을 replay

폐기. 사용자 코드에 외부 side effect가 있을 수 있다. 중복 실행보다 정직한 `failed` 또는 `lost`가 안전하다.

### 모델이 timeout 값이나 등급을 선택

폐기. containment 정책은 결정론적 runtime 코드에 속한다. 확률적 caller의 산술이 안전 경계가 될 수는 없다.

### agent/model 호출을 top-level MCP tool 또는 단일 `delegate` union으로

폐기. durable lifecycle contract가 중복되고, Code Mode 조합의 편의를 잃으며, deadline 소유권이 여러 root로 분열된다.

### Task lifecycle을 Code Mode 안에 유지

폐기. 코드를 launch하는 것과 이미 존재하는 공개 handle을 조작하는 것은 별개의 tool 선택이다. 확률적 caller에게는 전용 MCP tool이 더 명확하고, 엄격한 action variant를 허용한다.

### 상한 초과 작업에 `setsid nohup` 사용

폐기. cgroup 직접 검증으로 반증되었다. systemd supervision 경계를 신뢰성 있게 넘지 못하고, Popen fallback에서는 다르게 동작한다.

## Non-goal

- native MCP Tasks negotiation
- 자동 retry·replay 또는 workflow engine
- 하나의 공개 handle 아래 여러 Execution
- agent/model capability의 일반적 transport 통합
- 외부 `systemd-run --user` unit을 Runtime Task로 추적
- 기존 Runtime row·artifact·schema·method alias 보존
- `council_emit` 유지를 넘어선 Council 동작 확장

## 전달 순서 (Delivery order)

```text
1. glossary 와 이 ADR
2. SQLite journal + Worker claim CAS
3. always-durable launch, inline wait, deadline, Task publication
4. run_command + child budget 소유권
5. 엄격한 MCP/task contract + bounded TrackedTasks
6. stale runtime 문서 정리와 검증
```

테스트는 상태 전이, race 경계, 취소 containment, schema 폐쇄성, 출력 상한을 보호해야 한다. 낡은 private 구조나 호환 동작을 보존해서는 안 된다.

## References

- `docs/runtime/CONTEXT.md`
  - 이 결정이 사용하는 정식 도메인 언어와 invariant.
- `docs/runtime/adr/0_design-session-260827.md`
  - 이 결정에 이른 3자 리뷰 과정, 정정, 실측 기록.
- `CONTEXT-MAP.md`
  - Runtime 과 Conduit 사이의 컨텍스트 소유 경계.
- `docs/conduit/adr/0002-trackedtasks-refresh-and-opportunistic-evidence-pickup.md`
  - 일상적 활동이 비동기 작업 awareness 를 함께 나르는 이유(accepted).
- `docs/runtime/timeouts.md`
  - 여기서 결정한 clock 을 현재 계약으로 서술한 문서.
- `src/gpt_dive/app.py`, `src/gpt_dive/execution_store.py`, `src/gpt_dive/execution_worker.py`
  - MCP surface, control-plane authority, claim CAS 의 구현 authority.
- `src/gpt_dive/execution_context.py`, `src/gpt_dive/command_runtime.py`
  - child budget 계산과 `run_command` 의 종료·출력 제한 구현.
- `src/gpt_dive/worker_subprocess.py`, `src/gpt_dive/subagent_worker.py`
  - `run_command` 가 선택적으로 재사용한 기존 종료·환경·출력 제한 메커니즘.
