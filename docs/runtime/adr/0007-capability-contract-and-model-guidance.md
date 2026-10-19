---
title: ADR 0007 — Capability Contract and Minimal Model Guidance
created: 2026-08-30
updated: 2026-10-20
type: decision
status: accepted
---

# ADR 0007 — Capability Contract and Minimal Model Guidance

## Decision

**모델이 첫 `code_mode` 호출을 작성하기 전에, 등록된 Capability의 실제 이름·인자·반환 필드가 보이게 한다.** 하나의 등록 정의에서 공개 generated declaration, Monty 타입 검사 및 호스트 검증을 파생한다.

~~~text
Capability definition (single authority)
  ├─ MCP code_mode description: generated declarations (첫 호출 전)
  ├─ Monty type-check stubs
  ├─ runtime argument/result validation
  └─ CAPABILITIES reflection (실행 중 확인/보조)
~~~

Wiki `bootstrap`에는 안전·승인·워크플로의 짧은 원칙만 둔다. Pydantic/Monty의 지원 문법이나 시그니처를 Wiki에 수동 복제하지 않는다. 실제 public schema와 generated declarations가 오래된 가이드보다 우선한다.

- `code`는 Monty orchestration, `PAYLOAD`는 여러 줄·opaque 문자열, `CWD`는 경로 기준이다.
- 독립 호출만 `asyncio.gather`; 중간 Capability 값은 [ADR 0005](0005-code-mode-output-contract.md)대로 지역 변수에 유지한다.
- 오류는 `error.code/detail/guidance`와 실제 실행/부작용 증거에 근거해 처리한다. 불확실한 작업을 곧바로 재실행하지 않는다.
- 정확한 tool 이름·return type은 type declaration에서 확인하며 Python SDK 기억으로 추측하지 않는다.
- `CAPABILITIES`는 첫 호출 이전의 권위가 아니라 런타임 reflection/fallback이다.

## Why

과거에는 첫 코드 작성 전에 Capability를 몰라 오타·추정 필드를 실행하고, 다음 호출에서 `CAPABILITIES`로 발견해야 했다. 방대한 Monty 규칙을 미리 로딩하면 컨텍스트 낭비와 stale 정보가 증가했다. Codex의 사전 선언 순서는 채택하되, V8과 cell lifecycle까지 복사할 이유는 없다.

## Rejected

- 서로 다른 수동 함수 선언·타입 표·Wiki 목록 유지: 시간이 지나면 계약이 갈라진다.
- 모델이 런타임 탐색을 해야만 첫 호출 성공 가능: 불필요한 발견 호출.
- 대형 CPython 호환 룰북이나 speculative fallback: 이미 노출된 정확한 선언보다 신뢰도가 낮다.
- Codex JavaScript 실행기·deferred loading까지 이식: 현재 Monty 실행 모델과 무관하다.

## Ownership

구현: `src/gpt_dive/code_capabilities.py`, `code_runtime.py`, `app.py`. 실제 AI 사용 안내: `~/wiki/workflow/code-mode.md`. Codex 조사 근거는 이전 Runtime ADR 0010의 Git 이력에 보존한다. 기존 ADR 0010(typed declaration)과 0007(최소 안내)은 이 결정으로 통합했다.
