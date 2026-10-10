---
title: ADR 0005 — Code Mode Output Contract
created: 2026-08-29
updated: 2026-10-10
type: decision
status: accepted
---

# ADR 0005 — Local Reduction and Code Mode Output

**Decision:** Code Mode는 여러 capability의 큰 결과를 **Monty 프로그램 내부에서 선별·조합한 후 작은 최종 표현식만** 호출자에게 전달하는 programmable reduction boundary다. 출력을 예쁘게 꾸미는 것보다 AI가 단순한 계약으로 정확히 후속 행동하는 것이 우선이다.

~~~text
await capability A/B/C → intermediate data stays inside Monty
                            ↓
                    filter / combine / inspect
                            ├─ optional print() → console/progress
                            └─ final expression → result

Execution/Task lifecycle → ADR 0004 (별도 계층)
TrackedTasks awareness  → Conduit ADR 0002 (별도 계층)
~~~

## Why / observed failures

과거 Code Mode는 capability 결과와 `print()` 출력, 최종 결과를 중복 전달해 model context를 부풀렸다. `result.result.result`와 불필요한 metadata는 모델의 필드 선택·분기 오류를 유발했다. 초기 TrackedTasks는 `content[]`에 주입되었지만 실제 ChatGPT connector에서는 보이지 않는 경우가 있었다. 이는 출력 계산과 Task awareness의 **서로 다른 문제**다.

## Contract

1. **Capability return:** Monty 내부 값이다. 각각을 자동으로 model-visible output에 중계하지 않는다.
2. **`asyncio.gather()`:** 독립된 비동기 호출에 사용한다. 의존 작업은 순차적으로 await한다.
3. **`print()`:** 명시적 console/progress. 최종 result에 stdout 덤프를 자동 첨부하지 않는다.
4. **Final expression:** 정상 프로그램 결과이며 string/list/dict 같은 JSON-safe 값으로 반환한다.
5. **Bounding:** 큰 intermediate value는 Monty 안에서 그대로 다룰 수 있어야 한다. Web-facing 제한이나 spill 정책은 **최종 결과 경계**에 적용하며, retained result와 preview를 혼동하지 않는다.
6. **동일 결과:** inline 완료와 나중의 `task(get)`는 동일 Execution의 result를 조회한다. Publication은 결과 의미를 바꾸지 않는다.
7. **단순 public shape:** 실제 소스 `src/gpt_dive/app.py`의 Pydantic union을 기준으로 `status = completed | running | failed`와 `execution_id`를 사용한다. 완료는 `result`, 진행 중은 `guidance`, 실패는 `error{code,message,detail,recovery}` 및 행동 지침을 담는다.
8. **Awareness:** `tracked_tasks`는 필요할 때 top-level sibling으로 추가되는 부가 정보이며 프로그램 `result` 안에 넣지 않는다. 항목이 없으면 현재 Pydantic 직렬화에서는 필드를 생략할 수 있다.
9. **Diagnostic:** 실패의 `execution_id`와 구체적 오류 증거를 보존한다. 실패 후 기존 실행의 부작용을 확인하기 전에 무조건 retry하지 않는다.
10. **SDK wrapper:** model-facing structured output에 의미 없는 중첩 래퍼를 하나 더 추가하지 않는다. 현재 실물 schema를 검증한다.

## Rejected alternatives

- 모든 capability 반환을 자동 출력: local reduction 효과 상실.
- `print()` 누적분을 final stdout에 재주입: console/result 혼동과 중복 토큰.
- 먼저 범용 ordered transcript/event subsystem 구축: 확인된 필요보다 복잡성 증가.
- 모든 capability에 Web-facing truncate/spill 강제: Monty의 중간 계산 불능.
- Task awareness와 프로그램 출력을 하나의 프로토콜로 합치기: 서로 다른 수명·권위 혼합.
- 출력에 과도한 execution metadata 및 nested `result` envelope 넣기: 모델 오류 표면 확대.

## Authority and historical note

- [ADR 0004](0004-always-durable-code-mode-runtime.md) — durable lifecycle 소유.
- [Conduit ADR 0002](../../conduit/adr/0002-trackedtasks-refresh-and-opportunistic-evidence-pickup.md) — passive Task awareness.
- [Tool output limits](../../pydantic/tool-output-limits.md) — 별도 SubAgent 정책과 미구현 final spill.
- `src/gpt_dive/app.py`와 `src/gpt_dive/code_runtime.py` — **현재** 응답 필드와 Monty 실행 구현.

이 ADR은 여러 번의 output shape 리뉴얼을 거쳤다. 과거 `kind: completed|task|error`와 `output` 필드 등의 이전 wire 계약, 2026-08-31 connector 관찰, 교정된 토론 원문은 Git 이력으로 복원 가능하지만 현재 호출 계약으로 쓰지 않는다.
