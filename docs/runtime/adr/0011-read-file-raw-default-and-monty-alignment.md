---
title: ADR 0011 — Read File Raw Text Default & Monty Wire Alignment
created: 2026-09-06
updated: 2026-09-06
type: decision
status: accepted
---

# ADR 0011 — Read File Raw Text Default & Monty Wire Alignment

## Goal

Code Mode 안에서 `read_file`의 반환값을 `json.loads` 파싱이나 `edit_file`의 `old_text` 등 후속 파이프라인에 즉시 전달할 수 있도록 데이터 불일치(Impedance Mismatch)를 제거하고, multiline exception 시 발생하던 upstream Monty wire protocol 직렬화 버그(#631)를 해결하여 안정적인 에러 피드백을 보장한다.

```text
[과거: 연쇄 실패 및 에러 마스킹]
read_file(줄번호+헤더 강제) ──> edit_file(old_text 매칭 실패: ValueError) ──> Monty Wire Crash (Issue #631)
                                                                                  │
                                에이전트가 원인을 모른 채 read_file 기피 & cat 도피 ◄─────┘

[현재: 원자적 raw 텍스트 & 안정적 예외 전파]
read_file(raw 텍스트 기본값) ──> edit_file / json.loads 즉시 호환
                                └─ 만약 예외 발생 시 ──> Monty 0.0.23+ 정상 Traceback 반환
```

## Context & Problem

### 1. Chat Prompt Tool vs Code Mode의 Impedance Mismatch
* **문제**: Harness의 기존 `read_file`은 대화형 LLM에게 줄번호를 보여주기 위해 만들어진 뷰어였다 (`[path | lines | hash]` 헤더 및 각 줄 앞에 `\t1:` 접두사 추가).
* **결과**: Python 코드 안에서 `read_file`을 호출할 때:
  1. `json.loads(await read_file("config.json"))` 실행 시 `JSONDecodeError` 발생.
  2. `content = await read_file(...)`로 읽은 텍스트를 `edit_file(target, old_text=content, new_text=...)`로 넘기면 줄번호 접두사 때문에 원문 불일치(`ValueError: old_text not found`) 발생.

### 2. Upstream Monty Wire Protocol Crash (Issue #631)
* **문제**: `edit_file` 등 multiline 함수 호출에서 `ValueError` 예외가 발생할 때, `pydantic-monty <= 0.0.21`은 예외 AST span 계산 시 `StackFrame.end.column < start.column`이 되어 Pydantic 유효성 검증 실패로 런타임 프로세스 자체가 크래시됨.
* **증상**: 에이전트는 `old_text not found`라는 진짜 원인을 보지 못하고 `RuntimeError: Monty runner failed`만 수신.
* **오판 유도**: 에이전트는 `read_file` 또는 Monty 자체가 불안정하다고 판단하여 `run_command("cat ...")`으로 우회하는 악순환 발생.

---

## Decision

### 1. `read_file` 기본값을 Raw Text로 전환
[`code_capabilities.py`](file:///home/nicezic/gpt-dive/src/gpt_dive/code_capabilities.py)의 `read_file` 인터페이스를 개편하여 기본적으로 순수 파일 원문을 반환한다.

```text
read_file(path, offset=1, limit=None, line_numbers=False, raw=None)
├─ line_numbers=False (기본값) ──→ 순수 파일 원문 반환 (offset/limit line slicing 지원)
└─ line_numbers=True (또는 raw=False) ──→ 헤더 및 줄번호 포맷팅 반환 (사람/프롬프트 점검용)
```

- `offset`과 `limit`은 raw 모드에서도 1-indexed 라인 슬라이싱으로 정확히 작동한다.
- 하위 호환성을 위해 `raw: bool | None` 인자도 지원하되, `line_numbers: bool`을 권위 있는 canonical 매개변수로 삼는다.

### 2. Upstream 패키지 최신화
- `pydantic-monty >= 0.0.23`: multiline exception의 column span 직렬화 버그(#631) 수정본 반영.
- `pydantic-ai-harness >= 0.29.0`, `mcp >= 2.1.1`: 최신 도구 체인 및 예외 체이닝(`UnexpectedToolError.__cause__`) 정합성 확보.

### 3. SQLite 중심의 에러 감사(Audit) 체제 확립
- 에러 케이스를 매 턴마다 마크다운 파일(`ERROR_CASE.md`)에 수기 기록하던 방식을 폐지.
- SQLite SSOT(`~/.local/state/gpt-dive/runtime.sqlite3`의 `executions` 테이블)를 단일 진실 공급원으로 삼고, 주기적 감사 쿼리를 통해 체계적으로 트러블슈팅을 수행한다.

---

## Consequences

1. **기계 소비 정합성 확보**:
   - `json.loads(await read_file(...))` 및 AST/정규식 파싱이 별도 strip 없이 100% 작동.
   - `read_file` $\rightarrow$ `edit_file` 앵커 전달 파이프라인의 원문 일치 보장.
2. **토큰 소모 최적화**:
   - 줄번호 및 메타데이터 헤더 오버헤드가 제거되어 파일 읽기 토큰 소모량이 약 20% 절감됨.
3. **안정적인 장애 격리**:
   - multiline 예외 발생 시에도 Monty가 크래시되지 않고 정확한 파이썬 Traceback(`ValueError: old_text not found ...`)을 모델에게 반환하여 자가 교정(self-healing)이 가능해짐.
4. **선택적 줄번호 검토 유지**:
   - 모델이 코드 위치 파악을 위해 줄번호가 명시적으로 필요한 경우 `line_numbers=True` 옵션으로 언제든 포맷팅 뷰를 호출 가능.

---

## References

- [`src/gpt_dive/code_capabilities.py`](file:///home/nicezic/gpt-dive/src/gpt_dive/code_capabilities.py#L89-L115)
  - `read_file` raw 텍스트 기본 구현 및 `line_numbers` 처리 로직.
- [`tests/test_code_runtime.py`](file:///home/nicezic/gpt-dive/tests/test_code_runtime.py#L308-L325)
  - raw 기본값, `line_numbers=True`, offset/limit 슬라이싱 단위 테스트.
- [Upstream Issue `pydantic/monty#631`](https://github.com/pydantic/monty/issues/631)
  - Wire protocol `StackFrame.end.column` 직렬화 검증 실패 및 픽스.
