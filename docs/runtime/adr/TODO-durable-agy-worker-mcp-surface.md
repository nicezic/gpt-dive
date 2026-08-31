---
title: TODO - Durable AGY Worker MCP Surface
created: 2026-08-30
type: decision
status: accepted
---

# TODO — Durable AGY Worker MCP Surface

> `agy_worker`를 Code Mode 내부 capability로 유지하면서, Zed 같은 외부 agent harness가
> 직접 위임할 수 있는 top-level MCP tool로도 노출하는 결정 기록이다.
> durable execution의 상위 권위는 ADR 0004의 `ExecutionManager` 모델을 그대로 따른다.
>
> 이 ADR은 ADR 0004의 일반적인 "agent/model 호출을 top-level MCP tool로 만들지 않는다"는
> 기각안을 **AGY 하나에 한해 좁게 수정**한다. 다른 agent/model capability를 일반적으로
> top-level surface로 승격하는 결정은 아니다.

## 결정 요약 (Decision summary)

`agy_worker`는 두 개의 호출 surface를 갖되, AGY CLI 계약과 결과 해석은 하나의 shared
integration core를 사용한다.

```text
                         ┌─ Code Mode Execution
                         │      │
                         │      └─ agy_worker capability
                         │             │ awaited child call
                         │             ▼
                         │        shared AGY core
                         │             │
                         │             ▼
                         │          agy CLI
                         │
external MCP client ─────┤
(Zed Native Agent 등)    │
                         │
                         └─ top-level agy_worker MCP tool
                                │
                                ▼
                         ExecutionManager
                           kind = "agy"
                                │
                      ┌─────────┴─────────┐
                      ▼                   ▼
                inline result       GPT Dive Task
                                  get/cancel/dismiss
```

결정은 네 가지다.

1. `agy_worker`를 top-level MCP Tool로 노출한다.
2. top-level AGY 실행은 `ExecutionManager(kind="agy")`가 소유하고 기존 GPT Dive Task
   lifecycle을 재사용한다.
3. Code Mode 내부 `agy_worker`는 지금처럼 부모 Code Mode Execution 안에서 await되는
   child capability로 유지한다. nested durable Task를 만들지 않는다.
4. 공식 MCP Tasks extension은 현재 구현하지 않는다. 미래 adapter가 같은 Execution을
   projection할 수 있도록 protocol 경계만 보존한다.

AGY headless integration은 Antigravity가 제공하는 공식 `stream-json` NDJSON 계약을 primary
path로 사용한다. PTY/terminal scraping은 fallback으로 추가하지 않는다.

## 왜 필요한가 (Why this exists)

현재 `agy_worker`는 Code Mode 안에서만 호출할 수 있다. 이 구조는 ChatGPT Web의 Monty
orchestration에는 잘 맞지만, Zed Native Agent처럼 **MCP tool을 직접 선택하는 외부
orchestrator**는 AGY를 worker로 위임할 수 없다.

```text
현재
────
Zed Native Agent ──X──> Code Mode 내부 agy_worker

ChatGPT Web
    │
    ▼
code_mode
    │
    └─ agy_worker ──> agy CLI

원하는 추가 surface
───────────────────
Zed Native Agent
    │ MCP tool
    ▼
agy_worker
    │
    ▼
Gemini subscription-backed AGY worker
```

여기서 필요한 것은 AGY 전용 두 번째 runtime이 아니라, 이미 존재하는 durable Execution
control plane에 **새 root entrypoint 하나**를 연결하는 것이다.

## 현재 현실과 근거 (Current reality)

### 1. AGY integration core는 이미 분리되어 있다

`src/gpt_dive/code_capabilities.py`의 `agy_worker()`는 실질적인 AGY 구현을 소유하지 않는다.
`src/gpt_dive/agy_worker.py::invoke_agy_worker()`를 호출하는 thin wrapper이며, 현재 다음
계약을 사용한다.

```text
agy -p <task>
    --model <model>
    --output-format stream-json
    --mode plan
    --dangerously-skip-permissions
    --print-timeout <runtime-owned-budget>
    [--conversation <id>]
    [--add-dir <cwd>]
```

