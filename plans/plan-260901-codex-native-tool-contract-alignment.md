# Codex-native Tool Contract Alignment

## Problem Statement

GPT Dive의 `code_mode`는 Monty 내부에서 capability를 정확히 사용할 수 있는 runtime registry와 static type checking을 이미 갖고 있지만, 모델은 outer `code_mode.code`를 작성한 뒤에야 `CAPABILITIES`를 볼 수 있다. 첫 호출에서는 capability name, arguments, structured return fields를 기억이나 Wiki guidance에 의존해 추측하게 된다.

ADR 0009는 public/model-facing vocabulary를 `delivery`, `error_code`, `console`, `run_command_evidence`로 정리했고 `kind`는 유지하기로 했다. ADR 0010은 Codex처럼 capability contract를 code 작성 전에 model-facing declaration으로 제공하고, schema/stub/validation/reflection이 하나의 definition에서 파생되도록 결정했다.

## Solution

```text
registered Python capability
        │
        ▼
single capability definition
├─ description
├─ parameter schema
├─ return schema
└─ callable
        │
        ├─ generated pre-call Python catalog
        ├─ Monty type-check stubs
        ├─ host validation
        └─ CAPABILITIES reflection

public Code Mode vocabulary
├─ delivery = auto | task
├─ kind = completed | task | error
└─ error.error_code
```

첫 rollout은 `run_command`의 typed return contract를 완성하면서 registry의 single-authority 구조와 pre-call catalog를 검증한다. 나머지 capability는 기존 호출 semantics를 유지하며, return schema가 아직 열린 경우 `Any`로 정직하게 표현한다.

## User Stories

1. As a model using Code Mode, I want capability declarations before writing code, so that I can make the first call without a discovery-only retry.
2. As a model reducing tool results locally, I want exact structured return fields, so that I do not guess keys such as `stdout`, `results`, or failure fields.
3. As a maintainer, I want catalog, static stubs, validation, and reflection derived from one capability definition, so that model-facing contracts cannot drift independently.
4. As a caller, I want `delivery` to describe response delivery rather than execution type, so that `auto/task` does not imply different Execution semantics.
5. As a caller, I want public errors to expose `error_code`, so that Monty source `code` and error classification are not overloaded.
6. As a runtime maintainer, I want durable worker/store protocol semantics preserved, so that model-facing naming cleanup does not trigger an unnecessary persistence migration.

## Implementation Decisions

### 1. Public naming migrates at the model-facing boundary

- Rename the public Code Mode input from `mode` to `delivery` with the same `auto | task` behavior and default.
- Do not provide a compatibility alias; the migration is a clean break.
- Keep `kind` as the response discriminator.
- Expose `error_code` in public error outcomes.
- Preserve the durable worker/ExecutionManager internal error classification field as `code`; translate it at the shared public outcome projection seam instead of migrating retained protocol/state.
- Apply the same public error projection to direct Code Mode completion and `task(get)` so they keep one outcome vocabulary.

### 2. CallableRegistry becomes the capability-definition owner

- Registration continues to accept the real host callable; do not create a second hand-authored signature table.
- At registration, derive and retain parameter schema, return schema, description, async/sync nature, and the callable as one definition.
- Existing external dispatch and cleanup ownership remain in the registry.
- `CAPABILITIES` remains runtime reflection/fallback metadata, but its signature/return information is generated from the same definition used by the pre-call catalog and stubs.

### 3. Reuse the pinned Pydantic AI schema pipeline

- Use the installed Pydantic AI callable schema generation path to derive parameter validation schema and return JSON Schema from Python annotations.
- Use `FunctionSignature.from_schema()` and its type-definition renderer for Python model-facing declarations instead of writing a new JSON-Schema-to-Python generator.
- GPT Dive already pins the relevant Pydantic AI/Harness dependency, so the upstream schema API is treated as a pinned integration seam and protected by focuse
… output truncated …
lue fallback tests. Test only the clean public migration, single-authority generation, typed result validation, and preserved runtime behavior.

## Acceptance

- Public MCP schema advertises `delivery` and never advertises `mode`.
- Public error outcomes advertise and return `error_code`; `kind` remains the discriminator.
- Durable worker/store error protocol does not require migration.
- Outer `code_mode` description contains generated Python declarations before code execution.
- `run_command` exposes a typed return declaration generated from the same schema authority used for host validation.
- `CAPABILITIES`, Monty stubs, and pre-call catalog cannot drift by maintaining separate signature definitions.
- Focused public-surface and Code Mode runtime tests pass.
- Full relevant test suite, Ruff, Pyright, and `git diff --check` pass.

## Out of Scope

- V8/JavaScript or Codex cell lifecycle.
- `tools.*` namespace migration.
- Deferred tool loading.
- Compatibility aliases for `mode` or error `code`.
- Durable Execution/Task/output/evidence redesign.
- Typed migration of every capability in the first rollout.
- Automatic repair/fallback for invalid capability results.
- Changing the separate ADR 0008 run-command summary presentation beyond wording required by the new public vocabulary.

## Further Notes

- ADR 0009 and ADR 0010 are the decision authorities for this plan.
- Detailed Codex/Pydantic source evidence remains in the existing Codex-native research document rather than being duplicated here.
- The neighboring run-command summary plan remains a separate implementation concern; only stale public vocabulary should be reconciled if this migration makes it incorrect.

---

# Tickets

## 01 — Clean public Code Mode vocabulary

**What to build:** Expose the accepted ADR 0009 vocabulary end to end: callers use `delivery`, public error outcomes use `error_code`, `kind` remains the discriminator, and both direct Code Mode and `task(get)` share the same public error shape without migrating the durable worker/store protocol.

**Blocked by:** None — can start immediately.

**Status:** completed

- [x] Public MCP input schema exposes `delivery=auto|task` and does not expose legacy `mode`.
- [x] Direct Code Mode and `task(get)` public errors expose `error_code`; internal durable error `code` remains valid.
- [x] Existing auto/task Execution and Task publication behavior remains regression-green.

## 02 — Generate the pre-call capability contract

**What to build:** Make the registered callable definition generate parameter/return schemas, Monty stubs, `CAPABILITIES` reflection, and the outer pre-call Python catalog from one authority; prove the full path with a typed `run_command` result.

**Blocked by:** 01 — Clean public Code Mode vocabulary.

**Status:** completed

- [x] Model-visible Code Mode description contains generated enabled-capability declarations before code execution.
- [x] Registry reflection, Monty stubs, and pre-call catalog derive from one capability definition rather than parallel signature tables.
- [x] `run_command` has a closed typed return schema and invalid host result shapes fail before entering Monty.
- [x] Existing `result["stdout"]` local reduction remains unchanged.
