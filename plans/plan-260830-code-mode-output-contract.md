# Code Mode Output Contract

## Problem Statement

Code Mode의 현재 model-visible output은 원래 의도한 **local reduction boundary**를 충분히 보존하지 못한다.

Monty 안에서 capability의 큰 중간값을 병렬로 가져와 로컬에서 선별·조합한 뒤 작은 final expression만 caller/model에게 돌려주는 것이 핵심인데, 현재 projection은 다음 문제를 만든다.

- Monty `print()`의 console/progress 의미를 실행 종료 시 누적 `stdout` 필드로 다시 final response에 섞는다.
- runtime/worker/public outcome을 지나며 `result` 의미의 wrapper가 생겨 실제 program value까지 불필요한 JSON 경로를 따라가야 한다. 특히 MCP SDK가 generic/Union return annotation을 `{"result": value}`로 자동 projection하는 경우도 model-visible contract 위반으로 취급한다.
- 정상 completed outcome에 caller가 이미 알고 있는 `label` 같은 metadata가 반복된다.
- lifecycle, program result, console/progress, Task awareness가 하나의 output surface에서 필요 이상으로 섞인다.
- `code_mode`와 `task(get)`이 같은 durable Execution을 다루면서도 서로 다른 return vocabulary를 사용하면 LLM이 별도 분기 규칙을 학습해야 한다.
- model-visible 구조가 복잡할수록 LLM의 discriminator 판단, 필드 선택, 후속 `task(get)` 호출, 결과 해석 오류 가능성이 커진다.

이 변경의 최우선 소비자는 사람이 아니라 **LLM AI**다. 사람이 보기 좋은 축약보다, 모델이 추론 없이 안정적으로 분기하고 원하는 program output에 바로 도달하는 계약을 우선한다.

## Solution

Code Mode를 **programmable local reduction boundary**로 유지하고, model-visible public outcome을 하나의 작고 일관된 discriminated union으로 정리한다.

- capability return은 기본적으로 Monty 내부 프로그램 데이터다.
- 독립 capability는 `asyncio.gather()`로 병렬 실행하고, 큰 중간값은 Monty 내부에서 선별·조합한다.
- `print()`는 Monty의 console/progress 의미로 유지하되 정상 final program result에 자동 병합하지 않는다.
- final Monty expression이 caller/model에게 전달되는 유일한 정상 program output이다.
- `code_mode`와 `task(get)`은 같은 outcome vocabulary를 사용한다.
- public outcome은 `kind`를 명시적 discriminator로 유지하고, durable identifier는 항상 `execution_id`라는 한 이름만 사용한다.
- 정상 outcome에 필요 없는 metadata와 duplicate semantic wrapper를 제거한다.
- MCP tool의 advertised `outputSchema`와 실제 live `structuredContent`는 outcome object를 top-level에 직접 노출해야 하며, SDK-generated 최상위 `result` wrapper를 허용하지 않는다.
- 이상한 결과를 조사할 수 있도록 `execution_id`는 항상 보존한다.
- public `output` 안의 string/list/dict 구조는 Monty program이 결정하며 runtime은 다시 장식하거나 중첩하지 않는다.

목표 public contract는 다음 세 shape다. 이 type shape는 ADR 0005에서 승인된 schema 결정을 그대로 옮긴 것이다.

```text
completed = { kind: "completed", execution_id, output }
task      = { kind: "task",      execution_id, state }
error     = { kind: "error",     execution_id, code, message }
```

핵심 최적화 원칙은 다음과 같다.

```text
one discriminator
+ one identifier vocabulary
+ one output vocabulary
+ minimum metadata
+ no duplicate semantic wrappers
```

## User Stories

