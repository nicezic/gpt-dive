# Meeting Notes

> **Purpose**: Design Council 회의에서 무엇을 논의했고 무엇을 결정했는지 빠르게 남기는 기록
> **Default Rule**: 기존 기록은 고치기보다 **append(뒤에 추가)** 를 기본으로 한다. 사실 오류나 명백한 정정이 필요한 경우만 기존 항목을 수정한다.

## Council Protocol

### Input Requirements

Peer Reviewer에게 보내는 review packet에는 최소한 아래 context가 들어가야 한다.

- **History**: 여기까지 어떻게 왔는가
- **Problem**: 실제로 관찰된 pain point와 user economics
- **Constraints**: technical / platform / quota 제약
- **Current State**: 지금 이미 무엇이 구현되어 있는가
- **Alternatives**: 어떤 대안을 검토했고 왜 버렸는가
- **Proposal**: 현재 제안하는 방안
- **Uncertainties**: 아직 확정되지 않은 질문

### Review Process

1. Reviewer는 결론 자체보다 **assumption(전제)** 을 먼저 challenge한다.
2. Author/SOL은 방어적으로 설득하기보다, 부족했던 context와 evidence를 보강한다.
3. 합의가 생기거나 fundamental disagreement가 명확해질 때까지 필요한 만큼만 반복한다.
4. 마지막에는 **consensus + dissent + open items** 를 기록한다.
5. User는 domain reality와 실제 사용 목적을 보충하고 최종 방향을 결정한다.

### Output Format

- **Verdict**: approve / reject / needs-revision
- **Rationale**: 판단을 바꾼 핵심 이유
- **Improvements**: review를 통해 실제로 좋아진 부분
- **Remaining Dissent**: 끝까지 남은 disagreement가 있다면 기록
- **Action Items**: 다음 concrete step

---

## Sessions

### 2026-08-10 — Design Council Round 1 & 2

**Participants**: SOL (GPT-5.6), Opus-5 (Peer Reviewer), User
**Topic**: `code_mode` background execution architecture
**Status**: ✅ Converged

#### Key Decisions

- GPT Dive의 **primary execution root는 계속 `code_mode`** 로 유지한다.
- 일반 실행은 기존처럼 `code_mode(code="...")` 로 완료까지 기다린다.
- SOL을 오래 block할 작업만 `code_mode(code="...", background=True)` 로 detach한다.
- background lifecycle은 `status / result / cancel` 로 관리한다.
- 새 async engine을 만들지 않고 기존 `JobManager`를 재사용한다.
- `wsl2_async`는 low-level shell/process lifecycle path로 남긴다.
- 현재 단계에서 DBOS / Temporal / scheduler / streaming / resource manager를 추가하지 않는다.

#### Improvements from Review

- 최초 제안의 `action="sync" / action="start"` naming을 버렸다.
- Opus challenge를 받아들여 **`background=True`** 로 변경했다.
- Reason: 기존 호출은 그대로 유지되고, background가 필요한 5%의 경우에만 complexity가 드러난다.
- Council packet에는 proposal만이 아니라 **history + economics + constraints + actual pain** 이 반드시 필요하다는 lesson을 얻었다.

#### Action Items

- background Monty result serialization 방식 확인
- background exception/failure result contract 확인
- 승인된 API를 기준으로 implementation 진행
- 구현 완료 후 Result / deviation이 있으면 이 회의록에 append

---

## Template for New Sessions

```markdown
### YYYY-MM-DD — [Session Title]

**Participants**:
**Topic**:
**Status**: 🔄 In Progress / ✅ Converged / ⚠️ Blocked

#### Context Added
- 이번 회의에서 새로 확인된 중요한 context

#### Key Decisions
-

#### Improvements from Review
-

#### Remaining Dissent
- 없음 / ...

#### Action Items
-
```

---

### 2026-08-10 — Plan Verification & Implementation Handoff

**Participants**: SOL (GPT-5.6), Opus-5 (Peer Reviewer), User
**Topic**: `code_mode` background implementation plan 검증
**Status**: ✅ Final PASS / Ready for Implementation

#### Final Review Loop

1. Opus가 compact implementation plan skeleton을 작성했다.
2. SOL이 live repo를 확인해 `JobManager`의 실제 역할을 검증했다.
3. `registry snapshot` 가정을 **worker-side registry rebuild**로 교정했다.
4. Opus가 correction을 다시 검토했고 original design intent와 충돌 없음을 확인했다.

#### Final Implementation Boundary

- `JobManager`는 generic coroutine executor가 아니라 durable shell/process lifecycle manager다.
- background Code Mode는 작은 worker process를 `JobManager`로 실행한다.
- worker는 fresh Monty runtime + registry를 child process 내부에서 재구성한다.
- `CallableRegistry` 자체는 serialize/snapshot하지 않는다.
- result 판단은 lifecycle status만 보지 않고 `exit_code` + structured worker envelope를 함께 본다.

#### Remaining Open Item

- `MontyComplete.output`의 worker process boundary serialization contract만 implementation에서 확인한다.
- 이 항목은 architecture 재논의 대상이 아니라 implementation detail이다.

#### Communication Rule

SOL이 Opus에게 전달할 Council message는 sender를 즉시 식별할 수 있도록 첫 줄에 다음 header를 붙인다.

```markdown
# Sol -> Opus
```

#### Next Session Start

새 SOL session은 `bootstrap` 후 `docs/architecture-context.md`와 `plans/2026-08-10-code-mode-background.md`를 읽고 implementation부터 시작한다.
