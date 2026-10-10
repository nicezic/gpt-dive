# GPT Dive Runtime Deadline

> 현재 clock ownership과 containment 계약. ADR 0004가 결정을 소유하고 `app.py`, `execution_manager.py`, `execution_worker.py`, `command_runtime.py`가 구현한다.

## 이 clock들이 필요한 이유

2026-09-22 실측: GPT Dive의 70초 auto 작업은 로컬에서 정상 완료됐으나 ChatGPT가 결과를 못 받았고 같은 명령이 새 Execution으로 다시 실행됐다. 별도 Conduit 경계 시험에서는 서버 작업 60.0초의 성공과 60.1초의 실패가 반복됐다. 이는 관찰값이며 OpenAI 내부 설정값이나 GPT Dive의 성공 보증값은 아니다. Runtime의 durable work lifetime은 transport 한도와 독립적이다.

2026-10-10 재측정: `wsl_exec` 117초 작업은 Web 응답에 성공했고 124초 작업은 실패했다. OpenAI가 실제 전달하는 `response_timeout` 값은 아직 미확인이다. GPT Dive는 **120초를 운영상 가정한 응답 시간 예산**으로 사용하며, OpenAI가 보장하는 한도를 뜻하지 않는다.

```text
t=0       accepted Execution commit
│
├─ 114s    auto-mode inline wait 종료
│          └─ 이미 완료됐더라도 cutoff 뒤에는 같은 실행을 Task로 publish
├─ 117s    GPT Dive 내부 MCP response deadline
│
├─ 43190s Execution work cutoff (12h - 10s)
│          └─ TERM → KILL → drain/reap
└─ 43200s absolute Execution lifetime (12h)

t≈60s     2026-09-22 별도 Conduit 시험에서 관찰된 실패 경계
           └─ 외부 증거일 뿐 공식 OpenAI 한도나 Runtime clock이 아님
```

114초와 117초 사이 3초는 GPT Dive 내부 Task 공개·응답 처리를 위한 여유다. 117초와 가정된 120초 예산 사이에도 3초를 남기지만, 이 여유가 있다고 해서 터널 전송·ChatGPT 수신까지 보장하지 않는다. 43,190초 work cutoff 뒤 10초는 cleanup reserve이지 사용자 code에 주는 추가 시간이 아니다.

## Inline delivery

```text
delivery=auto
├─ 114초 전에 결과 구성 완료 → completed/error, Task 없음
├─ 114초에 inline 대기 만료   → 이미 terminal이어도 Task publish + 동일 execution_id 반환
└─ 관측된 waiter/transport cancel → Task publish, Execution 계속

delivery=task
└─ launch 시 publish하고 즉시 반환
```

117초 response deadline은 GPT Dive 내부 acceptance, Worker launch, inline observation, Task publication, result shaping의 한도다. Wrapper의 TrackedTasks 조회·직렬화 및 tunnel 전달은 여기에 포함되지 않을 수 있어 ChatGPT 수신 시각을 보장하지 않는다. 상위 호출 실패가 Runtime cancellation으로 전달된다고 보장할 수도 없다. 같은 부작용 작업의 자동 재시도를 금지한다. 공개 cancellation은 명시적 `task(action="cancel")`뿐이다.

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

Execution terminal artifact와 SQLite `run_command` evidence는 5일 보존한다. `/tmp` working evidence는 Execution `accepted_at`으로부터 48시간 후 cleanup 대상이 된다. Published Task를 dismiss하지 않았다고 해서 만료된 durable artifact를 계속 보관하지는 않는다. 대신 Task를 `lost(reason=retention_expired)`로 남겨 처리되지 않은 awareness가 조용히 사라지지 않게 한다.

## 첫 failure boundary 진단

```text
약 114초에 Task 반환
└─ 정상 inline delivery 경계; Execution을 재시작하지 않고 동일 ID로 공개

`Code Mode tool call timed out` 등 최상위 도구 오류
└─ 실행 실패로 단정하지 않고 기존 Task/Execution 증거 확인. 같은 명령을 맹목적으로 재호출하지 않음

오래된 `accepted` Execution
└─ 기존 launch grace 경과 후 `launch_interrupted`로 복구; 114/117초 응답 설정과 무관

failed(reason=deadline_exceeded)
└─ Runtime work cutoff; partial output과 workload 크기 확인

tunnel 502 / MCP request-entry log 없음
└─ Runtime이 call을 소유하기 전 외부에서 실패
```

## 참고 문서

- `docs/runtime/adr/0004-always-durable-code-mode-runtime.md`
  - Durability, fixed clock, transport-loss 정책의 accepted rationale.
- `src/gpt_dive/command_runtime.py`, `src/gpt_dive/code_capabilities.py`
  - Child budget 계산과 capability별 ceiling.
- `src/gpt_dive/execution_worker.py`, `src/gpt_dive/command_runtime.py`
  - Process-tree termination, cleanup reserve, bounded output drain.
- `docs/runtime/operations.md`
  - Operational state inspection과 live acceptance.
