# GPT Dive — 현재 Continuation

> 갱신: 2026-08-28
> 용도: Runtime renewal을 새 세션에서 이어가기 위한 handoff. 설계 근거의 권위는 `docs/runtime/adr/0004-always-durable-code-mode-runtime.md`에 있다.

## 현재 목표

저장소 안의 clean replacement와 로컬 검증은 끝났다. 남은 경계는 실제 서비스에 새 schema를 반영하고 fresh ChatGPT session에서 수용 확인하는 일이다.

```text
설계 grilling 완료
        │
        ▼
glossary + ADR 확정
        │
        ▼
구현 + 로컬 검증 완료
        │
        ▼
서비스 reload + fresh-session acceptance 대기
```

제거한 API나 기존 Task DB를 위한 호환 계층은 만들지 않는다.

## 현재 계약

```text
Web MCP tools
├─ bootstrap
├─ code_mode(label, code, payload?, cwd?, mode=auto|task)
└─ task({action: list|get|cancel|dismiss, execution_id?})

Execution 1 → Task 0..1
공개 identity          = execution_id
control-plane 권위     = SQLite runtime-v2.sqlite3
filesystem            = 보존 artifact 전용
```

모든 Code Mode 호출은 사용자 code보다 먼저 durable(응답 연결이 끊겨도 실행 소유권이 남는 상태)해진다. Worker는 원자적 `accepted → running` 전이를 이겨야만 code를 실행한다. Inline 전달은 100초, MCP 응답 처리는 110초, 사용자 작업은 3,590초, 정리를 포함한 절대 수명은 3,600초로 제한한다. Transport loss는 Task를 publish하며, 오직 명시적 `task(cancel)`만 실행을 취소한다.

## 반영된 source delta

- `execution_store.py`, `execution_worker.py`, `execution_context.py`를 추가해 SQLite SSOT(Single Source of Truth, 단일 상태 권위), claim-before-code 경계, 상속 deadline, process-tree containment를 구현했다.
- `ExecutionManager`를 accepted-row journal, 단일 ID, 고정 deadline, outcome 복구, 5일 retention 기준으로 재구성했다.
- 공개 `code_mode`와 `task`를 strict typed contract로 교체했다. 알 수 없는 인자는 거부한다.
- 내부 `task_list/task_collect/task_cancel/task_ack`, `BACKGROUND`, caller timeout, 기존 lifecycle action, `TaskStore`를 제거했다.
- awaited `run_command` 하나를 복원했다. guard-bin, secret 환경변수 제거, bounded live spool, 8,000자 context 출력, spill, TERM/KILL/reap을 적용한다.
- `agy_worker`, `subagent_call`, `peer_review`, `m3_evidence`, `repo_search`, `council_emit`은 Code Mode 내부에 유지했다. Child budget은 Runtime이 공급한다.
- Conduit를 같은 Execution/Task row와 단일 `execution_id` 위로 옮겼다. 현재 action은 `start/sync/get/cancel/dismiss/emit`이다.
- 독립 리뷰 후 private spool 생성, bounded TrackedTasks 조회, launch 중 inline cutoff·response reserve·accepted Task publication, stale-accepted recovery, signal 의미, 단일 cleanup reserve를 회귀 테스트와 함께 보강했다.
- `/proc` PID identity를 공통 모듈로 모으고 worker cleanup interface를 공개했으며, `repo_search`도 process-group 단위 bounded worker 경로로 통일했다.

## 로컬 검증

- 전체 pytest: `200 passed`
- Ruff: 통과
- Pyright: 통과
- `git diff --check`: 통과
- Popen smoke: 정상 완료, 명시적 취소, deadline 실패, `setsid` descendant 정리 통과
- 실제 `systemd --user` smoke: `accepted → completed` 및 출력 보존 통과
- 생성된 MCP schema: tool 3개와 고정 request object의 `additionalProperties:false` 확인

이 checkpoint 뒤 source가 바뀌면 위 gate를 다시 실행한다.

## 배포 경계

저장소 작업 완료만으로 live schema가 수용된 것은 아니다. ChatGPT Web의 기존 conversation은 이전 tool contract를 cache할 수 있다.

1. 사용자가 요청하면 `git diff`를 검토하고 commit한다.
2. `docs/runtime/operations.md` 절차로 지연 MCP/tunnel restart를 보낸다.
3. restart를 보낸 응답에서는 추가 MCP call을 하지 않는다.
4. 새 ChatGPT session을 연다.
5. bootstrap, tool 3개 schema, inline 완료, 즉시 Task, 비파괴 get, cancel, dismiss, change-only TrackedTasks, `run_command`를 확인한다.

## 문서 권위

- `docs/runtime/CONTEXT.md`
  - Execution, Worker, Task, Task publication, Inline wait, TrackedTasks, Lost의 canonical language.
- `docs/runtime/adr/0004-always-durable-code-mode-runtime.md`
  - 확정 설계, 근거, 폐기안, deadline, delivery order.
- `docs/runtime/architecture.md`, `docs/runtime/timeouts.md`, `docs/runtime/operations.md`
  - 현재 구현 구조, clock 계약, 운영 절차.
- `docs/conduit/CONTINUATION.md`
  - Conduit renewal 변화와 다음 작업.

Council, GBrain, provider, Pydantic compatibility 작업은 이번 Runtime renewal의 범위 밖이다. 이전 handoff의 완료된 TODO를 되살리지 말고 각 context 문서로 routing한다.
