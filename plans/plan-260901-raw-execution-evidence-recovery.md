# Raw Execution Evidence Recovery

## Problem Statement

ADR 0008에서 정한 raw evidence lifecycle을 구현해야 한다. 핵심은 기존 bounded `run_command` evidence를 terminal 뒤에도 사용할 수 있게 하고, recovery를 `/tmp` 우선으로 만들며, 오래된 SQLite evidence는 recovery 로직과 섞지 않고 기존 GC에서 정리하는 것이다.

## Solution

구현은 세 seam만 변경한다.

```text
run_command terminal
└─ /tmp 유지 + SQLite 저장 시도

recovery
└─ /tmp 먼저 → 없으면 SQLite 복원

cleanup
└─ Execution 생성 48시간 후 /tmp + 5일 지난 SQLite evidence 삭제
```

기존 8 MiB-per-stream bound와 execution-local `run_ordinal`은 유지한다. Final model-facing recovery API는 만들지 않는다.

## Implementation Decisions

### 1. Terminal 처리

- stdout/stderr bounded spool은 terminal 뒤에도 남긴다.
- Terminal run의 bounded stdout/stderr를 SQLite에 저장 시도한다.
- 저장 실패는 기존 `run_command` 성공/실패/timeout/cancellation 의미를 바꾸지 않는다.
- 성공, non-zero exit, timeout, cancellation 모두 terminal 시점까지 확보된 evidence를 같은 방식으로 처리한다.

### 2. Recovery

- 기존 `/tmp` evidence 존재 여부를 먼저 확인한다.
- 있으면 SQLite 조회 없이 그대로 사용한다.
- 없으면 SQLite evidence를 확인하고, 있으면 `/tmp/gpt-dive-run-command/<execution_id>/<run_ordinal>/<stream>`으로 복원한다.
- 양쪽 모두 없으면 unavailable로 끝낸다. Replay나 추가 recovery store는 만들지 않는다.

### 3. GC

- 기존 `ExecutionManager.cleanup()`을 확장해 5일이 지난 SQLite raw evidence를 정리한다.
- Execution `accepted_at`으로부터 48시간이 지난 `/tmp` raw evidence를 같은 cleanup에서 정리한다.
- Recovery 호출 중 age check나 삭제를 수행하지 않는다.
- 별도 evidence cleanup service나 별도 TTL protocol을 만들지 않는다.

### 4. 기존 경계 유지

- stdout/stderr는 각각 최대 8 MiB를 유지한다.
- 한 Execution의 여러 command는 execution-local `run_ordinal`로 구분한다.
- 이전 구현의 SQLite `run_command_next_ordinal`과 구형 evidence table schema는 제거한다.
- `/tmp/gpt-dive-run-command/<execution_id>/<run_ordinal>/`을 active spool과 recovery가 함께 사용한다.
- Runtime-owned directory는 `0700`, stdout/stderr file은 `0600` private permission을 유지한다.
- Normal model-facing `run_command` output은 계속 compact하게 유지한다.
- Private working path를 public recovery contract로 노출하지 않는다.
- Final model-facing recovery capability 이름과 schema는 이 plan에서 정하지 않는다.


## Testing Decisions

### Test contract

외부에서 의미 있는 Runtime 동작을 기존 seam에서 검증한다.

1. Terminal 뒤에도 bounded stdout/stderr evidence가 recovery에 사용 가능하다.
2. Terminal evidence가 SQLite 저장 경로로 전달된다.
3. SQLite 저장 실패가 원래 `run_command` 결과를 바꾸지 않는다.
4. `/tmp` evidence가 있으면 SQLite evidence 없이도 recovery된다.
5. `/tmp`가 없고 SQLite evidence가 있으면 같은 working location으로 복원된다.
6. 양쪽 모두 없으면 unavailable이며 command replay가 발생하지 않는다.
7. 여러 `run_command`의 run ordinal이 중복 없이 증가한다.
8. stdout/stderr가 각각 8 MiB bound를 유지한다.
9. success, non-zero exit, timeout, cancellation에서 terminal 전까지 확보된 evidence가 유지된다.
10. 5일 GC가 SQLite raw evidence를, Execution 생성 48시간 후 GC가 `/tmp` working evidence를 정리하고 recovery 경로는 age 기반 삭제를 하지 않는다.
11. `/tmp` working layout이 Runtime-owned private 상태를 유지한다: directory `0700`, stdout/stderr file `0600`, model-facing path 미노출.
12. 이전 구현의 DB ordinal 컬럼과 구형 evidence table schema가 제거된다.
13. Normal model-facing output의 compact semantics가 바뀌지 않는다.

### Preferred seams

- `run_command` Runtime seam: spool, terminal persistence, timeout/cancellation, bound, run ordering.
- Recovery/materialization seam: `/tmp` 우선과 SQLite 복원.
- Existing cleanup seam: 5일 SQLite raw-evidence GC와 48시간 creation-based `/tmp` GC.
- Store-level test는 위 seam에서 검증하기 어려운 persistence semantics에만 사용한다.

### Acceptance

```text
run_command
├─ bounded evidence 유지
├─ terminal SQLite 저장 시도
└─ 저장 실패가 command result를 덮지 않음

recovery
├─ /tmp first
├─ SQLite only if /tmp missing
└─ no replay / no extra store

GC
└─ 5일 지난 SQLite + 48시간 지난 `/tmp` raw evidence 정리
```

Focused tests와 관련 Runtime suite가 통과하고, owned diff에 whitespace 오류가 없어야 한다.

## Out of Scope

- Final model-facing recovery capability 이름/schema.
- Raw-output dump tool.
- Private working path의 public 노출.
- 다른 capability output이나 complete Execution transcript 저장.
- 8 MiB-per-stream bound 증가.
- Second evidence database, retry persistence, command replay.
- 별도 evidence GC service 또는 별도 TTL protocol.
- 5일을 recovery guarantee나 durability SLA로 해석하는 것.
