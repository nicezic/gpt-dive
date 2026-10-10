---
title: ADR 0006 — Automatic TrackedTasks Projection
created: 2026-08-30
updated: 2026-10-11
type: decision
status: accepted
---

# ADR 0006 — Passive TrackedTasks Awareness

**Decision:** AI가 `task(list)` polling을 기억하지 않아도, 일반 GPT Dive 도구 호출 중 미처리 Task를 발견하도록 Runtime-owned `TrackedTasks`를 ordinary tool result의 부가 metadata로 공개한다. 수명/identity는 ADR 0004, 출력 결과 의미는 ADR 0005가 소유한다.

~~~text
start background Execution → Task published
   │
   └─ SOL continues other work
        └─ later @dive/@c result carries TrackedTasks
             └─ inspect task(get) only when useful
                  └─ explicit task(dismiss) after handling
~~~

## Why

초기 구현은 MCP `CallToolResult.content[]`에 TrackedTasks 텍스트를 붙였다. 서버에서는 확인됐지만 2026-08-31 ChatGPT connector 실측에서는 model-visible 결과에 보이지 않았다. **Carrier 문제이지 opportunistic awareness 자체의 실패가 아니었다.** 그래서 결과를 실질적으로 모델에 노출하는 structured carrier로 옮겼다.

## Invariants

- Primary tool result는 그대로 유지한다. `tracked_tasks`는 출력의 **형제 필드**이지 중첩된 result나 원래 `output` 일부가 아니다.
- SQLite Task publication이 유일한 awareness authority다. Conduit는 새 Task ID/DB를 만들지 않는다.
- Snapshot은 compact하게 만들어 실행 label, identifier, lifecycle, elapsed 등 실제 선택에 필요한 정보만 실어야 한다. 구체 필드는 현재 Pydantic schema가 소유한다.
- **YAGNI:** Task는 드물게 발생한다. 대량 발생을 가정한 개수 제한·복잡한 관리 로직은 만들지 않는다. 실제 필요 없는 방어 설계가 코드와 버그만 늘렸다.
- Task가 없을 때 `tracked_tasks`를 항상 빈 배열로 전송하라는 초기 제안은 **현재 구현에서 대체**됐다. 선택 필드는 비어 있으면 생략될 수 있다.
- `task(list)`는 상세 조회 도구로 남지만, AI가 완료를 알기 위해 주기적으로 호출해야 하는 계약이 아니다.
- MCP transport 자체가 응답을 잃으면 awareness delivery를 보장하지 못한다. 기존 Execution은 별개로 살아 있을 수 있다.
- 완료 후 `task(get)`은 비파괴 조회, `task(dismiss)`만 awareness를 제거한다.

**Rejected:** 별도 TrackedTasks queue, polling 의무화, 항상 모든 중간 도구 출력을 로그로 첨부, 자동 result 삭제, 다른 Execution identity 생성.

## Evidence / reference

- [Conduit ADR 0002](../../conduit/adr/0002-trackedtasks-refresh-and-opportunistic-evidence-pickup.md) — 원래 OEP 동기.
- [Runtime architecture](../architecture.md) — 현재 실행·Task projection 동작.
- `src/gpt_dive/app.py` — 정확한 `tracked_tasks` 출력 schema/조건.

이 ADR의 초기 구현안과 `content[]` canary 분석은 Git 이력에 남아 있으며, 현재 transport schema보다 우선하지 않는다.