따라서 top-level MCP surface를 만들기 위해 AGY CLI parsing이나 conversation logic을 두
벌로 복제할 이유가 없다.

### 2. durable execution ownership은 이미 `ExecutionManager`에 있다

ADR 0004 이후 GPT Dive의 accepted work는 SQLite Execution을 control-plane authority로
사용한다. `ExecutionManager.start()`는 `kind`를 이미 받으며, Task publication,
non-destructive result lookup, cancellation, retention을 같은 Execution 위에서 제공한다.

```text
ExecutionManager
├─ durable acceptance
├─ worker containment
├─ cancel
├─ result / artifact retention
├─ optional Task publication
└─ kind discriminator
      ├─ code_mode
      ├─ conduit
      └─ agy        ← 추가할 execution kind
```

AGY용 `JobStore`, supervisor, status registry를 따로 만들면 동일 lifecycle authority가 두
개가 된다. 이 ADR은 그 중복을 허용하지 않는다.

### 3. 공식 AGY CLI가 machine-readable headless contract를 제공한다

Antigravity CLI 1.1.8(2026-07-28)은 print mode에 `json`과 `stream-json`을 공식 추가했다.
`stream-json`은 NDJSON(Newline-Delimited JSON, 한 줄에 JSON 객체 하나를 흘려보내는
형식)으로 `init` → `step_update` → terminal `result` 이벤트를 제공한다.

현재 GPT Dive가 이미 이 경로를 사용하므로, 과거 community wrapper들이 사용한 PTY
(Pseudo Terminal, 프로그램에 가짜 터미널을 제공하는 방식)나 TUI transcript scraping은
primary transport가 아니다.

### 4. 외부 AGY MCP 구현도 durable lifecycle 필요성에 수렴한다

최근 community bridge들은 AGY가 오래 실행될 수 있다는 현실 때문에 별도 durable
control plane, detached run, status/result/cancel surface를 도입한다.

```text
community bridge
    │
    ├─ run/job store
    ├─ detached supervisor
    ├─ status/result/cancel
    └─ session continuity

GPT Dive
    │
    └─ 위 책임이 이미 ExecutionManager + task 에 존재
```

이 사례들은 AGY를 durable worker로 취급할 필요를 뒷받침하지만, GPT Dive가 그들의
AGY-specific supervisor 구조까지 복제해야 한다는 근거는 아니다.

### 5. 현재 Zed에는 regular MCP Tool이 실용적인 통합 지점이다

2026-08-30 기준 Zed 문서는 MCP의 `Tools`와 `Prompts` 지원을 명시한다. MCP Tasks는 현재
Zed의 지원 surface로 문서화되어 있지 않다.

따라서 당장의 Zed orchestration 목표에는 top-level `agy_worker` Tool이 실제 소비 가능한
경로이고, MCP Tasks extension을 먼저 구현하는 것은 직접적인 사용자 가치를 만들지
못한다.

## 결정 (Decision)

### 1. `agy_worker`를 top-level MCP Tool로 추가한다

top-level tool의 의미는 **독립 read-only AGY worker에게 작업을 위임하는 것**이다.

```text
parent agent
    │
    │ delegate investigation / review / repo exploration
    ▼
agy_worker
    │
    ▼
independent AGY conversation
    │
    ▼
concise result back to parent
```

이 tool은 Zed Native Agent 같은 MCP caller에게 AGY를 agent-as-tool 패턴으로 제공한다.
`spawn_agent`와 같은 native subagent protocol은 아니지만, orchestrator 관점에서는 독립
context를 가진 worker delegation primitive로 사용할 수 있다.

정확한 Pydantic schema와 inline wait 수치는 구현 단계에서 기존 Code Mode delivery
contract와 함께 결정한다. 이 ADR은 입력 필드의 최종 형태보다 ownership과 lifecycle을
결정한다.

### 2. top-level AGY는 `ExecutionManager(kind="agy")`의 root Execution이다

top-level 호출은 durable Execution을 하나 만든다.