1. As an LLM consuming Code Mode, I want every outcome to have an explicit `kind`, so that I can branch without inferring the shape from optional fields.
2. As an LLM consuming Code Mode, I want one durable identifier name, `execution_id`, so that I do not have to translate between `id`, `task_id`, `job_id`, or similar aliases.
3. As an LLM receiving a completed execution, I want the final Monty expression directly under `output`, so that I do not have to navigate `result.result.result`-style wrappers.
4. As an LLM receiving a completed execution, I want only `kind`, `execution_id`, and `output` in the normal contract, so that irrelevant metadata does not compete for attention.
5. As an LLM receiving a running execution, I want only `kind`, `execution_id`, and `state`, so that I can immediately decide whether to call `task(get)` later.
6. As an LLM receiving an execution failure, I want `kind`, `execution_id`, `code`, and `message` at one level, so that I can classify the failure without traversing a nested error envelope.
7. As an LLM debugging an unexpected compact result, I want `execution_id` preserved even on completed outcomes, so that I can inspect retained execution evidence later.
8. As an LLM that already supplied the Code Mode label, I do not want the same label repeated on completed or error outcomes, so that model-visible context is not spent on known information.
9. As an LLM listing multiple Tasks, I still want labels on the awareness/list surface where they distinguish executions, so that metadata is removed only where it is redundant.
10. As an LLM running several independent capabilities, I want to use `asyncio.gather()` and keep all intermediate values local, so that wall-clock latency drops without injecting every tool result into model context.
11. As an LLM processing a large file or search result, I want to select only the useful subset in the final Monty expression, so that model context scales with the answer rather than the raw evidence size.
12. As an LLM using a capability result only for computation, I want that value to remain internal unless I explicitly select it for final output, so that intermediate data is not mirrored automatically.
13. As an LLM using `print()`, I want it to mean explicit console/progress observation rather than a second durable result payload, so that program output and progress do not become semantically ambiguous.
14. As an LLM that never calls `print()`, I want the final output contract to be unaffected by console machinery, so that the common path stays minimal.
15. As a future TUI/ACP/Web client, I want `print()` to remain a separate conceptual channel, so that live progress can later be added without redesigning the final program result contract.
16. As an LLM returning a string, I want that string to appear directly as `output`, so that runtime wrappers do not reinterpret it.
17. As an LLM returning a list, I want that list to appear directly as `output`, so that I can intentionally build ordered sections or mixed structured content inside Monty.
18. As an LLM returning a dict, I want that dict to appear directly as `output`, so that structured answers survive the runtime boundary unchanged.
19. As an LLM using inline `code_mode`, I want a completed Execution to have the same completed shape as the same Execution later retrieved with `task(get)`, so that delivery timing does not change result semantics.
20. As an LLM using `mode="task"`, I want the immediate task outcome to use the same `kind` and `execution_id` vocabulary as later retrieval, so that there is one lifecycle language.
21. As an LLM receiving a task outcome, I do not want backend, pid, timestamps, elapsed time, systemd details, or other operator metadata unless explicitly requested elsewhere, so that normal branching remains simple.
22. As an LLM receiving an error outcome, I do not want traceback, cleanup internals, or large raw diagnostics in the normal response, so that common recovery starts from a compact classification.
23. As an operator investigating an error, I want deeper retained evidence to remain reachable by `execution_id`, so that compact model output does not destroy observability.
24. As a runtime maintainer, I want lifecycle state to remain separate from program output, so that ADR 0004 durability semantics are not accidentally changed while simplifying the projection.
25. As a runtime maintainer, I want Task awareness to remain separate from program output, so that the current TrackedTasks connector bug does not distort the new output contract.
26. As a runtime maintainer, I want public names touched by this change to converge on `kind`, `execution_id`, `output`, `state`, `code`, and `message`, so that old synonyms do not remain beside the new contract.
27. As a runtime maintainer, I do not want a repo-wide terminology rewrite mixed into this patch, so that naming improvements stay proportional to the output-contract change.
28. As a runtime maintainer, I do not want an emoji-delimited machine protocol, so that simplifying JSON does not create a second parsing protocol with escaping/versioning concerns.
29. As a runtime maintainer, I want emoji or rich framing to remain presentation/debug-only, so that human-visible debugging can be distinctive without changing the runtime contract.
30. As a runtime maintainer, I want any final-output size bounding to occur after Monty has reduced intermediate data, so that Code Mode can still process large local capability results.
31. As a runtime maintainer, I want exact public contract tests to fail when unnecessary metadata is reintroduced, so that the LLM-optimized surface does not gradually bloat again.
32. As a runtime maintainer, I want tests to assert public behavior rather than private helper structure, so that projection internals can be simplified freely while the contract remains stable.
33. As a runtime maintainer, I want the same retained program value to back inline and Task delivery, so that there is no second source of truth for completed output.
34. As a runtime maintainer, I want no new event bus, transcript persistence model, or streaming framework in this change, so that the semantic correction is not buried under speculative infrastructure.
35. As a future maintainer reading the spec, I want the rejected alternatives and scope boundaries preserved, so that later cleanup does not accidentally recreate the context-polluting design.
36. As an LLM receiving MCP structured output, I want the outcome object itself at the top level rather than `{"result": outcome}`, so that SDK projection details do not become part of the reasoning contract.

## Implementation Decisions

### 1. Preserve four separate meanings

The implementation must keep these concepts separate:

- **Capability return** — internal Monty program data.
- **Console/progress** — explicit `print()` output.
- **Program output** — final Monty expression returned to the caller/model.
- **Execution/Task lifecycle** — durable state and awareness defined by ADR 0004.

