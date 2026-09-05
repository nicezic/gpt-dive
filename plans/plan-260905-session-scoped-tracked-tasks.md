# Plan 260905 — Session-scoped TrackedTasks via MCP connection state

## Goal

`tracked_tasks`를 현재 ChatGPT ↔ GPT Dive MCP connection에서 publish된 Task에만 한정한다.

새 계약:

- foreground에서 끝난 Execution은 session state에 등록하지 않는다.
- 실제로 Task가 publish된 뒤에만 해당 `execution_id`를 MCP connection state에 기록한다.
- automatic `tracked_tasks`는 SQLite의 published + undismissed Task 중 현재 connection state가 기억한 ID만 보여준다.
- 현재 세션에 보일 Task가 하나도 없으면 `tracked_tasks` field 자체를 생략한다.
- 다른 MCP connection/session이 만든 Task는 automatic `tracked_tasks`에 절대 섞이지 않는다.
- SQLite는 계속 Execution/Task lifecycle의 유일한 SSOT다.
- MCP state는 lifecycle 복제본이 아니라 session-local visibility membership만 가진다.
- `task(get/cancel/dismiss)` authorization 정책은 이번 변경 범위에 포함하지 않는다.

## Why this stays small

MCP state에는 Task object를 저장하지 않는다.

```text
MCP connection.state
└─ published_task_ids = {"ABC123", "DEF456"}
          │
          │ membership / visibility only
          ▼
SQLite ExecutionStore
└─ label/state/reason/timestamps/result/publication/dismissal
```

따라서 state와 SQLite 사이에 lifecycle synchronization을 만들지 않는다.

## Contract correction

기존 ADR 0006 / plan-260831에는 아래 옛 계약이 남아 있다.

- 모든 ordinary result에 `tracked_tasks`가 항상 존재한다.
- Task가 없으면 `tracked_tasks: []`.
- SQLite의 모든 published + undismissed Task를 automatic projection 대상으로 본다.

이번 결정은 automatic model-visible projection에 한해 이를 supersede한다.

새 계약:

```text
current-session published Task 있음
→ tracked_tasks: [...]

current-session published Task 없음
→ tracked_tasks field omitted

other-session published Task
→ never included in automatic tracked_tasks
```

`task(list)`의 explicit detailed inspection semantics는 별도이며 이번 변경에서 session authorization surface로 바꾸지 않는다.

## CRUD

### C — Create membership

Create는 Execution 생성 시점이 아니다.

잘못된 시점:

```text
generate_execution_id()
→ state에 추가   ❌
```

정확한 시점:

```text
Task publication succeeds
→ connection.state published_task_ids.add(execution_id)   ✅
```

따라서 foreground에서 완료된 Execution은 state에 흔적을 남기지 않는다.

반드시 커버할 publication 경로:

- explicit `delivery="task"` publication
- `delivery="auto"` inline wait expiry 후 publication
- response deadline / transport-loss preservation 중 실제 Task publication이 성공한 경우

원칙:

- publication이 실패하면 state에 추가하지 않는다.
- SQLite에서 `published_at`이 실제 설정된 Task만 membership에 들어간다.
- 같은 ID 재등록은 idempotent해야 한다 (`set.add`).

### R — Read membership

Automatic TrackedTasks projection 시:

1. 기존 SQLite Task authority에서 published + undismissed Task를 읽는다.
2. 현재 MCP connection state의 `published_task_ids`와 교집합만 남긴다.
3. 기존 ordering/bounding semantics를 적용한다.
4. 결과가 비어 있으면 `tracked_tasks` field를 붙이지 않는다.

개념:

```python
visible = [
    task
    for task in published_undismissed_tasks
    if task["execution_id"] in session_published_task_ids
]
```

주의:

- state가 빈 세션이면 SQLite 전체를 model에 노출하지 않는다.
- state 자체는 model-visible output이 아니므로 토큰을 소비하지 않는다.
- Task lifecycle fields는 항상 SQLite에서 읽는다.

### U — Update membership

없다.

Task가:

```text
accepted → running → completed/failed/cancelled/lost
```

로 변해도 MCP state는 수정하지 않는다.

이유:

- membership은 “이 connection에서 publish됐는가”만 표현한다.
- lifecycle state는 SQLite가 유일한 SSOT다.
- terminal Task도 explicit dismiss 전까지 automatic awareness에 남아야 한다.

### D — Delete membership

`task(dismiss)`가 성공한 뒤 해당 ID를 connection state에서 `discard`한다.

```text
SQLite dismiss succeeds
→ published_task_ids.discard(execution_id)
```

`discard`를 사용해 idempotent하게 처리한다.

단:

