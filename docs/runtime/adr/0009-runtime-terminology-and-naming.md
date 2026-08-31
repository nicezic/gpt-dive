---
title: ADR - Runtime Terminology and Naming
created: 2026-08-30
updated: 2026-08-31
type: decision
status: proposed
---

# ADR 0009 — Runtime Terminology and Naming

> ADR 0004~0008이 runtime semantics를 먼저 정의했다. 이 ADR은 그 의미를 바꾸지 않고 **model-facing naming에서 실제 혼동을 만드는 이름만 사용자와 확정**한다.

## 왜 필요한가

현재 schema/prose에서 같은 단어가 다른 의미로 보이거나, 이름만 보고 역할을 오해하기 쉬운 곳이 있다.

```text
mode
→ execution 종류처럼 들리지만 실제로는 response delivery 선택

kind
→ discriminator이지만 무엇의 kind인지 약함

code
├─ Monty source
└─ error category

stdout
→ subprocess stream과 Monty print/progress가 과거 혼용됨

result / status
→ 여러 층위에서 generic하게 재사용됨
```

목표는 repo 전체 rename이 아니다.

> **한 개념에는 한 이름, 다른 개념에는 다른 이름. Public/model-facing ambiguity만 줄인다.**

## 이 ADR이 바꾸지 않는 것

Semantics는 기존 ADR이 소유한다.

```text
Execution / Task / execution_id / state / reason → ADR 0004
output                                       → ADR 0005
TrackedTasks / tracked_tasks                 → ADR 0006
artifact / evidence recovery semantics       → ADR 0008
stdout / stderr                              → subprocess streams
```

`task(list)`와 TrackedTasks의 shape 차이, evidence 저장/조회 방식은 여기서 다시 결정하지 않는다.

## 같이 결정할 naming 후보

| 현재 | 후보 | 바꾸려는 이유 |
|---|---|---|
| `mode` | `delivery` ? | `auto/task`는 execution mode가 아니라 delivery/publication timing |
| `kind` | `outcome` ? | response branch라는 의미를 더 직접 표현 |
| error `code` | `error_code` ? | input source `code`와 충돌 제거 |
| Monty print/progress | `console` ? | subprocess `stdout`과 분리 |
| recovery capability | `execution_evidence` ? | ADR 0008의 evidence discovery 역할 표현 |

후보는 아직 결정이 아니다. 이름이 실제 schema와 모델 mental model을 더 명확하게 만드는지 CodeGraph/public surface를 보면서 확정한다.

## 사용자와 상의할 질문

1. `mode`는 실제로 혼동을 만들 만큼 나쁜가? 바꾼다면 `delivery`가 가장 좋은가?
2. `kind`는 유지해도 충분한가? 바꾼다면 `outcome`이 자연스러운가?
3. error category는 `error_code`로 분리하는 게 명확한가?
4. Monty print/progress에 별도 이름 `console`이 필요한가?
5. ADR 0008 recovery capability는 `execution_evidence`가 맞나? `execution_artifacts`, `execution_inspect` 등이 더 나은가?
6. 확정된 rename은 compatibility alias 없이 clean break로 적용할까?

## 적용 원칙 후보

이름을 바꾸기로 결정하면 기본 방향은:

```text
public/model-facing contract → clean replacement
old/new alias 동시 유지     → 하지 않음
private artifact filename    → 건드리지 않음
generic local variable       → 필요 없으면 건드리지 않음
semantic behavior            → 변경하지 않음
```

실제 blast radius는 CodeGraph + advertised MCP schema로 확인하고, 결정 뒤 `/to-spec` → `/to-tickets` → `/implement`로 넘긴다.

## Non-goal

- Execution / Task / Worker 재설계
- lifecycle/output/awareness/evidence behavior 변경
- retained artifact layout migration
- repository-wide mechanical rename
- historical ADR 전면 rewrite

## 참고

- `docs/runtime/adr/0004-always-durable-code-mode-runtime.md`
- `docs/runtime/adr/0005-code-mode-output-contract.md`
- `docs/runtime/adr/0006-tracked-tasks-connector-projection.md`
- `docs/runtime/adr/0008-raw-execution-evidence-recovery.md`
- `src/gpt_dive/app.py`