No layer may automatically duplicate one meaning into another merely for convenience.

### 2. Keep `print()` as a Monty feature but disconnect it from normal final output

Do not remove the Monty language/runtime `print()` feature. Remove the current behavior where accumulated print capture is replayed as a final model-visible `stdout` field.

This spec does not add live streaming, ordered transcript persistence, or a new event system. If the Monty runtime integration requires a print callback, use the simplest compatible handling that does not reintroduce print text into the normal public outcome.

### 3. Final Monty expression becomes the single program value

The runtime path should treat the Monty final expression as the program value and carry that value through durable retention and delivery without adding semantic `result` wrappers at each layer.

At the public boundary the field name is `output`.

A completed outcome contains exactly:

- `kind = "completed"`
- `execution_id`
- `output`

The value of `output` may be any supported serializable final Monty value, including string, list, or dict.

### 4. Use one public discriminated union for Code Mode delivery

`code_mode` and `task(get)` must project the same three outcome kinds:

- **completed** — `kind`, `execution_id`, `output`
- **task** — `kind`, `execution_id`, `state`
- **error** — `kind`, `execution_id`, `code`, `message`

Delivery timing may differ, but a completed durable Execution must have the same public meaning regardless of whether it was returned inline or collected later.

The current MCP SDK 2.0.0 wraps generic/Union return annotations as `{"result": value}` for structured output. That SDK-generated wrapper is not part of the approved contract. The implementation must therefore choose a registration/return model whose advertised `outputSchema` and live `structuredContent` expose the discriminated outcome union itself at the top level. A Pydantic `RootModel` is one possible implementation candidate if it satisfies that canary; it is not itself a contract requirement.

### 5. Keep `kind` even when another field appears to imply the outcome

`kind` is an intentional LLM-facing discriminator. The model should not infer outcome type from the presence of `state`, `output`, or `code`.

The small token cost is accepted because explicit branching is more valuable than clever field minimization.

### 6. Keep `execution_id` and do not shorten it to `id`

`execution_id` is the durable recovery/debug handle and the vocabulary already used by Task operations. A shorter generic name would save little while increasing ambiguity with other IDs.

The same runtime identity must not be exposed under new aliases such as `id`, `task_id`, or `job_id` on the changed surface.

### 7. Remove redundant completed/error metadata

Completed and error outcomes must not repeat the input label. Normal outcomes must not expose backend, pid, systemd unit, timestamps, elapsed time, cleanup internals, or other operator diagnostics.

Metadata remains allowed on surfaces where it has a distinct purpose, such as labels on a multi-Task awareness/list view.

### 8. Flatten the normal error contract

Normal model-visible errors expose one classification code and one concise message alongside `kind` and `execution_id`.

Deep diagnostics and raw evidence are not copied into the normal response. They remain a separate recovery/observability concern keyed by `execution_id`.

### 9. Let Monty own the internal shape of `output`

Runtime layers must not wrap or decorate a program-generated string/list/dict merely to make it look more presentational. The Monty program is responsible for selecting, arranging, labeling, and compacting its final value.

This keeps the runtime contract stable while allowing task-specific output to be optimized inside the program.

### 10. Keep large intermediate capability data local

Do not apply Web-facing truncation/spill projection to each Code Mode capability return. The program must be able to filter, compare, aggregate, or search large intermediate values locally before selecting the final output.

Any size-bounding policy that is part of the changed path belongs at the final program-output seam and must preserve identical semantics for inline and later Task delivery.

This spec does not introduce new raw-evidence storage or TTL infrastructure.

### 11. Actively normalize naming only on the changed path

Where the implementation directly touches the output projection path, remove stale synonyms and align names with the public vocabulary when doing so simplifies ownership and does not require unrelated architectural churn.

Do not retain an old and a new name side-by-side merely for compatibility unless an existing external contract requires it.

Do not expand this into repo-wide terminology work.

### 12. Do not introduce a custom text framing protocol

Emoji combinations or other visually unique delimiters may be useful in temporary debug/presentation rendering, but they are not part of the machine contract.

The machine contract remains structured data with the single discriminated union above.

### 13. Preserve ADR 0004 lifecycle authority

This change does not alter always-durable Execution creation, claim semantics, cancellation, deadlines, publication, retention authority, transport-loss behavior, or the single durable `execution_id` model.

The output refactor must fit inside those invariants rather than create a second lifecycle.

### 14. Preserve decision context over implementation history

The implementation must be reviewed against ADR 0005's root reason — local reduction plus an LLM-minimal output boundary — not against the superseded refactoring work log that previously occupied ADR 0005.

If implementation pressure suggests reintroducing extra wrappers or metadata, the default is to reject them unless they serve a distinct model-facing semantic need.

