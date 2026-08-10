# Design Council Log

> Design Council 자체가 어떻게 작동했고, 어떤 방식이 실제로 더 나은 결론을 만들었는지 기록하는 **append log**다.
> Architecture decision 자체는 `meeting-notes.md`와 관련 ADR/plan이 담당하고, 이 문서는 **review process의 진화와 lesson**을 남긴다.

---

## 2026-08-10 — First Council Experiment

### Participants

- **Proposer / Primary Engineer**: SOL (GPT-5.6)
- **Peer Reviewer**: Opus-5
- **Domain Owner / Moderator**: User

### Topic

긴 작업 중 SOL의 reasoning flow가 block되는 문제를 줄이기 위해 `code_mode`에 background execution을 추가할지 검토했다.

---

## Process Timeline

### Round 1 — Initial Challenge

Opus에게 처음 전달된 packet은 architecture proposal 자체는 설명했지만, 그 proposal이 나오게 된 **history / economics / actual workflow pain** 이 충분하지 않았다.

그 결과 Opus는 먼저 다음을 의심했다.

> "이게 정말 해결해야 할 문제인가? Premature optimization 아닌가?"

이 challenge 자체는 정상적이고 유용했다. 문제는 reviewer가 잘못했다기보다 **input context가 부족했다는 것**이었다.

### Context Fill-up

User가 다음 context를 직접 보강했다.

- Web SOL quota가 현재 실제 사용에서 매우 넉넉함
- 목표는 SOL을 다른 Agent로 대체하는 것이 아님
- MCP Tasks extension이 현재 ChatGPT Web ↔ Dive 연결에서 negotiate되지 않음
- 실제 pain은 긴 tool execution 동안 **한 reasoning flow 안에서 SOL이 다음 판단/대화/설계를 이어가기 어렵다는 것**
- 이미 `code_mode`, async registry, `JobManager`가 구현되어 있어 새 framework가 필요한 상황이 아님

이 context가 들어가자 review의 질문이 바뀌었다.

```text
Before: "왜 이걸 만들어야 하지?"
After:  "그렇다면 어떤 API가 가장 단순하고 자연스러운가?"
```

### Round 2 — Convergence

Opus는 core architecture를 **APPROVE**했고, 대신 API ergonomics를 challenge했다.

우리의 최초 proposal:

```python
code_mode(action="sync", code="...")
code_mode(action="start", code="...")
```

Opus가 제안한 방향:

```python
code_mode(code="...")
code_mode(code="...", background=True)
```

SOL과 User가 검토한 결과 `background=True`가 더 낫다고 수용했다.

---

## What Worked ✅

1. **Independent challenge**
   Opus가 SOL의 결론에 맞춰주지 않고 문제 정의부터 의심했다.

2. **Context responsiveness**
   추가 context가 들어오자 기존 판단을 고집하지 않고 verdict를 수정했다.

3. **Concrete improvement**
   단순한 찬반을 넘어서 `background=True`라는 실제 API 개선이 나왔다.

4. **No false consensus**
   처음부터 의견이 같았던 것이 아니라 disagreement → context → convergence 순서로 더 나은 결론에 도달했다.

5. **User가 중요한 역할을 했다**
   User가 quota/economics와 실제 workflow reality를 넣어주면서 두 AI의 추상적 추론을 현실에 다시 연결했다.

---

## What Didn't Work ⚠️

1. **Initial review packet이 너무 얇았다**
   Current architecture는 설명했지만, 왜 그 architecture가 필요한지에 대한 causal context가 부족했다.

2. **Reviewer가 빈칸을 추측으로 채웠다**
   정보가 부족하니 Opus는 quota pressure나 autonomous-agent 문제로 잘못 해석할 여지가 생겼다.

3. **불필요한 round-trip이 늘었다**
   처음부터 economics + pain + constraints가 있었다면 더 적은 token과 더 짧은 discussion으로 같은 challenge에 도달할 수 있었다.

4. **Premium reviewer cost를 고려해야 한다**
   Opus-5는 valuable하지만 비싸다. Whole history를 무작정 던지는 것도 낭비이고, 너무 압축해서 핵심 causal context를 잃는 것도 낭비다.

---

## Key Lessons 🔥

### 1. Review quality는 Context quality에 크게 좌우된다

> **Review quality ≈ Reviewer intelligence × Context quality**

똑똑한 reviewer에게도 context가 부족하면 좋은 challenge가 엉뚱한 문제를 향할 수 있다.

### 2. Peer Review는 결론보다 assumption을 challenge한다

좋은 Council의 목표는 "SOL안 승인 받기"가 아니다.

Reviewer가 물어야 할 것은:

- 이 problem이 실제 problem인가?
- 이 constraint가 진짜인가?
- 이 alternative를 왜 버렸는가?
- economics가 바뀌면 decision도 바뀌는가?

### 3. Context는 많다고 좋은 게 아니라 causal해야 한다

