---
title: ADR - Automatic TrackedTasks Projection
created: 2026-08-30
updated: 2026-08-31
type: decision
status: proposed
---

# ADR 0006 — Automatic TrackedTasks Projection

> ADR 0004가 Execution/Task lifecycle을, ADR 0005가 program output을 소유한다. 이 ADR은 **ChatGPT Web이 background Task completion을 ordinary tool activity 중 자동으로 다시 발견하는 awareness projection**만 결정한다.

## 결정 요약

**TrackedTasks의 목적은 AI가 polling을 기억하지 않아도 ordinary tool activity 중 background completion을 자동 재발견하게 만드는 것이다.**

따라서 모든 정상적인 model-visible GPT Dive tool result는 primary result를 보존하면서 현재 TrackedTasks snapshot을 top-level `tracked_tasks` field로 함께 노출한다.

```text
ordinary tool call
       ↓
primary result
+ tracked_tasks: [...]
       ↓
Web SOL은 자기 일을 계속함
       ↓
next ordinary tool call
       ↓
primary result
+ tracked_tasks: [... updated state ...]
       ↓
running → completed 자동 재발견
```

Task가 하나도 없어도 field는 생략하지 않는다.

```json
{
  "tracked_tasks": []
}
```

핵심은 **automatic awareness, not remembered polling**이다.

## 왜 필요한가

Background work를 시작한 뒤 Web SOL이 `task(list)` 호출을 기억해야만 완료를 알 수 있다면, completion awareness는 모델의 기억과 polling discipline에 의존한다.

원래 accepted Conduit ADR 0002의 목적은 반대였다.

```text
launch background work
        ↓
do not wait
        ↓
continue ordinary work
        ↓
later ordinary tool result carries refreshed TrackedTasks
        ↓
completion noticed opportunistically
```

이를 Opportunistic Evidence Pickup(OEP)으로 사용하면 background latency를 foreground critical path에서 제거하면서도 완료된 일을 잊지 않는다.

## 관찰된 문제: 설계가 아니라 carrier가 실패했다

기존 server middleware는 ordinary `CallToolResult.content[]`에 TrackedTasks `TextContent`를 additive하게 append했다.

```text
CallToolResult
├─ structuredContent: primary result
└─ content[]
   └─ TrackedTasks TextContent
```

Server-side test에서는 append가 확인됐다. 그러나 2026-08-31 live ChatGPT connector canary에서는 Task publication 뒤 projection state가 실제로 변했는데도 appended awareness가 model-visible output에 나타나지 않았다.

이 관찰이 의미하는 것은 다음 하나다.

```text
automatic TrackedTasks design failure   ❌
content[] carrier is not visible here   ✅
```

따라서 automatic awareness를 제거하거나 `task(list)` polling으로 대체하지 않는다. **ChatGPT model-visible structured output에서 실제로 보이는 carrier로 projection을 복구한다.**

## 결정

### 1. `tracked_tasks`는 ordinary result의 항상-present additive metadata다

정상적인 model-visible tool result는 자신의 primary fields를 그대로 유지하고, sibling field로 `tracked_tasks`를 추가한다.

Code Mode 예시:

```json
{
  "kind": "completed",
  "execution_id": "abc123",
  "output": {
    "answer": 42
  },
  "tracked_tasks": [
    {
      "execution_id": "xyz789",
      "label": "long test",
      "state": "running",
      "reason": null,
      "elapsed_seconds": 261
    }
  ]
}
```

`tracked_tasks`는 final Monty `output` 내부에 넣지 않는다.

```text
output         → 이번 프로그램이 선택한 결과
tracked_tasks  → outstanding background work awareness
```

둘은 같은 response에서 공존하지만 semantic ownership은 분리된다.

### 2. Primary result wrapper를 다시 만들지 않는다

다음 shape는 사용하지 않는다.

```json
{
  "result": {
    "kind": "completed",
    "execution_id": "abc123",
    "output": 42
  },
  "tracked_tasks": []
}
```

ADR 0005가 제거한 의미 없는 `result` wrapper를 awareness 때문에 되살리지 않는다. Primary result object 자체에 `tracked_tasks`가 sibling field로 존재해야 한다.

### 3. Projection authority는 기존 SQLite 하나다

TrackedTasks는 publish됐고 아직 dismiss되지 않은 Task의 compact projection이다.

```text
SQLite Execution / Task state
        ↓
current published + undismissed Tasks
        ↓
bounded TrackedTasks projection
        ↓
tracked_tasks field
```

별도 Task store나 awareness database를 만들지 않는다.

### 4. TrackedTasks snapshot은 compact하되 elapsed를 유지한다

Automatic TrackedTasks는 passive awareness에 필요한 정보만 싣되, 기존 awareness 계약의 **elapsed 표시를 보존**한다.