- `task(get)`은 삭제하지 않는다.
- `task(cancel)`은 삭제하지 않는다.
- terminal 전환 자체도 삭제하지 않는다.
- dismiss 실패 시 state를 먼저 지우지 않는다.

## Ownership

### SQLite owns

- execution_id record
- label
- state
- reason
- result/evidence
- published_at
- dismissed_at
- retention
- cancellation
- lifecycle transitions

### MCP connection state owns

오직:

```text
“이 connection에서 publish된 Task ID 집합”
```

권장 의미 이름:

```python
published_task_ids
```

`session_execution_ids`보다 의미가 정확하다. foreground-only Execution은 포함하지 않기 때문이다.

## SDK seam

현재 MCP SDK는 tool 함수의 `Context` annotation을 감지해서 runtime context를 직접 inject하고, 해당 parameter를 model-facing input schema에서 제외한다.

따라서:

- ContextVar 추가 금지.
- session token을 model 입력으로 추가 금지.
- DB에 session_id column 추가 금지.
- 별도 session registry/service 추가 금지.

가능하면 `_mcp_code_mode` / `_mcp_task` 같은 MCP boundary에서 injected `Context`를 사용한다.

다만 publication helper가 여러 async/follow-up 경로에서 호출되므로, 구현 전 “publication 성공 사실을 어느 boundary에서 connection state에 반영할 수 있는지”를 각 경로별로 확인한다.

중요:

- state registration을 위해 `code_mode()`의 execution-id 생성 API를 불필요하게 바꾸지 않는다.
- foreground 완료 path를 건드리지 않는다.
- publication lifecycle 자체를 state bookkeeping 때문에 재설계하지 않는다.

## Response shaping

새 automatic contract:

### Task가 있을 때

```json
{
  "...primary fields...": "...",
  "tracked_tasks": [
    {
      "execution_id": "ABC123",
      "label": "Long test",
      "state": "running",
      "reason": null,
      "elapsed_seconds": 42
    }
  ]
}
```

### Task가 없을 때

```json
{
  "...primary fields...": "..."
}
```

금지:

```json
{
  "tracked_tasks": []
}
```

현재 사용자 결정상 empty field는 model context에 불필요하므로 생략한다.

## Error outcome

Code Mode error에도 현재 세션의 outstanding published Task가 있으면 `tracked_tasks`를 붙인다.

기존 error evidence는 그대로 유지한다.

```json
{
  "execution_id": "ABC123",
  "error": {...},
  "calls": [...],
  "debug": "...",
  "tracked_tasks": [...]
}
```

없으면 기존 error shape 그대로다.

per-call evidence, stdout/stderr truncation, `_ERROR_DEBUG` 계약은 이번 기능 때문에 변경하지 않는다.

## Explicit Task lifecycle surface

이번 변경은 automatic visibility filter다.

다음은 그대로 유지한다:

```text
task(list)       explicit detailed inspection
task(get)        non-destructive pickup
task(cancel)     explicit cancellation
task(dismiss)    explicit terminal acknowledgement
```

이번 단계에서:

- 다른 세션의 known execution_id에 대한 get/cancel/dismiss authorization 차단을 추가하지 않는다.
- `task(list)`를 session-scoped authorization API로 재정의하지 않는다.
- 보안 boundary와 passive automatic visibility를 섞지 않는다.

## TODO

### Phase 0 — Protect current work

- [ ] `README.patch.openai.provider.md` 기존 변경을 건드리지 않는다.
- [ ] `src/gpt_dive/app.py`의 확정된 `_ERROR_DEBUG` 변경을 유지한다.
- [ ] 작업 전 owned path diff를 캡처한다.
- [ ] unrelated dirty changes에 `git restore`/format을 적용하지 않는다.

### Phase 1 — Lock the new contract in docs

- [ ] ADR 0006의 always-present `tracked_tasks: []` 문구를 session-scoped + omit-empty 계약으로 수정한다.
- [ ] 기존 plan-260831의 superseded assumptions를 명확히 표시하거나 새 plan을 authority로 연결한다.
- [ ] “all published Tasks”가 아니라 “current connection에서 publish된 Tasks ∩ SQLite published+undismissed”임을 명시한다.
- [ ] foreground completion은 membership Create 대상이 아님을 명시한다.

### Phase 2 — Add minimal MCP state helper

- [ ] existing connection state accessor를 generic하게 재사용 가능한지 확인한다.
- [ ] connection state에 `published_task_ids: set[str]`만 둔다.
- [ ] invalid/missing state behavior를 명시한다.
- [ ] Task object/lifecycle data를 state에 저장하지 않는다.
- [ ] ContextVar를 사용하지 않는다.

### Phase 3 — Wire Create to publication success only

