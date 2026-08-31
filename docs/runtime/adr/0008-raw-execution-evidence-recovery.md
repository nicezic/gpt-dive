---
title: ADR - Raw Execution Evidence Recovery
created: 2026-08-30
updated: 2026-09-01
type: decision
status: proposed
---

# ADR 0008 — Raw Execution Evidence Recovery

## Why

Normal `run_command` 결과는 model context에 맞게 compact하게 전달한다. 하지만 이후 더 자세한 조사가 필요할 때는 command를 다시 실행하거나 raw output 전체를 model context에 넣지 않고, 이미 수집한 bounded stdout/stderr를 다시 확인할 수 있어야 한다.

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

각 `run_command`의 stdout/stderr는 각각 최대 8 MiB까지 보존한다.

한 Execution 안의 여러 `run_command`는 실행 순서대로 `run_ordinal = 1, 2, 3, ...`으로 식별한다.

### 2. `/tmp` evidence는 terminal 뒤에도 유지한다

실행 중 raw evidence는 Runtime이 소유하는 private canonical path에 둔다.

```text
/tmp/gpt-dive-run-command/
└─ <execution_id>/                  directory 0700
   └─ <run_ordinal>/                directory 0700
      ├─ stdout                     file 0600
      └─ stderr                     file 0600
```

이 layout은 active spool과 recovery가 함께 사용한다. Runtime 내부 working path이며 model-facing protocol로 노출하거나 GPT가 직접 조립하게 하지 않는다.

`run_command`가 끝났다는 이유로 이 evidence를 즉시 삭제하지 않는다.

Terminal 시점에는 같은 bounded evidence를 SQLite에도 저장 시도한다. SQLite 저장 실패는 원래 `run_command` 결과를 storage failure로 바꾸지 않는다.

### 3. Recovery는 `/tmp`를 먼저 사용한다

`/tmp` evidence가 있으면 그대로 사용한다. 없을 때만 SQLite를 확인하고, evidence가 있으면 같은 `/tmp` 위치로 복원한다.

`/tmp`와 SQLite 양쪽에 evidence가 없으면 recovery할 수 없다. Command를 다시 실행하거나 별도 retry store, second database로 보완하지 않는다.

### 4. SQLite raw evidence는 5일 후 GC한다

5일은 SQLite recovery 보장 기간이 아니라 durable 저장 공간 증가를 막기 위한 GC 기준이다.

별도 GC 시스템을 만들지 않는다. 기존 `ExecutionManager.cleanup()`은 Execution `accepted_at`으로부터 48시간이 지나면 해당 `/tmp` working evidence를 삭제하고, 기존 retention 기준에 따라 SQLite raw evidence를 정리한다. Cleanup은 Runtime 시작 시와 이후 새 Execution 시작 시 하루에 최대 한 번 수행한다.

## Scope

이 ADR은 `run_command` stdout/stderr raw evidence의 저장, recovery, SQLite GC만 다룬다.

```text
included
└─ run_command stdout/stderr

out of scope
├─ arbitrary capability results
├─ arbitrary Monty variables
├─ complete Execution transcript
└─ final model-facing recovery capability name/schema
```
