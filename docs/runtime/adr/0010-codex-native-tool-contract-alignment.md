---
title: ADR - Codex-Native Tool Contract Alignment for Code Mode
created: 2026-08-31
updated: 2026-09-01
type: decision
status: accepted
---

# ADR 0010 — Codex-Native Tool Contract Alignment for Code Mode

## Goal

**GPT가 별도 guidance를 덜 받아도 `code_mode` capability를 첫 호출부터 정확히 사용하게 한다.**

Codex의 model-facing contract 구조를 가져오되 GPT Dive의 Monty/Python, local reduction, always-durable Execution semantics는 유지한다.

```text
현재
model이 code 작성
      ↓
code_mode 실행
      ↓
Monty 내부 CAPABILITIES 발견

문제: 첫 code 작성 시 name / args / return fields를 아직 모름
```

Codex는 nested tool의 name/description/input/output schema를 **code 작성 전에** model-facing declaration으로 제공한다. GPT Dive도 이 contract ordering을 따른다.

## Decision

### 1. 하나의 capability definition을 authority로 둔다

```text
CapabilityDefinition
├─ name + description
├─ callable
├─ parameters schema
├─ return schema
└─ rendered Python declaration
        │
        ├─ outer code_mode pre-call catalog
        ├─ Monty type-check stubs
        ├─ host argument/result validation
        └─ CAPABILITIES reflection
```

Exact signature/schema의 hand-written 복제본을 만들지 않는다.

### 2. typed declaration을 첫 호출 전에 보여 준다

Outer `code_mode` description에 enabled capability의 compact generated Python declarations를 넣는다.

```python
async def run_command(command: str) -> RunCommandResult: ...

class RunCommandResult(TypedDict):
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    truncated: bool
```

Renderer 형태는 구현 세부사항이다. **모델이 code를 쓰기 전에 exact name/args/return fields를 볼 수 있어야 한다**는 점만 invariant다.

### 3. structured return에서 열린 `dict[str, Any]` contract를 제거한다

Known return shape가 있는 capability는 typed schema를 가진다. Host boundary에서 arguments/results를 같은 schema authority로 검증하고 JSON-compatible value를 Monty에 전달한다.

우선 migration 대상은:

1. `run_command`
2. agent/model capabilities
3. `council_emit`

Unknown/freeform output이 실제 contract인 경우만 open shape로 남긴다.

### 4. Pydantic 계열 schema/rendering을 재사용한다

```text
Python callable + typed model
        ↓
Pydantic/Pydantic AI schema generation
        ↓
Python declaration renderer
```

Pydantic AI/Harness의 existing schema/`FunctionSignature` 계열 경로를 우선 재사용한다. 별도 JSON-Schema-to-Python generator나 hand-written schema table은 만들지 않는다.

Current upstream API가 달라지더라도 **single schema authority** invariant를 유지하는 가장 작은 구현을 택한다.

### 5. Python/Monty runtime semantics는 유지한다

```text
keep
├─ await run_command(...)
├─ direct capability globals
├─ local reduction
├─ asyncio.gather for independent work
└─ final expression = compact result

not copied from Codex
├─ V8 / JavaScript
├─ literal tools.* namespace
├─ exec/wait cell lifecycle
└─ deferred tool-loading machinery
```

모든 capability를 keyword-only로 강제하지 않는다. Exact generated declaration이 보이면 자연스러운 Python signature를 유지하고, capability 의미상 필요할 때만 keyword-only를 쓴다.

### 6. `CAPABILITIES`는 runtime reflection/fallback이 된다

ADR 0007의 “live `CAPABILITIES`가 exact inner authority”는 첫 호출에는 한 단계 늦다. 이 ADR이 그 부분을 좁게 amend한다.

```text
single capability definition
        ├─ pre-call catalog → first-call authority
        ├─ Monty stubs      → static enforcement
        ├─ host validation  → runtime enforcement
        └─ CAPABILITIES     → reflection / fallback discovery
```

`CAPABILITIES`를 제거하지 않지만 correctness가 discovery-only 호출에 의존하지 않게 한다.

## Rollout

전체 migration을 한 번에 하지 않는다. 첫 검증 단위는 **`run_command`**다.

확인할 것은 다음뿐이다.

- 첫 `code_mode` 호출 성공률
- 잘못된 capability name/argument/return field
- `CAPABILITIES` discovery-only 호출 수
- typing/validation retry
- 필요한 field만 local reduction하는 비율
- generated catalog token 비용

효과가 확인되면 나머지 structured capabilities로 확장한다. Eval 실패를 보상하기 위한 fallback machinery는 추가하지 않는다.

## Consequences

- 첫 code 작성 전에 capability contract를 알 수 있다.
- pre-call catalog, static checker, host validation, reflection이 같은 definition에서 파생된다.
- return-field 추측과 stale signature guidance가 줄어든다.
- bootstrap/reminder는 exact signature cache보다 workflow와 mental model에 집중할 수 있다.
- durable Execution/Task/output semantics는 바뀌지 않는다.

## Non-goal

- V8/JavaScript 또는 Codex cell lifecycle 도입
- always-durable Execution / Task lifecycle 변경
- output/awareness/evidence semantics 재설계
- arbitrary capability result 자동 pruning
- prompt guidance만 늘려 contract ambiguity를 보상
- historical ADR 전면 rewrite

## Evidence

상세 source 조사와 pinned commit/line evidence는 `docs/runtime/research/codex-native-tool-contract-alignment.md`가 소유한다.

Current upstream anchors:

- [Codex Code Mode tool conversion](https://github.com/openai/codex/blob/main/codex-rs/tools/src/code_mode.rs)
- [Codex Code Mode protocol](https://github.com/openai/codex/blob/main/codex-rs/code-mode-protocol/src/grpc/codex.code_mode.v1.proto)
- [Codex tool models](https://github.com/openai/codex/blob/main/codex-rs/tools/src/tool_spec.rs)

Local implementation anchors:

- `docs/runtime/adr/0007-code-mode-bootstrap-model-guidance.md`
- `src/gpt_dive/code_runtime.py`
- `src/gpt_dive/code_capabilities.py`
- `src/gpt_dive/app.py`