```text
agy_worker(...)
      │
      ▼
SQLite Execution: accepted
kind = "agy"
      │
      ▼
AGY worker process
      │
      ├─ bounded inline window 안에 완료
      │      └─ AGY result 반환
      │
      └─ immediate task / inline delivery 불가
             └─ 같은 Execution을 GPT Dive Task로 publish
```

Task lifecycle은 기존 top-level `task` tool이 소유한다.

```text
task({action: "list"})
task({action: "get", execution_id})
task({action: "cancel", execution_id})
task({action: "dismiss", execution_id})
```

`agy_status`, `agy_result`, `agy_cancel`, `agy_sessions` 같은 AGY 전용 lifecycle tool은 만들지
않는다. AGY라고 해서 Runtime lifecycle 언어가 바뀌지 않는다.

### 3. Code Mode capability는 nested Execution을 만들지 않는다

기존 Code Mode 호출:

```text
Code Mode Execution
      │
      └─ await agy_worker(...)
                │
                └─ bounded child worker
```

은 유지한다.

Code Mode capability가 다시 `ExecutionManager(kind="agy")`를 호출하여 nested durable
Execution/Task를 만드는 구조는 도입하지 않는다. 그렇게 하면 parent cancellation,
deadline ownership, Task publication이 두 계층으로 갈라진다.

두 surface가 공유할 것은 **AGY protocol integration**이다.

```text
shared
├─ command construction
├─ model / cwd / conversation argument handling
├─ stream-json parsing
├─ terminal result normalization
└─ failure metadata extraction

surface-specific
├─ Code Mode capability → parent Execution의 child budget을 await
└─ top-level MCP tool   → 독립 durable Execution lifecycle
```

### 4. 공식 `stream-json`을 primary AGY protocol로 유지한다

AGY 호출은 문서화된 headless contract를 우선한다.

```text
preferred
agy --output-format stream-json
    └─ typed NDJSON events

not introduced as fallback
├─ PTY / ConPTY terminal emulation
├─ TUI screen scraping
├─ tmux transcript parsing
└─ undocumented conversation-file scraping을 결과 권위로 사용
```

Antigravity가 공식 machine protocol을 제공하는 동안 terminal emulation을 추가하는 것은
복잡도와 failure mode만 늘린다.

`conversation_id` resume 기능은 공식 CLI 기능이므로 계속 지원한다.

### 5. caller-facing result와 full execution artifact의 경계를 유지한다

AGY는 큰 repository 조사나 긴 reasoning 결과를 만들 수 있다. parent agent context를
무제한 출력으로 오염시키지 않도록 **보존되는 실행 결과와 caller에게 projection되는
결과를 같은 개념으로 고정하지 않는다.**

```text
AGY Execution
    │
    ├─ retained stdout/stderr/result artifacts
    │
    └─ caller-facing result projection
          └─ 필요 시 bounded/truncated representation 허용
```

구체적인 AGY output cap 정책은 이 ADR의 구현 필수 항목이 아니다. 다만 future bounded
projection을 막는 contract는 만들지 않는다.

### 6. MCP Tasks extension은 adapter seam만 보존하고 defer한다

MCP Tasks는 `io.modelcontextprotocol/tasks` extension으로 long-running operation에 durable
task handle을 제공한다. 방향 자체는 GPT Dive Execution 모델과 잘 맞는다.

하지만 현재 구현하지 않는다.

```text
현재
────
MCP agy_worker
      │
      ▼
ExecutionManager
      │
      └─ GPT Dive task projection

미래
────
                 ┌─ GPT Dive task projection
ExecutionManager ┤
                 └─ MCP Tasks adapter
```

future MCP Tasks adapter는 **새 실행 시스템이 아니라 기존 Execution의 protocol
projection**이어야 한다.

현재 GPT Dive의 `execution_id`는 ADR 0004가 정의한 local lifecycle identity다. 미래
표준 adapter가 별도의 protocol `taskId`를 요구하더라도 그것이 두 번째 execution
authority가 되어서는 안 된다. 필요한 경우 adapter가 protocol identity와 내부
`execution_id`를 매핑한다.

MCP Tasks runtime, compatibility shim, speculative wire implementation은 이 ADR에서 만들지
않는다.

## ADR 0004와의 관계

