---
title: ADR 0007 — Code Mode Bootstrap and Model Guidance
created: 2026-08-30
updated: 2026-10-10
type: decision
status: accepted
---

# ADR 0007 — Minimal Model Guidance

**Decision:** AI에게 필요한 실행 규칙은 **짧게**, 실제 함수/인자/반환 계약은 **live generated capability declaration**에서 가져온다. Monty 지원 기능은 업스트림 버전에 따라 변하므로 오래된 제약 목록을 bootstrapping의 권위로 삼지 않는다.

~~~text
MCP code_mode schema + generated declarations  → outer/inner tool contract
Wiki preload                                    → 안전·워크플로우 최소 규칙
Monty type_check                                → 실제 코드 검증
Execution error.detail                          → 실패 증거와 수정 근거
~~~

## Why

AI가 Python/SDK 기억으로 tool arguments를 지어내면 런타임 불일치와 재시도가 발생한다. 동시에 긴 Handbook을 매 요청 읽히면 context만 소모하고 stale 규칙이 남는다. **하나의 등록 함수에서 schema·docstring·Monty type stubs를 생성**해야 타입 검사와 모델의 선언이 어긋나지 않는다.

## Minimum contract

1. Monty는 CPython 전체가 아니며 각 Execution의 변수는 새 세션으로 시작한다.
2. `code`는 연산과 orchestration, `PAYLOAD`는 다중행·opaque 데이터용이다. `CWD`와 `CAPABILITIES`는 Runtime 제공.
3. 독립 비동기 호출만 `asyncio.gather`로 묶고 의존 호출은 await 후 다음 호출한다.
4. capability return은 중간 데이터; 마지막 expression만 정상 결과로 반환하며 `print`는 별도 관찰/진행을 위한 것이다.
5. Task lifecycle은 `task` MCP tool에서 관리하며 Monty 내부에 또 만들지 않는다.
6. 실패하면 `error.code/message/detail` 및 live declarations를 먼저 살펴보고 이미 발생한 side effect를 확인한다.

## Ownership

- `src/gpt_dive/code_capabilities.py` — 등록된 Capability와 설명.
- `src/gpt_dive/code_runtime.py` — Monty 실행과 같은 선언에 기반한 타입 검사.
- `src/gpt_dive/app.py` — outer MCP description/schema.
- `~/wiki/bootstrap/preload.json`과 `~/wiki/workflow/code-mode.md` — 새 AI 세션에 전송되는 작업 지침.
- [ADR 0005](0005-code-mode-output-contract.md) — 출력 의미.

**Rejected:** 중복 수동 타입 선언, 대형 Monty 룰북 자동 프리로드, Python의 모든 모듈 지원을 추정하는 안내, 실패 직후 무조건 동일 요청 재발행.
