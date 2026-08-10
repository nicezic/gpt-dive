# Architecture Context — Fresh Session Bootstrap

> **Purpose**: 신규 SOL / Peer Reviewer가 정보 부족 때문에 잘못된 문제를 풀지 않도록, 현재 architecture decision의 핵심 causal context를 제공한다.
> **Audience**: 새 ChatGPT Web SOL session, Opus-5 Peer Review session, 중간 합류 Agent/Reviewer
> **Last Updated**: 2026-08-10

이 문서는 단순 architecture summary가 아니다.

이번 첫 Design Council에서 Opus가 처음에는 proposal을 의심했지만, User가 빠진 context를 보강한 뒤 **reject 성격의 challenge → approve + API improvement**로 판단을 수정했다.

따라서 신규 session에서는 **결론만 읽지 말고, 왜 그 결론이 나왔는지 먼저 이해하는 것**이 중요하다.

---

## 1. User Economics & Quota Reality

### ChatGPT Web SOL

- **Account**: ChatGPT Plus (2026-08-08 기준 확인)
- **Web SOL quota**: 실제 사용에서 매우 넉넉함
- **Usage pool**: standard ChatGPT reasoning 쪽으로 관찰됨
- **Operational meaning**: 강한 SOL을 직접 engineer로 쓰는 것이 현재 경제적으로 유리함

즉 현재 전략은 "SOL token을 무조건 아끼자"가 아니다.

> **SOL이 가장 잘하는 engineering 판단은 SOL이 직접 한다.**

### MCP Tunnel

현재 핵심 path:

```text
ChatGPT Web SOL
  ↓
Secure MCP Tunnel
  ↓
@dive
  ↓
local WSL2
```

현재 계정에서 이 흐름은 Web SOL을 local development에 직접 활용할 수 있게 해준다.

**Implication**:

- SOL이 repo를 직접 inspect할 수 있음
- 직접 edit / test / verify 가능
- 단순히 local 작업을 위해 Codex/M3 같은 별도 Agent에게 모든 것을 넘길 필요가 없음

### MiniMax M3

- **Quota**: 매우 넉넉함
- **Status**: quota와 별개로 reliability variance가 큼
- **Observed issue**: reread, raw-context leak, token amplification 등 반복 경험
- **Current role**: normal Orchestra routing에서는 제외, cheap/disposable experiment 정도만 예외적으로 고려

### Operational Reality

현재 economics가 의미하는 기본 전략:

```text
SOL Solo-first
  ↓
필요할 때만 selective worker / Peer Review
```

이 economics가 미래에 바뀌면 routing decision도 다시 검토해야 한다.

---

## 2. Platform Constraints

### MCP Tasks Extension

현재 이 ChatGPT Web ↔ GPT Dive connection에서는:

```text
io.modelcontextprotocol/tasks
```

MCP Tasks extension이 negotiate되지 않았다.

**Impact**:

```text
background job 완료
   ↓
SOL 자동 wake-up / completion push
```

형태를 현재 사용할 수 없다.

따라서 detached async job은 완료 여부를 나중에 polling해야 한다.

### Important Decision

이 platform limitation을 custom infrastructure로 억지로 복제하지 않는다.

```text
Custom completion-push protocol ❌
거대한 scheduler              ❌
현재 필요한 최소 async        ✅
```

향후 ChatGPT Web이 MCP Tasks를 지원하면 그때 standard lifecycle로 자연스럽게 연결하는 것을 선호한다.

---

## 3. Actual Workflow Pain

이 부분이 가장 중요하다.

### Problem Statement

SOL은 긴 execution을 시작한 뒤에도 같은 reasoning flow에서 다른 일을 계속하고 싶다.

예:

```text
Terra → 긴 review / test
Luna  → 별도 분석
local → test / profiling

그동안 SOL은:
- User와 다음 design 논의
- 코드 review
- 다음 phase 계획
- 다른 독립 작업
```

을 계속하고 싶다.

### Current Blocking

현재 일반 `code_mode` call은 내부에서 async/parallel이 가능해도 **Web SOL caller 관점에서는 call이 끝날 때까지 기다린다.**

```python
results = await asyncio.gather(
    subagent_call(...),
    local_exec(...),
)
```

