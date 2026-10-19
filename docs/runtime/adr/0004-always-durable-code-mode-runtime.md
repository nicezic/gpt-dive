---
title: ADR 0004 — Durable Execution and Task Lifecycle
created: 2026-08-27
updated: 2026-10-20
type: decision
status: accepted
---

# ADR 0004 — Durable Execution and Task Lifecycle

## Decision

모든 `code_mode` 요청은 사용자 코드를 시작하기 전에 SQLite에 단일 `Execution`으로 수락한다. MCP 응답의 유실이나 timeout은 그 수명을 소유하지 않는다. `Worker`는 claim CAS 이후 실행하고, `Task`는 필요할 때 같은 `execution_id`를 공개하는 인지 객체일 뿐 독립 작업이 아니다.

~~~text
code_mode(label, code, delivery=auto|task)
  → SQLite Execution (accepted) → Worker claim → Monty
                   ├─ inline 완료 → completed
                   └─ Task 공개  → task(get/cancel/dismiss)
                                같은 execution_id
~~~

- `delivery=auto|task`는 서로 다른 실행 종류가 아니라 결과 전달/Task 공개 방식이다.
- `status=completed|running|failed`는 공개 실행 결과 상태이며, `result`는 Monty의 최종 결과다.
- SQLite가 lifecycle의 유일한 권위다. 파일과 로그는 증거이지 두 번째 상태 저장소가 아니다.
- `task(get)`은 비파괴 조회, `task(dismiss)`는 terminal Task 인지를 정리한다.
- 손실된 응답이나 불확실한 부작용을 이유로 코드를 자동 replay/retry하지 않는다. 알 수 없는 결과는 증거로 복구하거나 `lost`로 처리한다.
- `run_command`는 부모 Execution의 예산·취소 경계 안에서 실행한다. 명시적으로 위임한 외부 sibling unit은 이 보장 밖이다.
- `bootstrap`과 `task`는 Monty Capability가 아니라 별도 MCP 도구다. 정확한 공개 schema는 현재 도구 선언을 따른다.

## Why

이전 foreground/detached 구분은 SQLite에 기록하기 전 코드가 시작되는 crash window, 별도 `task_id`, 파일/DB 이중 권위를 만들었다. 네트워크 오류 뒤 실행을 재발행하면 파일 쓰기 같은 부작용이 중복될 수 있다. Durability는 timeout 후 부여하는 속성이 아니라 수락 시점부터 유지되어야 한다.

## Rejected

- timeout 후 foreground를 detach하거나 `nohup`으로 자동 이관: 기록·취소 보장이 끊긴다.
- 별도 Task DB/ID, 항상 Task 발행: 하나의 실행이 둘로 보인다.
- `failed`/`lost` 자동 재시도: side effect 중복 위험.
- 모델이 서버 deadline을 선택하거나 Task lifecycle을 Monty 안에 구현: 권위 혼합.

## Ownership

실제 시간과 cleanup은 [timeouts](../timeouts.md), 상태·복구는 [CONTEXT](../CONTEXT.md) 및 [operations](../operations.md), 출력의 의미는 [ADR 0005](0005-code-mode-output-contract.md), 수동 polling 없는 인지는 [ADR 0006](0006-tracked-tasks-connector-projection.md)에서 확인한다. 미구현 독립 AGY MCP 도구는 [계획](../../../plans/runtime/2026-08-30-top-level-durable-agy-worker.md)으로만 보존한다.

2026-08~09의 명칭 전환(이전 ADR 0009)과 대체 실행 방식의 증거는 Git 이력에 보존한다.
