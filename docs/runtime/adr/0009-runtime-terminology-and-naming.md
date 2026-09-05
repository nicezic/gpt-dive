---
title: ADR - Runtime Terminology and Naming
created: 2026-08-30
updated: 2026-09-06
type: decision
status: accepted
---

# ADR 0009 — Runtime Terminology and Naming

> ADR 0004~0008이 runtime semantics를 소유한다. 이 ADR은 의미를 바꾸지 않고 **public/model-facing 이름만 정리**한다. Codex 근거는 ADR 0010을 따른다.

## Decision

| 현재 | 결정 | 이유 |
|---|---|---|
| `mode` | **`delivery`** | `auto/task`는 Execution 종류가 아니라 결과 전달/Task publication 선택이다. |
| `kind` | **`status`로 전환** | `completed`(상태)/`error`(상태)와 `task`(도구/명사)가 뒤섞인 카테고리 오류를 해결하고 실행 상태로 일원화 (`completed` / `running` / `failed`). |
| `output` | **`result`** | Monty의 최종 평가 표현식이자 성공 결과를 의미하는 canonical result vocabulary. |
| error `code` | **`error` 객체로 일원화** | `error: {code, message, detail}`로 계층화하여 top-level namespace 충돌을 방지하고 실패 원인과 디버그 증거를 함께 제공. |
| Monty print/progress | **`console`** | subprocess `stdout`/`stderr`와 분리하는 canonical term으로 쓴다. 새 output field를 뜻하지 않는다. |
| future recovery capability | **`run_command_evidence`** | ADR 0008의 범위는 Execution 전체가 아니라 각 `run_command`의 bounded stdout/stderr다. |

## Public contract

```python
code_mode(..., delivery="auto" | "task")
```

```text
delivery="auto"
├─ inline wait 안에 완료 → status="completed", result 직접 전달
└─ 아직 실행 중          → status="running", guidance 제공 및 세션 Task 등록

delivery="task"
└─ 즉시 status="running" 및 세션 Task 등록
```

Output vocabulary는 다음처럼 통일한다.

```text
completed = { status: "completed", execution_id, result }
running   = { status: "running",   execution_id, state, elapsed_seconds, guidance }
failed    = { status: "failed",    execution_id, error: { code, message, detail }, guidance }
```

Output 용어 경계:

```text
console        → Monty print/progress
stdout/stderr  → run_command subprocess streams
result         → final durable program result
```

`run_command_evidence`의 exact schema는 ADR 0008 구현 시 정한다. 이름 때문에 arbitrary capability result나 complete Execution transcript까지 포함시키지 않는다.

## Migration

Public/model-facing rename은 **clean break**로 적용한다.

- old/new alias를 병행하지 않는다.
- lifecycle/output/evidence semantics는 바꾸지 않는다.
- internal local variable은 public ambiguity가 아니면 건드리지 않는다.
- schema, tests, Wiki/bootstrap/reminder의 advertised contract를 같은 변경에서 맞춘다.

## Codex alignment

2026-09-01 current Codex source는 다음 구분을 사용한다.

- 전달 위치/방식에는 `delivery` vocabulary가 존재한다.
- Code Mode `ToolDefinition.kind`와 `ExecutionOutcome.outcome`은 서로 다른 역할이다.
- structured/tool error에서 `error_code` vocabulary를 사용한다.

따라서 Codex alignment는 이름을 표면적으로 복사하는 것이 아니라 **같은 의미는 일관되게, 다른 의미는 분리해서 명명**하는 방향으로 적용한다.

## Non-goal

- Execution / Task / Worker 재설계
- `auto/task` behavior 변경
- console을 새 durable result channel로 추가
- repository-wide mechanical rename
- historical ADR 전면 rewrite

## References

- `docs/runtime/CONTEXT.md` — delivery, Execution, Task publication의 canonical language.
- `docs/runtime/adr/0005-code-mode-output-contract.md` — output/console/subprocess stream 경계.
- `docs/runtime/adr/0008-raw-execution-evidence-recovery.md` — recovery evidence 범위.
- `docs/runtime/adr/0010-codex-native-tool-contract-alignment.md` — Codex-native contract 근거.
- [Codex Code Mode protocol](https://github.com/openai/codex/blob/main/codex-rs/code-mode-protocol/src/grpc/codex.code_mode.v1.proto)
- [Codex app-server protocol](https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md)
