# Automatic TrackedTasks Projection

## Problem Statement

GPT Dive의 TrackedTasks는 background Task가 끝났는지 Web SOL이 별도 polling을 기억하지 않아도 **ordinary tool activity 중 자동으로 재발견**하게 만들기 위한 passive awareness mechanism이다.

현재 Runtime은 publish되고 아직 dismiss되지 않은 Task를 SQLite에서 알고 있고, server-side middleware도 TrackedTasks를 계산할 수 있다. 하지만 기존 carrier는 awareness를 `CallToolResult.content[]`의 추가 `TextContent`로 붙였고, live ChatGPT connector에서는 이 내용이 model-visible output에 나타나지 않았다.

문제는 TrackedTasks 설계 자체가 아니라 **model-visible carrier가 실패한 것**이다. 이를 `task(list)` polling으로 대체하면 Web SOL이 background work와 polling 시점을 계속 기억해야 하므로 원래 목적을 잃는다.

동시에 최근 compact-output 작업에서 서로 다른 public surface의 계약이 잘못 합쳐졌다. Code Mode normal outcome을 줄이기 위한 ADR 0005의 compactness가 Task awareness까지 확장되면서 다음 두 regression이 생겼다.

- `task(list)`가 complete structured Task inspection에서 `execution_id`, `label`, `state`, `reason`만 남기는 compact list로 축약됐다.
- automatic TrackedTasks render에서 기존 elapsed 표시가 제거됐다.

이 둘은 ADR 0005의 요구사항이 아니다. ADR 0005가 compact하게 만든 대상은 `code_mode`와 `task(get)`의 normal outcome이고, `task(list)`와 TrackedTasks는 별도 Task-awareness surface다.

따라서 이번 구현은 automatic rediscovery carrier를 복구하면서 **기존 surface별 정보 계약을 보존**해야 한다.

```text
code_mode / task(get)
→ compact program/delivery outcome

task(list)
→ explicit detailed structured Task inspection

TrackedTasks / tracked_tasks
→ passive bounded awareness
→ elapsed 표시 유지
```

사용자가 원하는 contract는 다음과 같다.

- ordinary tool result가 정상적으로 model에게 전달되면 `tracked_tasks`가 항상 존재한다.
- Task가 없으면 빈 list다.
- Task가 running이면 running 상태와 elapsed가 보인다.
- Task가 completed/failed/cancelled/lost가 되면 다음 ordinary tool activity에서 갱신된 상태가 자동으로 보인다.
- completion discovery를 위해 `task(list)` polling을 기억할 필요가 없다.
- `task(list)`를 명시적으로 호출하면 compact awareness가 아니라 detailed Task 정보를 얻는다.
- primary tool result와 Task awareness는 같은 response에 공존하지만 서로 다른 의미를 유지한다.

ADR 0006이 이 spec의 primary decision authority다. ADR 0004의 lifecycle/SQLite authority와 ADR 0005의 program-output semantics는 유지한다. 기존 Task-awareness plan은 `task(list)` detailed inspection과 TrackedTasks elapsed semantics의 historical contract evidence다.

## Solution

GPT Dive의 ordinary model-visible tool result에 **always-present top-level `tracked_tasks` projection**을 추가한다.

Automatic projection은 기존 SQLite Task authority에서 publish되고 아직 dismiss되지 않은 Task를 읽어 bounded, deterministic passive-awareness snapshot으로 만든다. Primary result를 wrapper로 감싸지 않고 기존 primary fields 옆의 sibling metadata로 projection한다.

Automatic TrackedTasks item은 passive awareness에 필요한 다음 정보를 유지한다.

- `execution_id`
- `label`
- `state`
- `reason`
- `elapsed_seconds`

`elapsed_seconds`는 lifecycle authority가 아니라 read/render 시 파생되는 display 정보다. 사람이 읽는 render에서는 이를 `4:21` 또는 `1:04:21` 같은 compact elapsed 표시로 표현할 수 있다.

Explicit `task(list)`는 automatic TrackedTasks와 같은 compact field set으로 통일하지 않는다. 같은 SQLite Task authority를 읽지만 **detailed inspection surface**로서 complete structured Task object를 유지한다. 현재 detailed Task contract에는 identity/lifecycle fields와 함께 `accepted_at`, `finished_at`, `published_at`, `updated_at`, `elapsed_seconds`가 포함된다.