내부 parallelism은 이미 된다.

문제는 이 Monty program 전체가 끝날 때까지 SOL의 현재 tool call이 반환되지 않는다는 점이다.

### Not the Problem

다음 문제를 해결하려는 것이 아니다.

- "SOL 대신 autonomous Agent가 필요하다" → 아님
- "SOL quota가 부족하다" → 현재는 아님
- "모든 workflow를 durable orchestration으로 만들자" → 아님
- "브라우저 탭을 하나 더 열 수 없다" → 핵심 아님

### Real Need

> **SOL의 reasoning flow를 긴 execution에서 해방시키는 것.**

자동화 자체가 목표가 아니다.

---

## 4. Current Architecture

### MCP Surface

현재 Web-facing MCP surface는 4개로 유지한다.

```text
bootstrap    → fresh session trusted context
code_mode    → PRIMARY execution root
wsl2_sync    → 짧은 direct shell
wsl2_async   → low-level durable shell/process lifecycle
```

새 기능이 생겨도 가능하면 top-level tool을 늘리기보다 `code_mode` 뒤 capability / backend를 확장한다.

### `code_mode`

현재 `code_mode`는 Pydantic Monty 기반 programmable execution root다.

주요 특징:

- async Python 사용 가능
- `asyncio.gather()` 병렬 실행 가능
- local WSL2 filesystem read-write
- stateless per call
- large intermediate output을 sandbox에서 filter / aggregate 가능

현재 registry에는 다음 capability가 있다.

```text
local_exec
local_start
local_status
local_result
local_cancel
subagent_call
```

### JobManager

이미 durable local process job infrastructure가 존재한다.

- job별 `job_id`
- timeout
- status / result / cancel
- concurrent jobs
- completed log retention 5일
- systemd-user backend + fallback

따라서 background execution을 위해 새 process manager를 만들 이유가 없다.

---

## 5. Alternatives Rejected

### DBOS / Temporal / Full Workflow Engine

**Rejected because**: 현재 문제는 "SOL이 긴 실행 동안 block된다"는 작은 문제다. Durable reasoning/workflow framework는 현재 scope에 비해 너무 크다.

### Full Autonomous Multi-Agent Orchestra

**Rejected because**: SOL이 Primary Engineer로 잘 작동하고 있으며, 다른 model은 bounded worker 또는 Peer Reviewer로 쓰는 편이 현재 목적에 맞다.

### Direct `wsl2_async` as Main Interface

**Rejected because**: User의 기본 mental model은 `code_mode`이고, Monty + registry + parallel composition을 primary root로 유지하고 싶다.

### New Top-level Lifecycle Tools

**Rejected because**: MCP surface를 작게 유지하고 싶다.

### Custom Completion Push

**Rejected because**: MCP Tasks 미지원이라는 platform gap을 우리가 별도 protocol로 재구현하는 것은 과도하다.

### Streaming Background Output

**Rejected because**: complexity 대비 현재 value가 작다. 완료 후 batch result면 충분하다.

---

## 6. Approved Design

### Normal Execution

기존 API 그대로 유지한다.

```python
code_mode(code="...")
```

- 완료까지 기다림
- 내부 async / parallel 가능
- 기존 caller behavior 유지

### Background Execution

긴 작업만 명시적으로 detach한다.

```python
code_mode(
    code="...",
    background=True,
)
```

- Monty program 전체를 background로 실행
- 즉시 `job_id` 반환
- SOL은 다른 reasoning / discussion / work를 계속할 수 있음

### Lifecycle

```python
code_mode(action="status", job_id="...")
code_mode(action="result", job_id="...")
code_mode(action="cancel", job_id="...")
```

### Why `background=True`

최초 proposal은 다음과 같았다.

```python
code_mode(action="sync", ...)
code_mode(action="start", ...)
```

Design Council에서 Opus가 API ergonomics를 challenge했고, 다음 이유로 `background=True`를 채택했다.

- 기존 95% 호출에 noise가 없음
- zero breaking change
- "background로 실행한다"는 affirmative intent가 명확함
- complexity가 필요한 순간에만 드러나는 progressive disclosure

---

## 7. Explicit Non-goals / Deferred Edge Cases