ADR 0004의 다음 invariant는 그대로 유지한다.

- SQLite가 durable control-plane authority다.
- Task publication은 실행을 재시작하거나 소유하지 않는 projection이다.
- timeout/deadline은 Runtime이 소유한다.
- transport 절단은 자동 취소가 아니다.
- 공개 cancellation은 Runtime lifecycle surface를 통해 명시적으로 요청한다.

ADR 0004의 `Rejected alternatives`에 있던 다음 일반 결정은 **AGY에 대해서만 supersede**한다.

> agent/model 호출을 top-level MCP tool로 노출하면 lifecycle contract가 중복되고
> deadline ownership이 여러 root로 갈라진다.

이 우려는 top-level AGY가 별도 lifecycle을 만들 경우에는 여전히 맞다. 이 TODO는
`ExecutionManager`를 동일한 root authority로 재사용함으로써 그 중복을 만들지 않으면서,
새로운 외부 orchestrator 요구를 충족한다.

`subagent_call`, `peer_review` 또는 향후 다른 model capability까지 자동으로 top-level
MCP tool로 승격시키는 선례로 해석하지 않는다. 각각은 별도 요구와 ADR이 필요하다.

## 귀결 (Consequences)

- Zed Native Agent 등 MCP client가 Code Mode를 경유하지 않고 AGY를 직접 worker로
  호출할 수 있다.
- ChatGPT Web에서는 기존 Code Mode `agy_worker` composition이 그대로 유지된다.
- AGY long-running work가 기존 durable Runtime, cancellation, retention, TrackedTasks를
  재사용한다.
- AGY 전용 JobStore/supervisor/status API가 생기지 않아 lifecycle authority가 하나로
  유지된다.
- 동일 AGY integration core를 두 surface가 공유하므로 CLI protocol drift 대응 지점이
  하나다.
- MCP Tasks를 나중에 도입하더라도 AGY execution ownership을 다시 설계할 필요가 없다.
- top-level root와 Code Mode child의 delivery semantics는 다르므로, 구현은 이 차이를
  명시적으로 테스트해야 한다.

## 폐기한 대안 (Rejected alternatives)

### AGY 전용 MCP server/runtime을 별도로 만든다

폐기. community project에서는 필요한 구조지만 GPT Dive에는 이미 durable
`ExecutionManager`가 있다. 별도 store/supervisor는 상태 reconciliation과 cancellation
ownership을 중복시킨다.

### `agy_start/status/read/result/cancel` tool family를 만든다

폐기. AGY worker 특유의 lifecycle이 아니라 일반 durable Execution lifecycle이다. 기존
`task` surface가 같은 기능을 이미 소유한다.

### 하나의 `agy_worker`가 어디서 호출되든 항상 nested durable Execution을 만든다

폐기. Code Mode 안에서는 child capability를 await하는 현재 composition이 더 단순하다.
중첩 Execution은 deadline/cancel/publication ownership을 불필요하게 분할한다.

### 목적별 `agy_search`, `agy_review`, `agy_analyze_files` tool을 만든다

폐기. 일부 community bridge는 caller routing을 돕기 위해 purpose-built tool을 제공하지만,
GPT Dive가 원하는 primitive는 독립 worker delegation이다. task 의미를 서버 schema에
증식시키지 않고 caller가 prompt로 표현한다.

### PTY를 primary AGY transport로 사용한다

폐기. 현재 공식 CLI가 `stream-json` headless output을 제공한다. documented machine
contract가 있는 상황에서 terminal emulation은 추가 failure mode다.

### MCP Tasks extension부터 구현한다

폐기. 현재 Zed의 문서화된 MCP surface는 Tools/Prompts이고, 당장 AGY delegation을 열기
위한 prerequisite가 아니다. Tasks는 소비자가 실제로 negotiate할 때 adapter로 추가한다.

### writable AGY + worktree isolation까지 함께 도입한다

폐기. 현재 `agy_worker` 정책은 `--mode plan`의 read-only worker다. write-enabled executor와
Git worktree isolation은 별도 security/ownership 결정이다.

## Non-goal