## Testing Decisions

### Test contract

The smallest useful Test Contract is the public outcome behavior plus one narrow Monty runtime semantic check.

1. **Public completed outcome** — a successful inline Code Mode call exposes exactly `kind`, `execution_id`, and `output` at the top level of model-visible structured output, with no outer `result` property.
2. **Output type preservation** — representative string, list, and dict final expressions arrive unchanged under `output`.
3. **No final print replay** — a program that uses `print()` and then returns a final expression does not expose accumulated print text as a normal final field.
4. **Local reduction** — independent capability calls can be gathered and reduced to a compact final output without intermediate full results appearing in the public outcome.
5. **Public task outcome** — a still-running/published execution returns exactly `kind`, `execution_id`, and `state` on the Code Mode/Task collection surface being tested.
6. **Inline/Task equivalence** — a completed Execution retrieved through `task(get)` has the same completed outcome vocabulary and same retained program value as inline completion.
7. **Public error outcome** — a runtime failure exposes exactly `kind`, `execution_id`, `code`, and `message` in the normal error surface.
8. **Metadata/wrapper absence** — completed/task/error contract tests explicitly fail if `label`, `stdout`, backend/process/timestamp/elapsed metadata, nested semantic `result` wrappers, or an SDK-generated top-level `result` wrapper return on the normal path.
9. **Advertised schema shape** — `code_mode` and the delivery branch of `task` advertise the discriminated outcome union at the top level; tests must fail if `outputSchema.properties.result` reappears.
10. **Durability regression** — existing ADR 0004 behavior remains intact: one durable execution identity, normal task lifecycle, and retained completion behavior.
11. **TrackedTasks non-regression** — this change does not attempt to fix the connector projection bug and must not silently replace or redefine Task awareness semantics.

### Preferred seams

- **Primary seam:** existing public `code_mode` and `task(get)` behavior. Exact shape assertions are appropriate here because the public shape itself is the feature.
- **Secondary seam:** the existing Monty runtime behavioral test surface for the narrow `print()` versus final-expression semantic. Use this only where the public seam would make the cause unnecessarily indirect.
- Prefer existing lifecycle tests as prior art for inline/Task equivalence and durable Execution behavior.
- Prefer existing runtime tests as prior art for final expression, payload, capabilities, and `run_command` behavior.
- Do not add tests around new private helpers merely because the implementation is refactored.
- Avoid standard-library/private-state monkeypatching when the same behavior can be proven through the existing public seam.

### Acceptance rule

A green test suite is necessary but not sufficient. Final acceptance also requires inspecting both the advertised MCP `outputSchema` and the actual model-visible `structuredContent` from a live canary. `code_mode` must expose `kind` at the top level, must not advertise or return a top-level `result` wrapper, and must not replay accumulated `print()` output.

## Out of Scope

- TrackedTasks awareness missing from the current ChatGPT connector projection. This is reserved for ADR 0006.
- Bootstrap/model guidance overhaul for Monty versus CPython, CAPABILITIES, PAYLOAD, `asyncio.gather()`, and the new output idiom. This is reserved for ADR 0007.
- On-demand raw execution evidence recovery, raw-source inspection API, TTL decisions, or new storage. This is reserved for ADR 0008.
- Repo-wide `/grill-with-docs` terminology review or global naming cleanup. This is reserved for ADR 0009.
- Durable AGY worker top-level MCP surface work covered by ADR 0010.
- A general ordered event stream, transcript model, event bus, sequence schema, or live console streaming system.
- Removing Monty's `print()` language feature.
- Designing an emoji-delimited machine protocol.
- Redesigning Task list/awareness presentation beyond changes strictly required to keep the new outcome contract consistent.
- Changing ADR 0004 durability, worker claim, deadline, cancellation, publication, or retention semantics.
- Adding speculative fallback/recovery machinery for cases not required by the public contract.

## Further Notes

- ADR 0005 is the decision authority for this spec. Its forensic source preserves the original root-cause discussion and should be consulted when a future implementation choice appears to conflict with the local-reduction intent.
- The previous ADR 0005 refactoring narrative is not the authority for this work.
- The public contract is deliberately optimized for LLM consumption rather than human inspection. Human/operator diagnostics should remain available through separate, explicit recovery surfaces rather than normal-path metadata.
- Temporary MCP debug preview remains useful during implementation because it exposes the actual received response. It is an operating aid, not part of the runtime contract.
- Tickets 01–04 already decompose the original ADR 0005 work. Removing an SDK-generated top-level `result` wrapper remains ADR 0005 follow-up work because it violates the same LLM-facing output boundary; it does not require a new ADR.