동작 원칙은 다음과 같다.

- ordinary work tool의 successful model-visible result에는 `tracked_tasks`가 항상 존재한다.
- outstanding Task가 없으면 `tracked_tasks`는 빈 list다.
- snapshot이 이전 call과 같아도 field를 생략하지 않는다.
- Task state 또는 derived elapsed가 변하면 다음 ordinary result는 현재 snapshot을 보여준다.
- automatic TrackedTasks와 explicit `task(list)`는 같은 SQLite authority와 lifecycle semantics를 사용하지만 public field set은 의도적으로 다르다.
- `task(list)`는 explicit detailed inspection surface로 남지만 normal completion-discovery path는 아니다.
- bootstrap initialization과 explicit Task lifecycle operations는 ordinary-work automatic injection 대상이 아니다. Task lifecycle surface는 자체 result semantics를 유지한다.
- projection failure를 빈 list로 위장하지 않는다. Normal awareness contract를 만들 수 없는 경우 오류를 명시적으로 드러내며 별도 저장소나 replay machinery를 추가하지 않는다.
- 기존 `content[]` TrackedTasks text carrier와 per-connection changed-only suppression은 model-visible awareness contract의 authority에서 제거한다.

Public schema와 runtime value는 반드시 함께 움직인다. Advertised MCP output schema에도 `tracked_tasks`가 required awareness field로 드러나고, 실제 ChatGPT-visible structured result에도 같은 field가 있어야 한다. Server unit test에서만 보이고 connector에서 사라지는 구현은 완료로 보지 않는다.

## User Stories

