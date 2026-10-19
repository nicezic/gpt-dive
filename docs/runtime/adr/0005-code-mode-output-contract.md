---
title: ADR 0005 — Monty Data and MCP Output Boundary
created: 2026-08-29
updated: 2026-10-20
type: decision
status: accepted
---

# ADR 0005 — Monty Data and MCP Output Boundary

## Decision

**Monty 내부의 Capability 결과는 AI에게 자동 출력하지 않고, 중간 데이터로 온전하게 보존한다. 크기 제한은 최종 MCP 응답 경계에만 적용한다.** Code Mode는 큰 파일·로그를 내부에서 비교/축약하고 마지막 JSON-safe 표현식만 반환하는 programmable reduction boundary다.

~~~text
Capability 결과(내부 데이터, 자동 절단 금지)
   → Monty 분석·선별·조합
   → 마지막 expression = result
   → MCP 최종 응답: 출력 상한과 불완전성 안내
   → ChatGPT context
~~~

- `status=completed`는 실행 완료이지 **응답이 전부 전달됐다는 보장**이 아니다. 출력이 잘리면 별도 표시와 다음 조회 지침이 있어야 한다.
- 현재 구현의 상한·`output_truncated`·`output_guidance`는 `src/gpt_dive/mcp_models.py`와 [Runtime CONTEXT](../CONTEXT.md)가 소유한다. ADR은 상한 숫자를 고정하지 않는다.
- 잘린 미리보기에는 시작·중간 생략·끝 경고를 넣어 사람이든 AI든 불완전성을 쉽게 식별하게 한다. 구체 경고 문구와 Head/Tail 비율은 현행 코드가 소유한다.
- 큰 구조화된 최종 결과는 전송용 preview로 바뀔 수 있다. 잘린 응답을 완전한 원문/JSON이나 덮어쓰기 입력으로 사용해서는 안 된다.
- `task(get)`도 같은 최종 전송 제한을 받는다. 이를 반복 호출하는 것은 축약·복구 수단이 아니다.
- 결과의 원문 구간은 기존 Execution 보존 파일을 읽는 Code Mode `read_execution_result` Capability로 조회하며, `next_offset`을 사용한다. 별도의 MCP Tool·Task·DB는 만들지 않는다.
- `print()`는 최종 결과 전달 수단이 아니다. 현행 Code Mode는 print 출력을 AI 결과로 전달하지 않는다.
- `run_command`의 stdout/stderr와 최종 Monty `result`는 서로 다른 데이터다. 실행 요약·증거의 소유권은 [ADR 0008](0008-raw-execution-evidence-recovery.md)에서 구분한다.
- 출력 필드의 어휘는 `status`, `result`, `error`로 일관되게 사용한다. `tracked_tasks`는 result 안이 아닌 별도 인지 필드다.

## Why

과거 구현에서 capability 결과와 print, 최종 값을 중복 중계해 컨텍스트를 낭비하고 필드 오판을 유발했다. 2026-10 파일 손상 사례에서는 중간 `read_file` 데이터가 AI 출력 제한보다 먼저 잘려 파일 전체로 오인됐다. AI를 위한 출력 상한을 내부 데이터의 완전성과 혼동하면 안 된다.

## Rejected

- 모든 Capability 반환값을 Web 컨텍스트 크기에 맞게 자르기: Monty 내부 계산과 파일 무결성 침해.
- 모든 stdout 또는 print를 최종 `result`에 재주입: 중복 출력과 의미 혼란.
- 별도 transcript·spill 프레임워크를 선제 도입: 관찰된 필요보다 복잡하다.
- Task 상태와 프로그램 결과를 한 객체로 합치기: 실행 수명과 전송 의미 혼합.

## Ownership

[ADR 0011](0011-read-file-raw-default-and-monty-alignment.md)은 파일 원문 읽기, [ADR 0004](0004-always-durable-code-mode-runtime.md)는 실행 수명, [architecture](../architecture.md)는 현재 구현 경계를 소유한다. 옛 print/console 명칭과 출력 설계 변경 근거는 Git 이력에 있다.