Premium model의 token을 아끼려면 whole conversation dump가 아니라 다음 흐름이 필요하다.

```text
History
  ↓
Observed Pain
  ↓
Economics / Constraints
  ↓
Current Architecture
  ↓
Rejected Alternatives
  ↓
Proposal + Why
  ↓
Open Uncertainties
```

즉 **결론을 많이 보내는 것이 아니라, 결론이 나온 원인 사슬을 보내는 것**이 중요하다.

### 4. Consensus는 목적이 아니다

Council success는 둘이 같은 말을 하는 것이 아니다.

```text
Challenge
  ↓
Context 보강
  ↓
Assumption 수정
  ↓
더 나은 Decision
```

필요하다면 dissent를 그대로 남기는 것이 fake consensus보다 낫다.

---

## Protocol Improvements

앞으로 Design Council을 열 때 Peer Reviewer에게 보내는 packet에는 최소한 아래가 들어간다.

- **History**: 어떻게 여기까지 왔는가
- **User Economics**: quota / cost / subscription이 decision에 어떤 영향을 주는가
- **Observed Pain**: 실제 사용 중 무엇이 불편했는가
- **Platform Constraints**: 현재 무엇이 불가능하거나 제한되는가
- **Current Architecture**: 이미 있는 것은 무엇인가
- **Rejected Alternatives**: 검토했지만 버린 것과 이유
- **Proposal + Why**: 현재 안과 그 이유
- **Open Uncertainties**: Reviewer가 집중해서 challenge할 부분

### Token-saving rule for Opus

- 전체 chat history를 그대로 복사하지 않는다.
- SOL이 먼저 **compact review capsule**을 만든다.
- 단, economics / pain / rejected alternatives를 과도하게 잘라내지 않는다.
- Opus에게는 "새 설계 전체 작성"보다 **assumption challenge + alternative check**를 우선 요청한다.
- Round 2는 Round 1 전체를 반복하지 말고 **새 context + changed decision + remaining disagreement**만 전달한다.

---

## Outcome

**Architecture**: ✅ Validated
**API Design**: ✅ Improved (`background=True`)
**Council Pattern**: ✅ Useful
**Context Packet**: ⚠️ 반드시 개선 필요
**Implementation**: 🔄 Ready to proceed

이번 실험의 가장 큰 수확은 단순히 API naming 하나가 아니다.

> **User + SOL + Opus가 서로 다른 역할을 유지하면서 실제 decision을 진화시킬 수 있다는 것을 확인했다.**

- User: domain reality / economics / final direction
- SOL: Primary Engineer / integration / main reasoning
- Opus: independent Peer Reviewer / challenger

이 역할 분리가 잘 지켜졌을 때 Council이 가장 productive했다.

---

## Council Session Log Template

```markdown
## YYYY-MM-DD — [Council Topic]

### Participants
- **Primary Engineer / Proposer**:
- **Peer Reviewer**:
- **User / Domain Owner**:

### Context Packet
- History:
- Observed Pain:
- Economics / Constraints:
- Current Architecture:
- Rejected Alternatives:
- Proposal + Why:
- Open Uncertainties:

### Round 1 Challenge

### Context Added

### Changed Positions

### Remaining Dissent

### Final Decision

### What Improved Because of the Council

### Protocol Lesson
```

---

## 2026-08-10 — Plan Review Loop Lesson

Architecture가 수렴한 뒤에도 작은 review loop가 한 번 더 유효했다.

```text
Opus plan skeleton
      ↓
SOL live-code verification
      ↓
implementation boundary correction
      ↓
Opus compact re-validation
      ↓
Ready for Implementation
```

### 새로 확인한 역할 분담

- **Opus**: architecture challenge, alternative check, plan skeleton
- **SOL**: live repo inspection, local implementation truth, integration 판단
- **User**: economics / operational reality / final steering

비싼 Peer Reviewer에게 repo 전체를 반복해서 읽히는 것보다, SOL이 local truth를 확인하고 **결정에 영향을 주는 correction만 compact하게 전달**하는 편이 효율적이었다.

### Assumption Rule

Peer Reviewer가 live code를 직접 확인하지 않은 implementation detail은 확정 사실처럼 쓰지 않는다.

> **확인하지 않은 detail은 `assumption` 또는 `SOL live-check item`으로 표시한다.**

이번 사례에서 `registry snapshot`은 live inspection 후 `worker-side registry rebuild`로 수정됐다.

### Communication Header

Council relay에서 sender 혼동을 막기 위해 SOL → Opus 전달문은 항상 다음 header로 시작한다.

```markdown
# Sol -> Opus
```

### Final Verdict

- **Design Council pattern**: ✅ 성공
- **Architecture**: ✅ Converged
- **Implementation Plan**: ✅ Peer re-validated
- **Remaining disagreement**: 없음
- **Next**: 새 SOL session에서 implementation