Canonical structured item:

```json
{
  "execution_id": "abc123",
  "label": "build project",
  "state": "running",
  "reason": null,
  "elapsed_seconds": 261
}
```

| Field | 의미 |
|---|---|
| `execution_id` | get/cancel/dismiss handle |
| `label` | 여러 Task 구분 |
| `state` | current Execution state |
| `reason` | terminal reason; 정상 상태는 null |
| `elapsed_seconds` | read/render 시 계산되는 경과 시간; passive awareness에서 유지 |

사람이 읽는 TrackedTasks render에서는 `elapsed_seconds`를 `4:21` 또는 `1:04:21`처럼 compact하게 표시할 수 있다. Elapsed는 lifecycle authority가 아니며 read/render 시 파생되는 display 정보다.

`accepted_at`, `finished_at`, `published_at`, `updated_at`, backend, pid 같은 상세/진단 metadata는 automatic TrackedTasks에서 제외한다.

Snapshot은 server-owned hard limit과 deterministic ordering을 사용한다. Exact numeric limit은 tuning detail이며 API semantic으로 고정하지 않는다.

### 5. 모든 ordinary return에서 현재 snapshot을 노출한다

ADR 0004의 기존 "보이는 내용이 변했을 때만 emit하고 변화 없으면 생략" 규칙은 이 ADR이 awareness delivery에 한해 supersede한다.

Projection 계산이나 캐시는 내부적으로 최적화할 수 있지만 model-visible contract에서는 field를 생략하지 않는다.

```text
no Tasks      → tracked_tasks: []
unchanged     → same tracked_tasks snapshot
state changed → refreshed tracked_tasks snapshot
```

이 always-present contract가 있어야 Web SOL이 이전 response나 revision을 기억하지 않고 현재 awareness를 매 ordinary call에서 읽을 수 있다.

### 6. `task(list)`는 detailed inspection이며 polling requirement가 아니다

Top-level Task lifecycle 의미는 유지한다.

```text
ordinary tool result → automatic TrackedTasks awareness ⭐
task(list)           → detailed structured Task inspection
task(get)            → selected Execution status/result pickup, 비파괴
task(cancel)         → explicit cancellation
task(dismiss)        → terminal awareness 제거
```

`task(list)`는 automatic TrackedTasks와 **같은 compact field set을 공유하지 않는다**. 기존 explicit inspection 계약대로 complete structured Task objects를 반환하며, 현재 TaskView가 제공하는 lifecycle/display fields를 유지한다.

```text
execution_id
label
state
reason
accepted_at
finished_at
published_at
updated_at
elapsed_seconds
```

즉 두 surface가 공유하는 것은 SQLite Task authority와 lifecycle 의미이지 public representation 전체가 아니다. Automatic TrackedTasks는 passive awareness를 위해 bounded/compact하고, `task(list)`는 사용자가 명시적으로 요청한 상세 inspection이므로 더 많은 정보를 제공한다.

`task(list)`는 디버깅, 재확인, 사용자의 명시적 요청처럼 Task를 자세히 보고 싶을 때 유용하다. Background completion을 놓치지 않기 위해 모델이 주기적으로 호출해야 하는 polling loop가 아니다.

Result를 읽었다고 자동 dismiss하지 않는다. Terminal Task는 명시적 dismiss 전까지 automatic snapshot에 남는다.

### 7. Carrier는 live connector에서 검증한다

기존 additive `content[]` TextContent는 현재 ChatGPT connector에서 model-visible contract로 신뢰할 수 없다.

구현은 특정 middleware/Pydantic helper를 고정하지 않고 다음 결과를 만족해야 한다.

```text
advertised tool schema
        +
live structured/model-visible output
        ↓
primary result fields + tracked_tasks field
```

즉 server 내부 unit test만으로 완료 처리하지 않는다. 실제 ChatGPT Web canary에서 다음 ordinary call이 `tracked_tasks`를 노출하고, background Task의 `running → completed` 변화가 자동으로 보이는지 검증한다.

### 8. Transport 자체가 실패하면 refresh를 보장할 수 없다

MCP/connector transport failure로 model-visible result 자체가 돌아오지 않으면 TrackedTasks도 전달할 수 없다.

반대로 정상적인 model-visible tool result가 반환되는 경로에서는 empty/unchanged 여부와 관계없이 `tracked_tasks` field를 유지한다.

## 기존 ADR과의 관계