1. As Web SOL, I want every successful ordinary GPT Dive result to include current `tracked_tasks`, so that I can see background work without remembering a separate polling step.
2. As Web SOL, I want `tracked_tasks` to be present even when there are no outstanding Tasks, so that I do not have to infer whether omission means none or unchanged.
3. As Web SOL, I want a background Task launched as running to remain visible on later ordinary tool activity, so that I can continue foreground work without waiting.
4. As Web SOL, I want a running Task that becomes completed to appear as completed on a later ordinary tool result, so that completion is rediscovered automatically.
5. As Web SOL, I want failed, cancelled, or lost terminal Tasks to remain visible until explicitly dismissed, so that terminal work is not silently forgotten.
6. As Web SOL, I want Task completion discovery to work without `task(list)` polling, so that correctness does not depend on long-session memory.
7. As Web SOL, I want `task(list)` to remain available for explicit detailed inspection, so that I can inspect full Task lifecycle/display metadata when useful.
8. As Web SOL, I want `task(list)` to keep complete structured Task objects rather than a four-field awareness projection, so that explicit inspection does not lose timestamps or elapsed information.
9. As Web SOL, I want automatic TrackedTasks to keep elapsed information, so that passive awareness still tells me how long background work has been running.
10. As Web SOL, I want `task(get)` to remain non-destructive, so that reading a result does not create a loss window before I have handled it.
11. As Web SOL, I want `task(dismiss)` to be the action that removes terminal awareness, so that pickup and acknowledgement remain separate decisions.
12. As Web SOL, I want the primary Code Mode output to remain directly accessible, so that automatic awareness does not reintroduce a `result.result`-style wrapper.
13. As Web SOL, I want `tracked_tasks` beside the primary result rather than inside program `output`, so that program semantics and Task awareness stay distinct.
14. As Web SOL, I want raw shell results to keep their normal fields while also showing current background awareness, so that ordinary shell activity can rediscover completed work.
15. As Web SOL, I want repeated ordinary calls to keep showing the current snapshot even when lifecycle state did not change, so that each response is self-contained.
16. As Web SOL, I want automatic awareness to stay bounded and compact while retaining elapsed, so that background context stays useful without becoming a detailed inspection dump.
17. As Web SOL, I want active Tasks prioritized over terminal backlog when the bounded snapshot is full, so that current work is not hidden by old completed items.
18. As Web SOL, I want Task ordering to be deterministic, so that repeated snapshots are stable and easy for the model to compare.
19. As a user, I want background latency removed from the foreground critical path, so that Web SOL can keep working while long operations finish independently.
20. As a user, I want completed background work to surface naturally during later work, so that I do not have to remind the AI to check it.
21. As a user, I want a missed individual response not to lose a completed Task, so that terminal awareness remains available on subsequent ordinary calls until dismissal.
22. As a maintainer, I want SQLite to remain the single Task-awareness authority, so that automatic projection does not create a second store or reconciliation problem.
23. As a maintainer, I want automatic TrackedTasks and `task(list)` to share lifecycle meaning but not be forced into the same field set, so that passive awareness and explicit inspection can each preserve their intended information density.
24. As a maintainer, I want the projection to be cross-cutting at the existing tool response boundary, so that individual ordinary tools do not implement Task awareness independently.
25. As a maintainer, I want advertised output schemas and runtime structured results to express the same automatic awareness contract, so that SDK projection details cannot create a hidden connector mismatch.
26. As a maintainer, I want the existing primary result schema preserved, so that adding awareness does not resurrect an outer semantic wrapper.
27. As a maintainer, I want change-only revision suppression removed from the model-visible contract, so that callers never need connection-local history to interpret a result.
28. As a maintainer, I want automatic TrackedTasks to exclude detailed timestamps, backend, and process metadata while retaining derived elapsed, so that passive awareness remains compact without regressing its established display semantics.
29. As a maintainer, I want `task(list)` detailed metadata preserved independently from ADR 0005 compact outcomes, so that changes to program delivery do not silently redefine Task inspection.
30. As a maintainer, I want projection failure to be distinguishable from an empty Task list, so that the runtime does not lie about awareness state.
31. As a maintainer, I do not want a new push subsystem, event bus, polling scheduler, or second Task service, so that the fix stays proportional to the connector problem.
32. As a maintainer, I want the old `content[]` text carrier removed from contract-critical behavior, so that tests do not validate a surface ChatGPT does not expose to the model.
33. As a maintainer, I want a live ChatGPT connector canary to prove automatic `running → completed` rediscovery without an intervening `task(list)`, so that acceptance verifies the actual user-facing behavior.
34. As a maintainer, I want terminal dismissal proven in the same lifecycle canary, so that the automatic snapshot disappears only after explicit acknowledgement.
35. As a maintainer, I want current durability, cancellation, deadline, retention, and single-`execution_id` semantics preserved, so that awareness repair does not reopen ADR 0004.
36. As a maintainer, I want ADR 0005 local-reduction semantics preserved only on its intended outcome surfaces, so that compact program output does not spill into separate Task-awareness APIs.
37. As a maintainer, I want broad runtime terminology cleanup deferred, so that this implementation remains focused on automatic TrackedTasks projection rather than ADR 0009 migration.

## Implementation Decisions

