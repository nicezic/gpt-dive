---
title: ADR - Runtime Terminology and Naming
created: 2026-08-30
updated: 2026-08-31
type: decision
status: proposed
---

# ADR 0009 — Runtime Terminology and Naming

> ADR 0004~0008이 lifecycle/output/awareness/recovery 의미를 먼저 분리했다. 이 ADR은 **model-facing vocabulary를 하나씩만 남기고 충돌하는 이름을 제거**한다.

## 결정 요약

| 개념 | Canonical term |
|---|---|
| durable runtime object | `Execution` |
| transient OS implementation | `Worker` |
| published awareness object | `Task` |
| public identity | `execution_id` |
| lifecycle | `state` / `reason` |
| response-delivery 선택 | `delivery` |
| response discriminator | `outcome` |
| final Monty value | `output` |
| public error category | `error_code` |
| Monty print/progress | `console` |
| subprocess streams | `stdout` / `stderr` |
| generic rediscovery concept | `Task awareness` |
| automatic awareness projection / field | `TrackedTasks` / `tracked_tasks` |

핵심 public contract:

```json
{"outcome":"completed","execution_id":"abc123","output":42,"tracked_tasks":[]}
```

```json
{"outcome":"task","execution_id":"abc123","state":"running","tracked_tasks":[{"execution_id":"abc123","label":"build project","state":"running","reason":null,"elapsed_seconds":261}]}
```

```json
{
  "outcome":"error",
  "execution_id":"abc123",
  "error_code":"execution_error",
  "message":"Code Mode Execution failed.",
  "tracked_tasks":[]
}
```

ADR 0006에 따라 `tracked_tasks`는 primary outcome 종류와 무관하게 ordinary model-visible result에 항상 존재하는 cross-cutting awareness field다.

Input:

```text
code_mode(..., delivery="auto" | "task")
```

즉 clean replacement:

```text
kind → outcome
mode → delivery
error code → error_code
```

## 왜 필요한가

현재 같은 단어가 여러 의미를 가진다.

```text
code
├─ code_mode input source
└─ error category

mode
└─ 실제 execution mode처럼 들리지만 의미는 delivery 선택

result
├─ SDK wrapper
├─ generic local variable
└─ program result prose

stdout
├─ subprocess stdout
└─ 과거 Monty print capture

status
└─ lifecycle state와 혼용 가능
```

Naming 원칙은 단순하다.

1. 한 개념에 한 canonical word.
2. 다른 개념에는 다른 word.
3. LLM이 schema만 보고 역할을 추론할 수 있게 한다.
4. 멀쩡한 이름까지 mechanical rename하지 않는다.

## Domain nouns

### `Execution` / `Worker` / `Task` — 유지

- Execution: accepted Code Mode run의 durable identity/lifecycle record.
- Worker: Execution을 수행하는 transient process/unit. Public identity 아님.
- Task: publish된 Execution의 awareness object. 모든 Execution의 동의어 아님.

`Job`, `Run`, `Process`를 새 domain alias로 만들지 않는다.

### `TrackedTasks` / `tracked_tasks` — 유지

ADR 0006의 automatic rediscovery contract를 가리키는 canonical vocabulary로 유지한다.

```text
generic concept      → Task awareness
automatic projection → TrackedTasks
public field         → tracked_tasks
explicit inspection → task(list)
```

`Task awareness`는 넓은 개념이고 `TrackedTasks`는 ordinary tool result에 자동으로 실리는 bounded passive projection이다. `task(list)`는 같은 SQLite Task authority를 명시적으로 자세히 검사하는 surface이지 TrackedTasks와 동일한 compact representation도, 이를 대체하는 polling mechanism도 아니다.

## Public fields

### `execution_id` — 유지

`id`, `task_id`, `job_id`, `run_id` alias를 만들지 않는다.

### `state` — lifecycle 전용

```text
accepted / running / completed / failed / cancelled / lost
```

`status` public alias를 만들지 않는다.

### `reason` — lifecycle terminal reason

`deadline_exceeded`, `launch_interrupted`, `retention_expired` 같은 reason을 표현한다. Public tool error category와 다르다.

### `delivery` — `mode` 대체

ADR 0004에서 `auto`/`task` 차이는 Execution 종류가 아니라 **response delivery / Task publication timing**이다.

```text
delivery="auto"
→ bounded inline wait, 필요 시 Task publish

delivery="task"
→ immediate Task publish
```

### `outcome` — `kind` 대체

`kind`는 discriminator 기능은 하지만 domain meaning이 약하다.

`outcome`은 "이번 call이 caller에게 어떤 형태로 전달됐는가"를 직접 표현한다.

