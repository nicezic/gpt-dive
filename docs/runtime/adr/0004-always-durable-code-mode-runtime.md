---
title: ADR 0004 — Always-Durable Code Mode Runtime
created: 2026-08-27
updated: 2026-10-10
type: decision
status: accepted
---

# ADR 0004 — Always-Durable Code Mode Runtime

**Decision:** 수락된 모든 Code Mode 작업은 사용자 코드를 시작하기 **전에** SQLite에 durable `Execution`으로 기록한다. MCP 응답의 성공·타임아웃·연결 종료는 그 실행의 수명을 소유하지 않는다. 정확한 현재 deadline과 운영 조건은 [timeouts](../timeouts.md)가, 상태 이름과 불변조건은 [Runtime Context](../CONTEXT.md)가 소유한다.

~~~text
code_mode(label, code, delivery=auto|task)
    ↓
SQLite Execution(accepted) → Worker spawn → accepted→running CAS
                                  │
                    ┌─────────────┴──────────────┐
                 inline result            Task publication
                    │                           │
                completed                 task(get/cancel/dismiss)
                                  모두 동일한 execution_id
~~~

## Why — 이전 구조의 실패 지점

- 기존 foreground와 detached 경로는 **다른 시점**에 내구성을 확보했다. 프로세스가 기록보다 먼저 시작하는 crash window가 있었다.
- 별도 `task_id`와 `execution_id`, 파일/SQLite의 이중 lifecycle 권위 때문에 실행과 후속 조회의 연결이 약했다.
- MCP/터널 응답이 손실되어도 사용자 코드가 끝났다는 뜻이 아니다. 네트워크 오류 뒤 부작용 있는 코드를 재실행하면 중복 작업이 발생할 수 있다.
- 과거 관측된 터널 지연(약 120초)은 설계 동기였지만 근본 원인은 확정하지 못했다. 현재 시간 한계는 과거 측정값이 아니라 [timeouts](../timeouts.md)에서 확인한다.
- 알 수 없는 MCP 인자가 조용히 무시되던 문제 때문에 strict schema가 필요했다.

**목표는 foreground를 나중에 durable하게 만드는 게 아니라, 모든 실행을 처음부터 durable하게 만드는 것.**

## Lifecycle과 권위

| 객체 | 역할 |
|---|---|
| Execution | 수락·실행·완료/실패/취소/유실의 SQLite control-plane record |
| Worker | `accepted → running` CAS 이후에만 사용자 코드 실행; 자식 프로세스 containment와 evidence 기록 |
| Task | 같은 Execution의 publication/awareness; 별도 작업이나 ID가 아님 |
| Artifact | request, stdout/stderr, outcome 등 복구 증거; 독립 상태 권위가 아님 |

- **하나의 identity:** 공개 lifecycle handle은 `execution_id`다.
- **별도 awareness:** Task가 publish/dismiss돼도 Execution lifecycle을 되돌리거나 재시작하지 않는다. `get`은 비파괴 조회, `dismiss`만 awareness를 제거한다.
- **복구:** Worker claim과 저장된 outcome 증거로 reconcile한다. 불확실하면 `lost`이며 코드 자동 replay/retry는 없다.
- **취소:** 명시적 cancel 요청이 Runtime cancellation을 결정한다. Transport 단절과 timeout 응답은 cancellation이 아니다.
- **예산:** Runtime이 work cutoff와 child budget을 계산한다. 모델 임의의 timeout 인자를 신뢰하지 않는다.
- **직접 명령:** `run_command`는 Execution 안에서 await되는 capability이며 명령과 자식을 부모 예산·취소 경계에 묶는다.
- **장기 위임:** 명시적인 `systemd-run --user` sibling 작업은 GPT Dive Execution/Task/retention 보장의 **밖**에 있다.
- **MCP surface:** `bootstrap`, `code_mode`, `task`, emergency `wsl_exec`. 정확한 인자와 응답은 live schema가 권위다. 원시 `wsl_exec`의 정책 경계는 코드와 Wiki 규칙을 따른다.
- **Model calls:** `agy_worker`, `peer_review` 등은 기본적으로 Code Mode capabilities. 범용 top-level delegate tool과 중복 task store를 만들지 않는다. 특정 AGY top-level 확장은 별도 [미구현 설계](TODO-durable-agy-worker-mcp-surface.md)다.

## Rejected alternatives

| 대안 | 기각 이유 |
|---|---|
| foreground 시작 후 timeout에 detach | 수락과 실행 사이의 durability gap 유지 |
| 항상 Task 발행 / 별도 task_id | 사용자 결과와 awareness를 불필요하게 결합 |
| 파일 + SQLite 둘 다 lifecycle authority | 복구 판단 충돌 |
| 실패·lost 자동 재실행 | side effect 중복 위험 |
| `setsid nohup`로 긴 작업 자동 전환 | containment·취소·상태 보장 상실 |
| 모델이 deadline 등급·값 선택 | 서버의 안전·수명 정책 우회 |
| task lifecycle을 Monty 코드 안에 구현 | 제어 계층의 소유권 혼합 |

## Consequences / validation

SQLite journaling·claim CAS·process containment·evidence reconciliation·strict MCP validation을 보호하는 테스트가 필요하다. 정상 inline 결과가 Task로 공개되지 않아도 Execution은 기록되며, 출력 손실 후에는 기존 `execution_id`와 증거를 먼저 확인한다.

- [Runtime architecture](../architecture.md) — **현재** 구현과 프로세스 경계.
- [Runtime operations](../operations.md) — 현재 검증·재시작.
- [ADR 0005](0005-code-mode-output-contract.md) — Code Mode 출력 의미; 이 ADR의 lifecycle과 독립.
- [Conduit ADR 0002](../../conduit/adr/0002-trackedtasks-refresh-and-opportunistic-evidence-pickup.md) — Task 인지와 opportunistic pickup.

2026-08-27 설계 토론과 중간 구현 상세는 Git 이력에 보존한다. 과거 수치나 설계 스케치는 현재 런타임 계약이 아니다.