- ADR 0004: SQLite authority, Task publication/dismissal, single `execution_id`는 유지한다. Section 11의 changed-only model-visible emission 규칙만 이 ADR이 supersede한다.
- ADR 0005: program `output` 의미와 minimal outcome fields는 유지한다. `tracked_tasks`는 output 내부가 아니라 cross-cutting awareness sibling metadata다.
- Conduit ADR 0002: ordinary tool activity가 TrackedTasks refresh opportunity가 된다는 accepted OEP 방향을 유지하고 Runtime contract로 구체화한다.
- ADR 0007: 모델은 automatic `tracked_tasks`를 읽고 terminal work를 처리하는 방법을 배운다. polling cadence를 기억하게 만들지 않는다.
- ADR 0009: `TrackedTasks` / `tracked_tasks` naming을 current terminology로 유지할지 최종 정리한다.

## 폐기한 대안

| 대안 | 폐기 이유 |
|---|---|
| `task(list)`를 canonical polling path로 사용 | AI가 polling을 기억해야 하므로 TrackedTasks의 원래 목적 상실 |
| `task(list)`와 TrackedTasks를 같은 compact field set으로 통일 | explicit inspection의 상세 정보와 passive awareness의 elapsed 표시를 동시에 훼손 |
| additive `content[]` TextContent를 그대로 신뢰 | 현재 live ChatGPT model-visible surface에서 관찰되지 않음 |
| `{result, tracked_tasks}` wrapper | ADR 0005가 제거한 불필요한 outer wrapper 부활 |
| 변화가 있을 때만 field emit | caller가 omission 의미와 이전 snapshot을 기억해야 하며 always-present awareness가 깨짐 |
| `_meta`에만 저장 | model-visible awareness 보장 없음 |
| 새 `tracked_tasks` MCP tool 추가 | `task(list)`와 중복되고 automatic discovery를 해결하지 못함 |
| server push/event subsystem | 현재 connector reality 대비 과설계 |
| 모든 Execution을 Task로 publish | ADR 0004의 Task 의미 훼손 |

## 귀결

- Web SOL은 background Task를 시작한 뒤 별도 polling loop 없이 자기 일을 계속할 수 있다.
- 다음 ordinary tool activity가 자연스러운 completion rediscovery point가 된다.
- Primary tool result와 Task awareness는 같은 response에서 보이지만 의미적으로 섞이지 않는다.
- `tracked_tasks: []`까지 항상 존재하므로 omission semantics와 revision 기억이 필요 없다.
- Terminal Task는 dismiss 전까지 반복 노출되어 한 번의 missed response가 결과 유실을 만들지 않는다.
- `task(list)`는 detailed inspection surface로 남고 complete structured Task 정보를 유지하지만 정상 workflow의 polling 의무가 아니다.
- Automatic TrackedTasks는 compactness를 유지하면서 기존 elapsed 표시 의미를 보존한다.

## Non-goal

- native MCP Tasks negotiation / push notification
- complete execution transcript
- raw artifact recovery — ADR 0008
- naming cleanup — ADR 0009
- automatic result pickup or automatic dismissal
- 모든 Execution을 Task로 publish

## 구현 불변조건

- **AI가 polling을 기억하지 않아도 ordinary tool activity 중 background completion을 자동 재발견할 수 있어야 한다.**
- 정상적인 model-visible ordinary tool result에는 `tracked_tasks` field가 항상 존재한다. Task가 없으면 `[]`다.
- `tracked_tasks`는 primary program `output` 내부가 아니라 top-level sibling metadata다.
- awareness 때문에 `{result, tracked_tasks}` 같은 outer result wrapper를 만들지 않는다.
- Task awareness authority는 기존 SQLite 하나다.
- snapshot은 published + undismissed Task의 bounded compact deterministic projection이며 passive awareness용 `elapsed_seconds`를 유지한다.
- automatic TrackedTasks와 `task(list)`는 같은 SQLite authority를 사용하지만 같은 public field set으로 강제하지 않는다.
- `task(list)`는 complete structured Task inspection 계약과 detailed TaskView fields를 유지한다.
- terminal Task는 explicit dismiss 전까지 snapshot에 남는다.
- `task(get)`은 비파괴이며 `task(dismiss)`만 awareness를 제거한다.
- `task(list)` polling을 정상 completion-discovery requirement로 만들지 않는다.
- 기존 `content[]` carrier 실패를 automatic awareness 설계 폐기의 근거로 사용하지 않는다.
- advertised schema와 live ChatGPT structured/model-visible output 양쪽에서 `tracked_tasks`를 canary 검증한다.

## 참고 문서

- `docs/runtime/adr/0004-always-durable-code-mode-runtime.md`
- `docs/runtime/adr/0005-code-mode-output-contract.md`
- `docs/conduit/adr/0002-trackedtasks-refresh-and-opportunistic-evidence-pickup.md`
- `docs/runtime/CONTEXT.md`
- `docs/runtime/adr/source-adr-0005-root-cause.md`
- `src/gpt_dive/app.py`
- `tests/test_task_projection.py`, `tests/test_surface.py`
