---
title: ADR - Raw Execution Evidence Recovery
created: 2026-08-30
updated: 2026-09-01
type: decision
status: proposed
---

# ADR 0008 — Raw Execution Evidence Recovery

## Why

Normal `run_command` 결과는 model context에 맞게 compact하게 전달한다. 이후 더 자세한 조사가 필요할 때는 command를 다시 실행하거나 raw output 전체를 model context에 넣지 않고, 이미 수집한 bounded stdout/stderr를 다시 확인할 수 있어야 한다.

## Decision

```text
run_command #N
    │
    ├─ stdout ≤ 8 MiB
    └─ stderr ≤ 8 MiB
         │
         ▼
      /tmp evidence
         │
      terminal
         │
         ├─ /tmp 유지
         └─ SQLite 저장 시도
                └─ 실패해도 run_command 결과 유지

recovery
    │
    ├─ /tmp 있음 → 사용
    └─ /tmp 없음 → SQLite 확인
                     ├─ 있음 → 같은 /tmp 위치로 복원
                     └─ 없음 → recovery 불가

GC
    └─ Execution 생성 48시간 후 /tmp evidence 삭제
       + 5일 지난 SQLite raw evidence 삭제
```

### 1. Raw evidence는 run 단위로 bounded한다

각 `run_command`의 stdout/stderr를 각각 최대 8 MiB까지 보존하고, 한 Execution 안에서는 실행 순서대로 `run_ordinal = 1, 2, 3, ...`으로 식별한다.

### 2. `/tmp` evidence는 terminal 뒤에도 유지한다

Runtime이 소유하는 private canonical path를 active spool과 recovery가 함께 사용한다.

```text
/tmp/gpt-dive-run-command/
└─ <execution_id>/                  directory 0700
   └─ <run_ordinal>/                directory 0700
      ├─ stdout                     file 0600
      └─ stderr                     file 0600
```

이 path는 Runtime 내부 working path이며 model-facing protocol로 노출하거나 GPT가 직접 조립하지 않는다. `run_command` terminal 뒤에도 유지하고, 같은 bounded evidence를 SQLite에 저장 시도한다. SQLite 저장 실패는 원래 `run_command` 결과를 storage failure로 바꾸지 않는다.

### 3. Recovery는 `/tmp`를 먼저 사용한다

`/tmp`가 없을 때만 SQLite를 확인하고, 있으면 같은 `/tmp` 위치로 복원한다. 양쪽 모두 없으면 recovery할 수 없으며 command 재실행, retry store, second database로 보완하지 않는다.

### 4. Raw evidence는 기존 cleanup으로 GC한다

- `/tmp`: Execution `accepted_at` 48시간 후 삭제
- SQLite raw evidence: 5일 후 삭제
- 5일은 recovery 보장 기간이 아니라 durable 저장 공간 증가를 막기 위한 GC 기준이다.
- 별도 GC 시스템을 만들지 않는다. 기존 `ExecutionManager.cleanup()`이 Runtime 시작 시와 이후 새 Execution 시작 시 하루에 최대 한 번 수행한다.

### 5. Model-facing output은 실행 메타와 가공 결과를 분리한다

Raw stdout은 기본 model-facing output에 다시 펼치지 않는다. 각 `run_command`의 실행 메타를 compact하게 표시하고, 그 아래에는 Monty가 만든 가공 결과를 전달한다.

```text
id: X8M_Yw

[0] 0, 2310 ms, 1.8 KiB
[1] 2, 410 ms, 620 B, stderr ↓
"..."
[2] 0, 95 ms, 24 B

----
<processed output>
```

각 행은 `[index] exit_code, duration, captured size` 순서다. `captured size`는 해당 run의 bounded stdout + stderr 총 byte 수다. `[index]`는 같은 Execution 안의 `run_command` 순서이며 `asyncio.gather()` 결과도 호출 순서대로 대응한다. `stderr`는 값이 있을 때만 표시한다. Raw stdout/stderr 전체가 필요하면 recovery 경로를 사용한다.

## Scope

이 ADR은 `run_command` stdout/stderr raw evidence의 저장, recovery, GC와 model-facing 실행 요약 형식을 다룬다.

```text
included
├─ run_command stdout/stderr raw evidence
└─ compact run metadata + processed output boundary

out of scope
├─ arbitrary capability results
├─ arbitrary Monty variables
├─ complete Execution transcript
└─ final model-facing recovery capability name/schema
```
