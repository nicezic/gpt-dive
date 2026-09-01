# Run Command Model-facing Summary

## Problem Statement

ADR 0008 Section 5의 model-facing 실행 요약을 구현한다. `run_command`의 raw stdout/stderr는 기본 model context에 다시 펼치지 않고, 각 run의 최소 실행 메타와 필요한 stderr만 보여준 뒤 기존 Monty final `output`을 전달해야 한다.

ADR 0005의 public output contract는 유지한다. `kind + execution_id + output`과 `tracked_tasks` structured schema를 바꾸지 않는다.

## Solution

```text
run_command terminal
├─ 기존 bounded raw evidence
├─ exit_code
└─ duration_ms
      │
      ▼
run_command_evidence (SQLite)
      │
      ▼
MCP model-visible text content
id: <execution_id>

[0] <exit_code>, <duration> ms, <stdout+stderr size>
[1] <exit_code>, <duration> ms, <size>, stderr ↓
<bounded stderr preview>

----
<processed Monty output>

structured_content
└─ 기존 kind / execution_id / output / tracked_tasks 그대로
```

## Implementation Decisions

### 1. Evidence metadata

- 기존 `run_command_evidence` row에 `exit_code`, `duration_ms`를 함께 저장한다.
- 새 table이나 별도 summary store는 만들지 않는다.
- `captured size`는 bounded raw stdout + stderr byte 수의 합이다.
- 기존 stdout/stderr 8 MiB-per-stream bound와 overflow 정보는 유지한다.

### 2. Model-visible text

- completed `code_mode`와 completed `task(get)`의 MCP text content에 같은 요약을 사용한다.
- 첫 줄은 `id: <execution_id>`만 둔다.
- 각 run은 `[index] exit_code, duration ms, size` 순서다.
- `stderr`가 비어 있지 않을 때만 `stderr ↓`와 bounded preview를 표시한다.
- stdout raw/preview는 요약 영역에 표시하지 않는다.
- run이 없으면 run summary block을 만들지 않고 기존 output presentation을 유지한다.

### 3. Structured contract preservation

- `CodeModeCompleted` / `CodeModeTask` / `CodeModeError` schema는 변경하지 않는다.
- Monty final `output` 값은 그대로 유지한다.
- `tracked_tasks` semantics도 변경하지 않는다.
- debug text presentation은 MCP `content`에만 적용한다.

### 4. Failure semantics

- run evidence 저장 실패가 원래 command 결과를 바꾸지 않는 ADR 0008 규칙은 유지한다.
- summary metadata가 없거나 조회되지 않으면 completed outcome 자체를 실패시키지 않는다.
- 새 retry/fallback store는 만들지 않는다.

## Testing Decisions

1. evidence row가 `exit_code`, `duration_ms`, raw stream을 함께 보존한다.
2. captured size가 stdout + stderr bounded byte 수와 일치한다.
3. 다중 run은 ordinal 순서대로 `[0]`, `[1]`, ... 로 렌더링된다.
4. stderr가 있을 때만 `stderr ↓`와 bounded preview가 나온다.
5. stdout 내용은 debug summary에 복제되지 않는다.
6. processed Monty output이 `----` 아래에 표시된다.
7. completed `code_mode`와 completed `task(get)`이 같은 presentation을 사용한다.
8. `structured_content`의 기존 shape와 typed `output`은 변하지 않는다.
9. no-run completed execution은 불필요한 empty run header를 만들지 않는다.
10. evidence persistence 실패는 기존 `run_command` outcome을 바꾸지 않는다.

## Acceptance

- focused tests 통과
- full pytest 통과
- Ruff 통과
- Pyright 통과
- `git diff --check` 통과
- staged diff 직접 review 후 actionable finding 0건

## Out of Scope

- MCP structured schema 변경
- raw stdout 기본 노출
- recovery capability 이름/schema 결정
- 새 evidence table/store
- arbitrary capability execution summary
