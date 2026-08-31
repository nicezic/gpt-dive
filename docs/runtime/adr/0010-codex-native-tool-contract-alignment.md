---
title: ADR - Codex-Native Tool Contract Alignment for Code Mode
created: 2026-08-31
type: decision
status: proposed
---

# ADR 0010 — Codex-Native Tool Contract Alignment for Code Mode

## 최종 목표

**GPT가 본인이 학습되고 실제 Codex에서 사용하는 tool/code-mode 스타일에 최대한 자연스럽게 `~/gpt-dive`의 `code_mode`를 사용하게 한다.**

이를 위해 먼저 OpenAI Codex가 실제 모델에게 제공하는 tool stub, schema, Code Mode tool definition과 runtime contract를 소스에서 확인한다. 그 뒤 GPT Dive의 Pydantic/Monty `CAPABILITIES`와 1:1로 비교하고, 모델이 별도 guidance를 덜 받아도 올바른 tool call과 local reduction 코드를 생성하는 데 가치가 있는 부분만 반영한다.

```text
OpenAI Codex의 실제 model-facing contract
        ↓
tool stub / description / input_schema / output_schema
        ↓
GPT Dive CAPABILITIES와 1:1 비교
        ↓
Pydantic + Monty로 적합한 contract 표현
        ↓
GPT가 익숙한 방식으로 code_mode 사용
```

목표는 Codex 구현을 그대로 복제하는 것이 아니다. **모델이 이미 익숙한 contract와 idiom을 우선 조사하고, GPT Dive의 durable execution·local reduction 경계를 유지하면서 가능한 부분을 정렬한다.**

## 우선 조사할 것

1. Codex의 canonical `ToolSpec`과 Responses API용 tool representation.
2. 일반 tool이 Code Mode용 definition으로 변환될 때의 `name`, `description`, `input_schema`, `output_schema`와 실행 예시.
3. Codex Code Mode runtime이 nested tool을 모델에게 어떤 callable/stub 형태로 노출하는지.
4. GPT Dive의 현재 `CAPABILITIES` signature/return metadata와 비교했을 때 모델이 추측해야 하는 부분.
5. `dict[str, Any]` 같은 열린 output을 typed Pydantic result / strict schema로 좁히는 것이 실제로 유리한지.
6. 이 정렬로 bootstrap/reminder/ERROR_CASE 같은 guidance 부담을 실제로 줄일 수 있는지.

## 기존 ADR과의 관계

이 ADR은 기존 결정을 자동으로 폐기하지 않는다. Codex source 조사와 GPT Dive 1:1 diff를 먼저 만든 뒤, 근거가 있는 ADR만 명시적으로 amend 또는 supersede한다.

우선 재점검 대상은 ADR 0004~0009와 `TODO-durable-agy-worker-mcp-surface.md`다. 특히 model-facing naming을 다루는 ADR 0009는 Codex의 실제 vocabulary와 contract를 확인한 뒤 최종 확정한다.

## 주요 레퍼런스

### 실제 Codex 동작 기준

- [OpenAI Codex — `codex-rs/tools/src/tool_spec.rs`](https://github.com/openai/codex/blob/main/codex-rs/tools/src/tool_spec.rs)
  - Responses API로 전달되는 Codex tool representation의 기준.
- [OpenAI Codex — `codex-rs/tools/src/code_mode.rs`](https://github.com/openai/codex/blob/main/codex-rs/tools/src/code_mode.rs)
  - 일반 tool을 Code Mode용 definition으로 변환하고 `input_schema` / `output_schema`와 code-mode-specific description을 구성하는 경계.
- [OpenAI Codex — `codex-rs/code-mode`](https://github.com/openai/codex/tree/main/codex-rs/code-mode)
  - Code Mode tool definition과 모델용 callable 표현 조사 대상.
- [OpenAI Codex — `codex-rs/code-mode-runtime`](https://github.com/openai/codex/tree/main/codex-rs/code-mode-runtime)
  - 실제 Code Mode 실행 경계 조사 대상.

### 구현 참고

- [OpenAI Agents SDK — Function schema](https://openai.github.io/openai-agents-python/ref/function_schema/)
  - Python signature + Pydantic model에서 strict JSON Schema를 만드는 구현 참고. Codex 자체 runtime의 authority는 아니다.
- [Pydantic AI](https://github.com/pydantic/pydantic-ai)
  - Python typed tool/schema와 structured validation 참고.
- [Pydantic AI Harness](https://github.com/pydantic/pydantic-ai-harness)
  - Code Mode와 model-context/tool-output 관리 참고.
- [Pydantic Monty](https://github.com/pydantic/monty)
  - GPT Dive Code Mode가 사용하는 sandbox/runtime 계층의 upstream 참고.

### GPT Dive local authority

- `docs/runtime/adr/0004-always-durable-code-mode-runtime.md`
- `docs/runtime/adr/0005-code-mode-output-contract.md`
- `docs/runtime/adr/0007-code-mode-bootstrap-model-guidance.md`
- `docs/pydantic/code-mode.md`
- `src/gpt_dive/code_capabilities.py`
