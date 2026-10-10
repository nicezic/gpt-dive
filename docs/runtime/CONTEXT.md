# GPT Dive Runtime Context

GPT Dive Runtime은 inline MCP 응답이 사라져도 안전해야 하는 Code Mode 작업의 언어와 lifecycle을 소유한다. ChatGPT Web은 이 workflow에 필요한 native MCP Tasks contract를 아직 제공하지 않는다. 따라서 Runtime이 durable execution(전송 연결과 무관하게 수명이 보장되는 실행)을 소유하고, transport connection을 작업 소유자로 만들지 않은 채 작은 awareness projection(인지용 축약 투영)만 공개한다.

## Mental model

```text
code_mode request
      │
      ▼
Execution을 durable하게 수락                         one execution_id
      │
      ▼
Worker가 Execution을 claim한 뒤 사용자 code 실행     구현 세부사항
      │
      ├─ inline wait 안에 result 전달 ─────────────→ Task 없음
      ├─ 즉시 awareness 요청 ─────────────────────→ Task publish
      └─ inline wait / transport가 먼저 종료 ─────→ Task publish
                                                        │
                                                        ▼
                                              TrackedTasks projection
                                                        │
                                                        ▼
                                                 명시적 dismiss
```

Publication은 기존 Execution을 드러내는 방법만 바꾼다. 작업을 이동·재실행·재시작하지 않는다.

```text
Execution 1 ── Worker를 통해 수행 ───── Worker 0..1
     │
     └── 필요할 때 공개 ─────────────── Task 0..1

Task 1 ── 가리킴 ───────────────────── Execution 1
```

## 용어

### Execution

**Execution**은 수락된 Code Mode 실행마다 생성되는 durable runtime record다. 수락, lifecycle state, deadline, cancellation, 결과와 artifact retention, 단일 공개 `execution_id`를 소유한다.

_피할 표현_: Job; durable identity를 뜻하면서 PID나 process라고 부르는 것; 차이가 응답 전달뿐인데 foreground/background execution이라고 부르는 것.

### Worker

**Worker**는 하나의 Execution을 수행하는 OS process 또는 transient systemd unit이다. `accepted` Execution을 원자적으로 claim한 뒤에만 사용자 code를 실행할 수 있다.

Worker는 구현 세부사항이며 공개 identity나 복구 가능한 workflow step이 아니다.

_피할 표현_: process/unit만 뜻하면서 Execution이라고 부르는 것; Job.

### Task

**Task**는 결과가 더 이상 inline으로 전달되지 않는 Execution을 위한 공개 awareness object다. Caller가 즉시 awareness를 요청했거나, 결과 전달 전에 inline wait 또는 transport가 끝나면 publish된다.

Task는 Execution이 terminal state에 도달한 뒤에도 명시적으로 dismiss할 때까지 보인다. 결과를 읽었다는 사실만으로 처리가 끝났다고 간주하지 않는다.

_피할 표현_: Job; process; 두 번째 execution record; 모든 Execution의 동의어.

### Task publication

**Task publication**은 Execution을 Task lifecycle과 TrackedTasks에 보이게 만드는 일이다. 정상적인 delivery decision이며 failure, detachment, replay, execution-state transition이 아니다.

_피할 표현_: automatic backgrounding; promotion; retry; foreground-to-background migration.

### Inline wait

**Inline wait**는 `code_mode`가 Execution 결과를 직접 반환하기 위해 기다리는 bounded period다. 이 wait가 끝나도 Execution은 취소되지 않는다.

_피할 표현_: 작업 자체를 가리키는 foreground execution.

### TrackedTasks

**TrackedTasks**는 publish됐고 아직 dismiss되지 않은 Task의 session-scoped compact projection이다. Web SOL이 보통의 tool activity 중 작업을 재발견하게 하되, 별도 manager나 persistence layer가 되지는 않는다.

_피할 표현_: Job list; Execution list; Web-facing projection을 Task store 또는 registry라고 부르는 것.

### CodeModeOutput

**CodeModeOutput**은 Code Mode 실행 및 Task 조회(`task(get)`)가 반환하는 단일화된 공개 출력 계약이다. Discriminator는 실행 상태를 가리키는 **`status`**다.

- `status="completed"`: 실행 완료. `result`에 최종 프로그램 결과 전달.
- `status="running"`: 백그라운드 진행 중. `state="running"`, `elapsed_seconds`, 그리고 `task(get)`을 안내하는 `guidance` 제공.
- `status="failed"`: 실행 실패. `error: {code, message, detail}`과 `guidance` 제공.

현재 세션에 active한 백그라운드 Task가 있을 때 `tracked_tasks`가 포함된다. `tracked_tasks_guidance`는 같은 Task 집합이 처음 보일 때와 이후 9개 응답마다만 재출력하며, Task가 없으면 둘 다 생략된다.

### Lost

**Lost**는 실행이 시작된 뒤 Runtime이 backing Worker나 retained result를 더는 진실하게 관찰할 수 없다는 terminal Execution state다. Lost 작업은 재구성·추측·replay·retry하지 않는다.

_피할 표현_: backing state가 확실히 사라졌는데 stale이라고 부르는 것; 실행이 어떻게 끝났는지 증명할 수 없는데 failed라고 부르는 것.

## 불변조건

1. 수락된 모든 Code Mode run은 사용자 code보다 먼저 durable Execution을 가진다.
2. `execution_id`만 공개 lifecycle identity다. Task는 별도 ID를 만들지 않는다.
3. Execution lifecycle과 Task awareness는 별개다. Publication과 dismissal은 execution state를 바꾸지 않는다.
4. Worker는 `accepted → running` CAS(Compare-And-Set, 예상 상태일 때만 수행하는 원자적 변경)에 성공한 뒤에만 사용자 code를 실행한다.
5. Runtime은 사용자 code를 자동 replay 또는 retry하지 않는다. 단, GPT Dive 밖에서 같은 MCP 요청이 재발행되면 새 Execution이 만들어질 수 있다. 특히 상위 응답 유실이 Runtime cancellation으로 전달되지 않은 경우, 완료된 inline Execution은 Task로 공개되지 않을 수 있다. 최상위 도구 오류 후 기존 실행 증거를 확인하기 전에는 부작용 있는 작업을 재요청하지 않는다.
6. Transport loss는 cancellation이 아니다. 명시적인 Task cancel 요청만 Execution을 취소한다.
7. Terminal result 읽기는 비파괴적이다. 명시적 dismissal만 Task awareness를 제거한다.
8. SQLite가 control-plane state의 권위다. Filesystem은 artifact를 저장할 뿐 경쟁 lifecycle truth가 아니다.

## 경계

`systemd-run --user`로 명시적으로 위임한 작업은 GPT Dive Runtime 밖에 있다. 생성된 sibling unit은 자체 supervisor lifecycle을 가지며 GPT Dive의 Execution, Task, TrackedTasks, retention, deadline 보장을 받지 않는다.

## 참고 문서

- `docs/runtime/adr/0004-always-durable-code-mode-runtime.md`
  - 여기 정의한 lifecycle, delivery, deadline, persistence, 공개 surface의 decision authority.
- `docs/runtime/adr/0005-code-mode-output-contract.md`
  - Code Mode의 local reduction, console/progress, final result 경계를 정의한 decision authority.
- [프로젝트 README](../../README.md)
  - Runtime과 Conduit의 컨텍스트 소유 경계 및 문서 지도를 보여준다.
- `src/gpt_dive/app.py`, `src/gpt_dive/execution_manager.py`
  - Renewal 이후의 구현 권위.