- ADR 0006 is the primary authority for this implementation. ADR 0004 remains authoritative for Execution/Task lifecycle and SQLite persistence, while ADR 0005 remains authoritative for `code_mode`/`task(get)` program outcome semantics.
- Automatic TrackedTasks applies at one cross-cutting ordinary tool-response projection seam rather than being implemented independently by each ordinary work tool.
- Bootstrap initialization and explicit Task lifecycle calls are not treated as ordinary-work automatic injection points. `task(list)` remains explicit inspection rather than the normal rediscovery mechanism.
- Every successful ordinary model-visible result has a required top-level `tracked_tasks` list. Empty and unchanged snapshots remain present.
- `tracked_tasks` is additive sibling metadata. It is not nested inside final program `output`, and the primary result is not moved under a new `result` wrapper.
- The automatic snapshot uses the existing SQLite-backed published-and-undismissed Task authority. No new persistence layer, cache authority, or Task registry is introduced.
- Automatic TrackedTasks uses a dedicated passive-awareness projection containing `execution_id`, `label`, `state`, `reason`, and derived `elapsed_seconds`.
- Automatic elapsed remains display information rather than lifecycle SSOT. Human-readable rendering may format it as minutes/seconds or hours/minutes/seconds.
- Explicit `task(list)` keeps complete structured Task objects. It must not be projected through the compact TrackedTasks helper or a shared four-field awareness model.
- Current detailed Task inspection retains `execution_id`, `label`, `state`, `reason`, `accepted_at`, `finished_at`, `published_at`, `updated_at`, and `elapsed_seconds`.
- Automatic TrackedTasks and `task(list)` share SQLite authority and lifecycle semantics, not an identical public representation.
- Automatic snapshot bounding and ordering remain server-owned implementation policy. Active Tasks are preferred over terminal backlog, ordering is deterministic, and the exact numeric limit is not promoted to public API semantics.
- Model-visible change-only suppression is removed. Internal computation may still avoid unnecessary work, but the output field itself is never omitted because a previous revision matched.
- The old appended TrackedTasks text block is no longer relied upon as the model-visible carrier. Any retained human-readable rendering must preserve elapsed semantics but is not the connector contract.
- Advertised output schemas for ordinary work tools must include the same `tracked_tasks` contract that runtime structured results return. Schema augmentation must preserve each tool's existing primary output shape and strictness.
- The Code Mode discriminated primary outcome remains directly top-level. Adding `tracked_tasks` must not cause the MCP SDK to reintroduce an outer `result` property.
- Raw shell primary fields remain unchanged except for the additive `tracked_tasks` sibling.
- Projection-read failure must not be represented as a successful empty snapshot. The implementation must expose the failure honestly without adding a second awareness protocol or persistence fallback.
- Successful Task result pickup remains non-destructive. Explicit dismissal remains the normal operation that removes terminal awareness.
- Current naming such as the existing Code Mode discriminator and delivery input is not renamed as part of this feature. ADR 0009 naming migration is a separate change.
- User/model guidance must state that ordinary result `tracked_tasks` is the normal automatic rediscovery path and `task(list)` is explicit detailed inspection, not a polling obligation.

## Testing Decisions

A good test proves **externally observable MCP behavior and preserved surface contracts**, not a private helper implementation. Exact schema/value assertions are appropriate because the model-facing contract itself is the feature.

### Primary test seam: public MCP surface

- Extend the existing public tool-schema tests to prove ordinary work-tool output schemas advertise required `tracked_tasks` awareness while preserving each primary result shape.
- Prove Code Mode still exposes its primary discriminated outcome directly at top level and does not regain a top-level `result` wrapper.
- Prove raw shell output keeps its existing primary fields and gains only the awareness sibling.
- Prove automatic `tracked_tasks` items include `execution_id`, `label`, `state`, `reason`, and `elapsed_seconds`, while excluding detailed timestamps/backend/process metadata.
- Reuse the existing public `structured_content` test seam to prove actual converted MCP results contain `tracked_tasks`, not only the advertised schema.
- Prove an empty Task authority returns `tracked_tasks: []` rather than omission.
- Prove the current snapshot is returned on consecutive ordinary calls; no connection revision is required to interpret the second response.
- Prove a Task changing from running to a terminal state changes the later automatic snapshot.
- Prove derived elapsed advances for a running Task and remains stable according to existing terminal elapsed semantics.
- Prove primary result fields remain unchanged while awareness is added.
- Prove an awareness projection failure does not silently masquerade as `tracked_tasks: []`.

### Secondary test seam: explicit Task inspection and lifecycle

- Add/restore `task(list)` schema coverage proving it returns the detailed TaskView rather than a compact awareness view.
- Prove `task(list)` retains timestamps and `elapsed_seconds` required by the explicit inspection contract.
- Prove automatic TrackedTasks and `task(list)` may expose different field sets while reflecting the same underlying Task state.
- Reuse existing Task lifecycle tests for published/undismissed selection, non-destructive get, explicit dismiss, single `execution_id`, active-before-terminal ordering, and bounded projection behavior.
- Keep lifecycle tests focused on SQLite/Task semantics rather than connector formatting.
- Replace tests introduced by the compact-vocabulary regression that assert four-field `task(list)` output or missing TrackedTasks elapsed.

### TrackedTasks render non-regression

- Preserve coverage that a running Task's elapsed duration is visible in the compact human-readable TrackedTasks rendering.
- Keep the rendering bounded and exclude internal field names or detailed timestamp dumps.
- Do not make human-readable rendering the acceptance carrier for ChatGPT; it is a semantics regression guard while structured `tracked_tasks` is the model-visible contract.

### Live connector acceptance seam

A green local suite is necessary but not sufficient. Final acceptance requires a fresh ChatGPT connector canary that proves the behavior the user actually wants.

