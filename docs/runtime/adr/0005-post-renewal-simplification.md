---
title: ADR - Post-Renewal Architecture Simplification
created: 2026-08-29
type: decision
status: accepted
---

# ADR 0005 — Post-Renewal Architecture Simplification

> 사용자의 요청(로직 단순화 및 개선)에 따라 AI 에이전트가 수행한 리팩토링의
> 결정 기록이다. 상위 설계 권위는 ADR 0004이며, 이 문서는 그 구현 구조를
> 단순화한 내용만을 다룬다. 실행 근거와 진행 과정은
> `plans/runtime/2026-08-29-simplification.md`에 있다.

## 결정 요약 (Decision summary)

ADR 0004의 외부 계약(MCP surface, Execution lifecycle, always-durable 보장)은
그대로 유지하면서, 구현 내부의 **간접층(indirection)과 중복을 제거**한다.
모든 변경은 main 대비 6개 커밋으로 이루어졌고, 매 커밋에서 143개 테스트가
통과했다.

```text
Before                                After
─────────────────────────────────────────────────────────────
app → task_runtime → exec_manager     app → exec_manager
exec_manager → execution_context      exec_manager (record dict 직접 전달)
store: 전이 SQL ×4                    store: _transition_to_terminal ×1
start → _spawn_worker                 start (inline, 원자 순서 가시)
error 생성 ×2                         _code_mode_error ×1
followup 등록 ×4 wrapper              _spawn_followup ×1
```

## 수용한 변경 (Accepted changes)

### 1. ExecutionStore 터미널 전이 통합 (d0f2a66)

`finish`, `fail_accepted`, `fail_running`, `mark_lost` 4개 메서드가 각자
유사한 SQL과 `cancel_requested` 가드를 반복했다. 단일
`_transition_to_terminal()`으로 합치고, 4개 public 메서드는 의미를 드러내는
thin wrapper로 남긴다. 호출부 13곳은 변경 없다.

### 2. ExecutionContext 제거 (acb1418)

`execution_context.py`는 3개 필드를 wrapping한 dataclass였다. helpers
(`remaining_seconds`, `child_budget`, `spill_path`)는 `command_runtime.py`로
옮기고, capabilities에는 execution record dict를 직접 전달한다.

### 3. task_runtime.py 레이어 제거 (2383330)

projection layer의 관심사를 자연스러운 소유 모듈로 분배했다:

| 관심사 | 새 소유지 |
|---|---|
| `CODE_MODE_WORKER_PROTOCOL` 상수 | `code_mode_protocol.py` |
| Code Mode envelope 파싱/정규화 | `ExecutionManager.result()`의 `_code_mode_projection()` |
| Task projection (`elapsed_seconds`) | `ExecutionManager._public_task()` |
| Task 오퍼레이션 (get/cancel/dismiss) | `ExecutionManager.task_with_result/cancel_task/dismiss_task` |
| TrackedTasks 렌더링 + `projection_revision` | `app.py` |

이로써 envelope 정규화가 SQLite control-plane 권위와 같은 모듈에 위치하게
되어, ADR 0004의 단일 권위 원칙이 구현 구조에도 일치한다.

### 4. spawn inline화와 에러 생성 통합 (efea5dd)

`_spawn_worker()`는 한 곳에서만 호출되는 private 메서드였다. `start()` 본문에
inline하여 "journal 기록 → worker 호출 → 실패 시 `fail_accepted` 롤백"의
원자적 순서가 한 몸에서 보이게 한다. 테스트는 private 메서드 대신
`subprocess.Popen`을 패치한다.

`CodeModeError` 생성 로직 두 벌(`_code_mode_delivery_error`,
`_code_mode_launch_error`)을 `_code_mode_error(code, message, reason=None)`
하나로 합친다.

### 5. followup 단일 진입점 (62f4350)

백그라운드 publication 후속작업 등록이 `_track_runtime_followup`과 3개
`_defer_*` wrapper로 흩어져 있었다. `_spawn_followup(coro)` 하나로 통합하고
wrapper를 제거한다. 재시도 로직(`_publish_during_launch`,
`_publish_execution`)은 변경 없다.

## 기각된 안 (Rejected)

### `start()`에서 `publish` 파라미터 제거

"발행은 전달 결정이므로 start에서 분리해야 한다"는 원래 계획과 달리, 실행
직전 검토에서 기각했다. `store.create(publish=)`는 행 생성 시점에
`published_at = accepted_at`을 **원자적으로** 설정한다. 이를 후속
`manager.publish()` 호출로 분리하면:

- 생성됐지만 미발행인 Task의 가시성 race가 발생하고 (TrackedTasks가 놓침)
- ~14개 호출부 변경 대비 LOC 절감은 0

ADR 0004의 원자성 보장이 마진 decoupling보다 우선한다. 근거는
`plans/runtime/2026-08-29-simplification.md`에 기록했다.

## 결과 (Outcome)

- 모듈 -2개 (`execution_context.py`, `task_runtime.py`), 테스트 1개 리네임
  (`test_task_runtime.py` → `test_task_projection.py`)
- main 대비 +646/−574 라인, 19개 파일
- 외부 계약 변경 없음: MCP tool schema, Execution 상태 전이, Task 가시성
  시맨틱 모두 불변
- 문서 동기화: `docs/runtime/architecture.md` 모듈 트리,
  `docs/runtime/CONTEXT.md` 구현 권위

## 참고 문서

- `docs/runtime/adr/0004-always-durable-code-mode-runtime.md`
  - 이 리팩토링이 보존한 lifecycle/delivery/deadline/persistence 결정 권위.
- `plans/runtime/2026-08-29-simplification.md`
  - 항목별 실행 계획, 검증 결과, 3.2 기각 근거의 원본 기록.
- `src/gpt_dive/execution_manager.py`, `src/gpt_dive/app.py`
  - 리팩토링 후의 구현 권위.
