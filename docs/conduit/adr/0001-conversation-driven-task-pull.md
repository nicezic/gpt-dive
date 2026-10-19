---
title: ADR 0001 — Conversation-Driven Task Awareness
created: 2026-08-16
updated: 2026-10-20
type: decision
status: accepted
---

# ADR 0001 — Conversation-Driven Task Awareness

## Decision

ChatGPT Web의 사용자 대화와 일반 도구 호출을 **Task 상태를 다시 보는 자연스러운 기회**로 사용한다. 별도 서버 push나 매번 명시적인 polling 호출을 필수로 만들지 않는다. 이 결정은 옛 Conduit ADR 0001의 conversation-driven pull과 ADR 0002의 cross-surface TrackedTasks/OEP를 통합한다.

~~~text
Task를 가진 Execution 시작 → SOL은 다른 일 진행
    → 후속 정상 도구 호출에 compact TrackedTasks snapshot
    → 필요할 때 기존 execution_id로 결과 조회
    → 활용하거나 terminal 상태에서 dismiss
~~~

- Task/Execution 상태와 ID는 **GPT Dive Runtime의 SQLite**가 소유한다([Runtime ADR 0004](../../runtime/adr/0004-always-durable-code-mode-runtime.md)).
- Conduit는 대화 프로토콜·이벤트 전달과 화면을 소유한다. 별도 `TaskStore`, `task_id`, duplicate execution authority를 만들지 않는다.
- 완료 결과 조회는 비파괴적이며, 의도한 정리만 `dismiss`한다.
- Passive awareness의 실제 carrier, 제공되는 MCP 도구, 필드 생략 규칙은 [Runtime ADR 0006](../../runtime/adr/0006-tracked-tasks-connector-projection.md)과 현재 schema가 소유한다.
- 외부 worker가 달라도 결합은 **상태·결과 경계**에서만 한다. 새로운 공통 worker 실행기나 자동 background 전환을 만들지 않는다.
- Opportunistic Evidence Pickup(OEP)은 알림을 받은 AI가 근거를 필요할 때 검토·중복 제거·활용한다는 운영 원칙이지 자동 내용 수집을 보장하는 새 서비스가 아니다.

## Why

2026-08-16 실험에서는 같은 대화에서 `@c`를 두 번 호출하는 방식으로 독립 실행의 완료를 발견했고, 비파괴적 결과 재조회가 가능함을 관찰했다. 다음 설계에서는 평범한 `@dive` 호출에도 상태를 보여 주려 했으나, 일부 MCP `content[]` 주입은 ChatGPT 측에서 보이지 않았다. 실제 모델에 보이는 경로로 투영해야 한다.

## Rejected

- 서버 push/특별한 주기적 poll을 기본 계약으로 강제.
- Conduit 전용 durable 작업 DB·ACK/collect 수명주기·두 번째 Task ID.
- 이 원칙 하나로 이질적인 worker를 전부 통합하는 실행 프레임워크.
- Task 수가 많을 것이라는 가정만으로 queue·cap·dedupe 체계를 선제 도입.

## Ownership

현재 Conduit 구현: [CONTINUATION](../CONTINUATION.md), [Context](../CONTEXT.md). 과거 canary의 `collect/ack` 용어는 더 이상 현재 공개 계약이 아니다. 당시 관찰과 보다 넓은 OEP 제안은 이전 ADR 0001/0002의 Git 이력에 보존한다.