- [ ] explicit `delivery="task"` publication 성공 후 membership 추가.
- [ ] auto inline expiry publication 성공 후 membership 추가.
- [ ] transport-loss/deadline preservation publication 성공 경로 검토.
- [ ] publication 실패/미완료 시 membership을 미리 추가하지 않는 테스트.
- [ ] foreground inline completion에서 membership이 생성되지 않는 테스트.
- [ ] foreground inline execution error가 Task로 publish되지 않았다면 membership이 생성되지 않는 테스트.

### Phase 4 — Session-filter automatic projection

- [ ] SQLite의 published + undismissed Task projection을 그대로 authority로 사용한다.
- [ ] MCP state ID membership으로 먼저 session filter한다.
- [ ] 그 뒤 기존 active-first / deterministic / bounded projection semantics를 유지한다.
- [ ] current session에 visible Task가 없으면 `tracked_tasks` field를 생략한다.
- [ ] 다른 session Task가 SQLite에 존재해도 automatic result에 나오지 않는 테스트.
- [ ] session A/B 각각 자기 Task만 보는 cross-session 테스트.

### Phase 5 — Wire Delete to dismiss success

- [ ] `task(dismiss)` 성공 뒤 membership `discard`.
- [ ] dismiss 실패 시 membership 보존.
- [ ] `task(get)` 후 membership 유지.
- [ ] `task(cancel)` 후 membership 유지.
- [ ] completed/failed/cancelled/lost 전환만으로 membership이 삭제되지 않는 테스트.

### Phase 6 — Result surface coverage

- [ ] ordinary successful result + visible Tasks → `tracked_tasks` 포함.
- [ ] ordinary successful result + no visible Tasks → field 생략.
- [ ] Code Mode error + visible Tasks → `tracked_tasks` 포함.
- [ ] Code Mode error + no visible Tasks → 기존 error shape 유지.
- [ ] pending/task-delivery result에서도 current-session awareness 계약 확인.
- [ ] primary result shape/wrapper semantics를 불필요하게 바꾸지 않는다.
- [ ] output schema를 변경해야 하는지 live MCP SDK conversion 기준으로 최소 범위 확인 후 결정한다.

### Phase 7 — Regression tests

- [ ] foreground completion does not create session membership.
- [ ] explicit background publication creates membership.
- [ ] auto background publication creates membership.
- [ ] session A cannot automatically see session B Task.
- [ ] reconnect/new connection starts with empty membership.
- [ ] lifecycle state refresh comes from SQLite without state updates.
- [ ] terminal Task remains visible until dismiss.
- [ ] dismiss removes it.
- [ ] projection bounding/order still works after session filtering.
- [ ] `_ERROR_DEBUG` tests remain green.
- [ ] existing durability/deadline/cancellation tests remain green.

### Phase 8 — Validation

- [ ] targeted Ruff format/check on owned files only.
- [ ] `git diff --check` on owned files.
- [ ] focused Task/Code Mode/surface tests.
- [ ] broader runtime suite only after focused suite is green.
- [ ] inspect final diff for accidental schema/API expansion.
- [ ] verify no ContextVar/session DB/schema/service was introduced.

### Phase 9 — Live connector canary

- [ ] fresh ChatGPT session A: foreground Code Mode completes → no tracked membership.
- [ ] session A: publish background Task → later ordinary result shows it.
- [ ] fresh ChatGPT session B: same server DB contains session A Task but automatic result does not show it.
- [ ] session A: observe running → terminal via ordinary activity.
- [ ] session A: `task(get)` does not remove awareness.
- [ ] session A: `task(dismiss)` removes awareness.
- [ ] after no session-visible Tasks remain, later result omits `tracked_tasks` entirely.

## Non-goals

- durable per-conversation ownership across MCP reconnects
- ChatGPT conversation-id persistence
- task authorization/security boundary
- second Task store
- DB schema migration for session identity
- server push/event bus
- ContextVar propagation
- publishing every Execution
- changing Code Mode call evidence
- changing `_ERROR_DEBUG`
- changing OpenAI provider work

## Stop conditions

구현 중 아래 중 하나가 필요해지면 즉시 범위를 재검토한다.

- DB schema에 session/conversation identity를 추가해야 함
- ContextVar가 필요함
- `code_mode()` public/internal signature를 session bookkeeping 때문에 크게 바꿔야 함
- Task lifecycle state를 MCP state에 복제해야 함
- foreground Execution을 membership에 넣어야 함
- 각 tool마다 별도 tracked_tasks 구현이 필요해짐

이 경우 현재 minimal design에서 벗어난 신호다.

## Acceptance summary

완료 조건은 한 문장으로:

> MCP connection state는 “이 connection에서 실제 publish된 Task ID”만 기억하고, automatic `tracked_tasks`는 그 ID와 SQLite의 current published+undismissed Task의 교집합만 필요할 때 노출한다.