Canonical values:

```text
completed | task | error
```

### `output` — 유지

Final Monty expression 전용이다. Public program-value field를 `result`, `data`, `value`로 다시 늘리지 않는다.

### `error_code` — error `code` 대체

같은 tool에서 input `code`는 Monty source다. Error category까지 `code`라고 부르지 않는다.

### `message` / `label` — 유지

- `message`: 짧은 public error explanation.
- `label`: awareness에서 Execution을 구분하는 짧은 description.

## Stream/output vocabulary

```text
print()            → console
run_command.stdout → subprocess stdout
run_command.stderr → subprocess stderr
final expression   → output
```

Monty `print()`를 `stdout`이라고 부르지 않는다.

## `result` / `status` 사용 규칙

`result`라는 Python local variable까지 전역 rename하지 않는다. Public/domain prose에서는 더 정확한 단어를 쓴다.

```text
program value      → output
response branch    → outcome
lifecycle          → state
retained raw bytes → artifact / evidence
```

`status`는 일반 prose에서는 쓸 수 있지만 public lifecycle field는 `state` 하나다.

## ADR 관계

- ADR 0005 semantics는 유지하고 `kind`, input `mode`, error `code` naming만 이 ADR이 supersede한다.
- ADR 0006은 `TrackedTasks` / `tracked_tasks`를 automatic awareness vocabulary로 유지하고, `task(list)`는 explicit inspection surface로 둔다.
- ADR 0008에서는 `output` / `artifact` / `evidence` / `stdout`을 구분한다.

## 폐기한 대안

| 후보 | 폐기 이유 |
|---|---|
| `kind` 유지 | domain meaning 약함; naming ADR 목적과 맞지 않음 |
| `status` discriminator | lifecycle `state`와 충돌, `task`는 status가 아님 |
| `type` | 너무 generic |
| `variant` | type-system jargon |
| `result_type` | 과부하된 `result` 재도입 + 불필요하게 김 |
| `mode` 유지 | execution mode라는 잘못된 mental model 유도 |
| error `code` 유지 | input `code`와 충돌 |
| `id` 축약 | identity domain 재추론 필요 |
| `TrackedTasks`를 제거하고 `task(list)`만 사용 | automatic rediscovery 의미가 사라지고 polling-oriented mental model을 유도 |
| 모든 internal `result` 변수 rename | 가치 없는 diff 확대 |
| retained artifact filename 전면 rename | private layout migration 비용 대비 가치 낮음 |

## Clean-break 원칙

새 public schema에서 old/new alias를 동시에 지원하지 않는다.

```text
kind      → 제거
mode      → 제거
error code→ 제거
```

Naming implementation 뒤 advertised schema + live structured output을 다시 canary한다.

## 귀결

- 사용자가 싫어한 `kind`가 사라지고 `outcome`으로 의미가 명확해진다.
- `delivery`가 foreground/background execution 오해를 줄인다.
- Source `code`와 `error_code`가 분리된다.
- `state`, `output`, `console`, `stdout/stderr` 역할이 명확해진다.
- `TrackedTasks` / `tracked_tasks`가 automatic awareness projection이라는 의미를 유지한다.
- Private local naming까지 과도하게 건드리지 않는다.

## Non-goal

- Execution/Task/Worker domain 재설계
- lifecycle state value 변경
- output reduction semantics 변경
- retained artifact filename migration
- historical ADR 전면 rewrite
- generic repository style guide

## 구현 불변조건

- `execution_id`, `state`, `reason`, `output`, `message`, `label`은 유지한다.
- `kind → outcome`, `mode → delivery`, error `code → error_code`는 clean replace한다.
- old/new public aliases를 동시에 지원하지 않는다.
- Monty print는 `console`, process stream만 `stdout/stderr`로 부른다.
- ADR 0006 채택 후 current docs에서 `TrackedTasks`를 automatic awareness projection, `tracked_tasks`를 그 public field로 일관되게 사용한다.
- generic internal local variable rename을 목표로 하지 않는다.
- schema + live canary로 naming contract를 검증한다.

## 참고 문서

- `docs/runtime/CONTEXT.md`
- `docs/runtime/adr/0004-always-durable-code-mode-runtime.md`
- `docs/runtime/adr/0005-code-mode-output-contract.md`
- `docs/runtime/adr/0006-tracked-tasks-connector-projection.md`
- `docs/runtime/adr/0007-code-mode-bootstrap-model-guidance.md`
- `docs/runtime/adr/0008-raw-execution-evidence-recovery.md`
- `src/gpt_dive/app.py`