현재는 만들지 않는다.

- automatic job discovery
- streaming output
- hard concurrent-job limits
- CPU/RAM resource manager
- automatic filesystem locking
- durable reasoning state
- custom completion notification
- DBOS / Temporal integration

### Why

상상 가능한 모든 failure mode를 미리 해결하는 것이 목적이 아니다.

> **실제로 발생한 pain을 가장 작은 architecture change로 해결한다.**

필요가 실제로 생기면 capability를 확장한다.

---

## 8. Implementation Items to Confirm

Architecture decision에는 영향이 없지만 implementation 전에 실제 코드로 확인할 부분:

- `JobManager.start()`와 code-mode background wrapper의 정확한 연결 방식
- `MontyComplete.output`을 background result로 어떻게 serialize/store할지
- background Monty exception/failure를 `result`에서 어떤 contract로 반환할지

현재 방향은 이 세부사항 때문에 다시 architecture discussion을 열 필요는 없는 것으로 판단했다.

---

## 9. Why This Context Matters

### Context가 부족했을 때

Reviewer가 보는 것은 단순히:

> "code_mode에 background execution을 넣자"

뿐이다.

그러면 자연스럽게 다음을 의심할 수 있다.

- 왜 필요한가?
- autonomous Agent를 만들려는 건가?
- quota 최적화인가?
- premature optimization 아닌가?

실제 첫 Council에서 비슷한 일이 발생했다.

### Full causal context가 있을 때

```text
Web SOL quota가 넉넉함
        ↓
SOL이 Primary Engineer로 직접 일하는 것이 유리
        ↓
하지만 긴 MCP call은 reasoning flow를 block
        ↓
내부 parallelism과 JobManager는 이미 존재
        ↓
MCP Tasks completion push는 현재 미지원
        ↓
그러면 가장 작은 해법은?
        ↓
code_mode + optional background=True
```

이 흐름을 알면 reviewer는 잘못된 문제를 다시 풀지 않고, **실제 남은 trade-off**를 challenge할 수 있다.

---

# Fresh Session Rule

새 SOL / Opus / Reviewer는 중요한 design discussion 전에 다음 순서로 orientation한다.

1. **이 문서를 먼저 읽는다.**
2. 현재 repo/runtime의 volatile fact는 live inspection으로 확인한다.
3. `meeting-notes.md`에서 최근 결정사항을 확인한다.
4. `design-council-log.md`에서 review 과정과 lesson을 확인한다.
5. proposal을 challenge하기 전에 **economics / actual pain / rejected alternatives**를 이해했는지 확인한다.
6. 문서와 live state가 다르면 live evidence를 우선하고 문서를 업데이트한다.

## Reviewer Reminder

> **결론을 믿으라는 문서가 아니다.**
> **올바른 문제를 challenge하기 위해 필요한 context를 제공하는 문서다.**

좋은 Peer Review는 disagreement를 없애는 것이 아니라, 충분한 context 위에서 더 정확한 disagreement를 만드는 것에서 시작한다.

---

## 10. Current Handoff State — 2026-08-10

현재 Design phase는 종료됐다.

- **Architecture**: ✅ Council Converged
- **Implementation Plan**: ✅ SOL live-code correction + Opus re-validation 완료
- **Plan**: `plans/2026-08-10-code-mode-background.md`
- **Implementation**: 아직 시작하지 않음
- **Remaining design dissent**: 없음
- **Remaining implementation check**: `MontyComplete.output` serialization contract

### Live-code correction already agreed

```text
registry snapshot
      ❌
worker-side registry rebuild
      ✅
```

`JobManager`는 durable shell/process lifecycle을 담당하고, background Code Mode worker가 fresh Monty runtime + registry를 재구성한다.

### Fresh SOL Session Start

새 session에서 architecture를 처음부터 다시 토론하지 않는다. 다음 순서로 시작한다.

1. `@dive bootstrap`
2. 이 문서 `docs/architecture-context.md` 확인
3. `plans/2026-08-10-code-mode-background.md` 확인
4. volatile implementation fact만 live code로 재확인
5. implementation 진행

새 evidence가 기존 decision을 깨는 경우에만 Council을 다시 연다.