The canary must:

1. launch a deterministic short-lived Code Mode Task;
2. continue with ordinary tool activity rather than waiting on or polling the Task;
3. observe the Task in automatic `tracked_tasks` without calling `task(list)`;
4. observe a later automatic snapshot showing the Task's terminal state, again without `task(list)` being required for discovery;
5. verify passive awareness carries elapsed information while the Task is active;
6. call `task(list)` separately and verify detailed Task inspection remains richer than automatic TrackedTasks;
7. retrieve the result non-destructively only after it is automatically rediscovered;
8. explicitly dismiss the handled Task;
9. verify a later ordinary result no longer includes the dismissed Task;
10. inspect both advertised MCP schema and actual model-visible structured output during the canary.

The acceptance criterion is **automatic rediscovery through ordinary activity without regressing either Task-awareness surface**. A test that succeeds only because it explicitly polls `task(list)`, or that passes by making `task(list)` and TrackedTasks the same compact shape, does not satisfy this spec.

### Prior art

- Existing public-surface tests already assert Code Mode and Task output schemas, strict result shapes, and actual model-visible `structured_content`.
- Existing historical Task-awareness tests/specs establish complete structured `task(list)` inspection and derived elapsed behavior.
- Existing TrackedTasks middleware tests exercise primary-result preservation, elapsed rendering, and state-change behavior; assertions introduced to remove elapsed are regression expectations and must not become authority.
- Existing Task projection tests cover non-destructive get, dismissal, bounded output, single execution identity, and active-before-terminal ordering.
- Existing Code Mode output-contract tests are prior art for treating advertised schema plus live structured output as a single acceptance boundary without applying ADR 0005 compactness to unrelated awareness surfaces.

## Out of Scope

- Redesigning Execution, Worker, Task publication, cancellation, deadlines, retention, or the single `execution_id` lifecycle from ADR 0004.
- Changing Code Mode local-reduction, final-expression, console, or output-bounding semantics from ADR 0005.
- Making `task(list)` compact as part of Code Mode outcome simplification.
- Removing TrackedTasks elapsed information for context reduction.
- Broad bootstrap/model-guidance restructuring from ADR 0007 beyond the minimum wording required to distinguish automatic awareness from explicit detailed inspection.
- ADR 0008 raw Execution evidence recovery.
- ADR 0009 repo-wide naming migration such as discriminator, delivery-input, or error-field renames.
- Native MCP Tasks negotiation, server push, subscriptions, event streams, or a general notification subsystem.
- A new polling scheduler, reminder timer, or model-driven periodic `task(list)` loop.
- A second Task store, awareness database, cache authority, or reconciliation mechanism.
- Persisting every intermediate capability result or building a full execution transcript.
- Automatic `task(get)`, automatic result consumption, automatic dismissal, or automatic retry/replay.
- New backend/process diagnostics in the normal automatic awareness snapshot.
- Maintaining the old `content[]` TrackedTasks text as a fallback connector contract.
- Compatibility aliases or dual old/new awareness protocols.

## Further Notes

- The defining invariant is: **TrackedTasks exists so the AI does not have to remember to poll.** Any implementation that requires `task(list)` cadence for correctness has missed the feature even if its Task lifecycle is otherwise correct.
- A second invariant is: **compact Code Mode outcomes do not imply compact Task inspection.** `task(list)` is a separate detailed surface.
- A third invariant is: **passive TrackedTasks keeps elapsed awareness.** Removing elapsed to share a four-field helper with `task(list)` is a regression, not simplification required by ADR 0005.
- The connector observation from 2026-08-31 is evidence that the old `content[]` carrier is ineffective in the current ChatGPT path, not evidence against automatic awareness.
- `tracked_tasks` is cross-cutting awareness metadata, not part of the Monty program `output`. This distinction is what allows ADR 0005's minimal output contract and ADR 0006's automatic awareness to coexist.
- Automatic TrackedTasks and `task(list)` deliberately have different information density. Shared authority does not require shared public shape.
- This plan is the local implementation SSOT for ADR 0006. Historical Task-awareness documents remain authority for pre-existing detailed-inspection and elapsed-display semantics unless a later ADR explicitly supersedes them.