- `subagent_call`, `peer_review`의 top-level MCP 승격
- native Zed `spawn_agent` 또는 ACP subagent semantics 모방
- MCP Tasks extension의 현재 구현 또는 compatibility layer
- AGY 전용 Task/Job persistence
- AGY model quota failover/routing policy 확장
- writable AGY execution, 자동 worktree 생성, patch 적용
- PTY/TUI transcript 기반 compatibility fallback
- purpose-built AGY tool family
- Code Mode의 기존 child budget 정책 변경

## 구현 시 보호해야 할 경계 (Implementation guards)

```text
1. top-level AGY acceptance
      → ExecutionManager(kind="agy")

2. Code Mode AGY call
      → parent record의 child budget 사용
      → nested Execution 없음

3. protocol parsing
      → 공식 stream-json terminal result가 authority

4. lifecycle
      → 기존 task tool 하나가 get/cancel/dismiss 소유

5. failure / transport loss
      → ADR 0004의 durable semantics 재사용

6. tests
      → top-level AGY completion / publication / cancel
      → Code Mode capability regression
      → 두 surface의 shared result normalization
```

## References

### Local authority

- `docs/runtime/adr/0004-always-durable-code-mode-runtime.md`
  - 이 ADR이 재사용하는 durable Execution, Task publication, deadline, cancellation의 상위
    architecture authority. AGY top-level 예외가 좁게 supersede하는 기존 기각안도 여기에
    있다.
- `docs/runtime/CONTEXT.md`
  - `Execution`, `Worker`, `Task`, projection의 정식 Runtime 언어와 invariant.
- `src/gpt_dive/agy_worker.py`
  - 현재 AGY command construction, `stream-json` parsing, conversation resume, result
    normalization의 구현 authority.
- `src/gpt_dive/code_capabilities.py`
  - 현재 Code Mode `agy_worker` capability와 child-budget 적용 위치.
- `src/gpt_dive/execution_manager.py`, `src/gpt_dive/app.py`
  - durable Execution start/result/cancel 및 공개 MCP/Task surface의 현재 구현 authority.

### Upstream and ecosystem evidence

- [Google Antigravity — Headless mode](https://antigravity.google/docs/cli/headless/)
  - `-p`, `stream-json`, stdout/stderr separation, `--conversation`, `--print-timeout` 등 공식
    programmable AGY contract의 현재 authority.
- [Google Antigravity — Changelog](https://antigravity.google/changelog)
  - 2026-07-28 v1.1.8에서 print mode의 `json`/`stream-json` machine-readable output이 공식
    추가된 근거.
- [Google Antigravity — Managing conversations](https://www.antigravity.google/docs/cli/conversations/)
  - workspace-scoped conversation history와 resume가 공식 AGY 기능임을 설명한다.
- [varadfromeast/codex-agy-bridge](https://github.com/varadfromeast/codex-agy-bridge)
  - AGY를 durable, resumable MCP worker로 감싸면서 별도 run state와 supervisor를 두는
    community architecture 사례. GPT Dive가 이미 가진 Runtime 책임과 비교하는 근거다.
- [Boulea7/agy-mcp architecture](https://github.com/Boulea7/agy-mcp/blob/main/docs/architecture.md)
  - `agy_start/status/read/result/cancel`과 session store를 별도로 제공하는 사례. GPT Dive가
    AGY-specific lifecycle tool을 중복 도입하지 않는 대조 근거다.
- [PyModel/claude-agy-mcp](https://github.com/PyModel/claude-agy-mcp)
  - parent agent가 MCP를 통해 AGY에 heavy work를 위임하고 concise/bounded result만
    회수하는 agent-as-tool 패턴 및 session continuity 사례.
- [MCP Tasks Extension](https://tasks.extensions.modelcontextprotocol.io/)
  - `io.modelcontextprotocol/tasks`가 long-running operation을 durable task handle로
    projection하는 공식 extension이라는 미래 adapter 기준.
- [Zed — Model Context Protocol](https://zed.dev/docs/ai/mcp)
  - 2026-08-30 기준 Zed가 문서화한 MCP 지원 범위가 Tools와 Prompts임을 확인하는 현재
    integration reality.
