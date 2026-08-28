# GPT Dive Runtime Deadline

> 현재 clock ownership과 containment 계약. ADR 0004가 결정을 소유하고 `app.py`, `execution_manager.py`, `execution_worker.py`, `execution_context.py`가 구현한다.

## 이 clock들이 필요한 이유

관찰된 ChatGPT tunnel은 약 120초에 응답을 끊을 수 있다. 그러나 Runtime은 이 transport 문제가 고쳐지든 끝내 원인을 모르든 올바르게 동작해야 한다. 따라서 durability는 사용자 code보다 먼저 시작하고, deadline은 transport health를 추측하는 대신 resource를 제한한다.

```text
t=0       accepted Execution commit
│
├─ 100s   auto-mode inline wait 종료
│          └─ 끝나지 않은 작업을 Task로 publish; 재시작하지 않음
├─ 110s   MCP response deadline
│
├─ 43190s Execution work cutoff (12h - 10s)
│          └─ TERM → KILL → drain/reap
└─ 43200s absolute Execution lifetime (12h)

t≈120s    관찰된 외부 tunnel 경계
           └─ 외부 증거일 뿐 Runtime clock이 아님
```

각 work/wait cutoff 뒤 10초는 runtime bookkeeping 또는 cleanup reserve다. 사용자 code에 주는 추가 시간이 아니다.

## Inline delivery

```text
mode=auto
├─ 100초 전에 terminal result → completed/error, Task 없음
├─ 100초에도 실행 중          → Task publish + execution_id 반환
└─ waiter/transport cancel     → Task publish, Execution 계속

mode=task
└─ launch 시 publish하고 즉시 반환
```

110초 response deadline은 acceptance, Worker launch, inline observation, Task publication, result shaping을 감싼다. Execution cutoff로 사용하지 않는다. 공개 cancellation은 명시적 `task(action="cancel")`뿐이다.

## Execution lifetime

모든 Execution은 `accepted` row가 commit될 때 고정 wall-clock timestamp를 받는다.

```text
work_deadline_at     = accepted_at + 43190s
absolute_deadline_at = accepted_at + 43200s
```

Work cutoff에 도달하면 Worker가 소유 process tree를 종료한다. Deadline expiry 표현은 하나다.

```text
state  = failed
reason = deadline_exceeded
```

`timed_out` lifecycle state나 caller-selected short/long tier는 없다. Cleanup이 성공하면 그 시점까지의 stdout/stderr를 보존한다.

Systemd backend는 transient unit에 `RuntimeMaxSec=43200s`와 `TimeoutStopSec=10s`도 적용한다. Popen backend는 Worker의 같은 application clock과 subreaper 기반 descendant containment로 동등한 경계를 지킨다.

## Child capability budget

모델은 `agy_worker`, `subagent_call`, `peer_review`, `run_command`에 `timeout`을 넘길 수 없다.

```text
effective child budget
    = min(capability policy, 남은 Execution work budget)
```

현재 policy ceiling:

| Capability | 상한 |
|---|---:|
| `agy_worker` | 360초 |
| `subagent_call` | 600초 |
| `peer_review` | 600초 |
| `run_command` | 43,190초 |

`deadline_remaining()`은 Monty code가 새 단계를 시작할 가치가 있는지 판단하도록 live read-only remainder를 제공한다. Deadline을 바꾸거나 capability timeout 인자로 되돌릴 수는 없다.

`run_command`는 effective budget 중 9초를 자체 TERM/KILL/drain에 남긴다.

```text
command wait = effective budget - 9s
cleanup      = SIGTERM 4s → SIGKILL 4s → final reap/drain
```

남은 시간이 9초 이하면 command 시작을 거부한다. 다른 worker-based capability는 자체 bounded cleanup을 사용하며, 최종 containment는 owning Execution deadline이 보장한다.

## Recovery는 새 시간을 주지 않는다

Restart recovery는 durable state를 관찰할 뿐 deadline을 다시 시작하지 않는다.

```text
accepted but never claimed
└─ launch grace 뒤 → failed(launch_interrupted)

running but Worker/outcome no longer observable
└─ lost

모든 recovery state
└─ replay/retry 없음
```

Wall-clock deadline timestamp 덕분에 이미 spawn된 Worker는 새 43,190초가 아니라 남은 budget만 계산한다.

## Retention clock

`run_command` spill을 포함한 terminal artifact는 Execution과 함께 5일 보존한다. Published Task를 dismiss하지 않았다고 해서 만료된 artifact를 계속 보관하지는 않는다. 대신 Task를 `lost(reason=retention_expired)`로 남겨 처리되지 않은 awareness가 조용히 사라지지 않게 한다.

## 첫 failure boundary 진단

```text
약 100초에 Task 반환
└─ 정상 inline delivery 경계; Execution은 계속 로컬에서 소유됨

failed(reason=deadline_exceeded)
└─ Runtime work cutoff; partial output과 workload 크기 확인

tunnel 502 / MCP request-entry log 없음
└─ Runtime이 call을 소유하기 전 외부에서 실패
```

## 참고 문서

- `docs/runtime/adr/0004-always-durable-code-mode-runtime.md`
  - Durability, fixed clock, transport-loss 정책의 accepted rationale.
- `src/gpt_dive/execution_context.py`, `src/gpt_dive/code_capabilities.py`
  - Child budget 계산과 capability별 ceiling.
- `src/gpt_dive/execution_worker.py`, `src/gpt_dive/command_runtime.py`
  - Process-tree termination, cleanup reserve, bounded output drain.
- `docs/runtime/operations.md`
  - Operational state inspection과 live acceptance.
