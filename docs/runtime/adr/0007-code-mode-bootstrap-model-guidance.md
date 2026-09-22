---
title: ADR - Code Mode Bootstrap and Model Guidance
created: 2026-08-30
updated: 2026-08-31
type: decision
status: proposed
---

# ADR 0007 — Code Mode Bootstrap and Model Guidance

> Runtime semantics는 ADR 0004/0005, awareness는 ADR 0006이 소유한다. 이 ADR은 **LLM이 그 계약을 실제 행동으로 지키게 만드는 guidance 책임 분리**를 결정한다.

## 결정 요약

Guidance를 하나의 거대한 prompt에 몰지 않는다.

```text
outer MCP schema / description → public call authority
bootstrap                      → fresh-session mental model
Wiki capability map            → primitive 선택
live CAPABILITIES              → exact inner signature/return authority
periodic reminder              → drift 방지 재강조
repo docs                       → implementation/maintenance detail
```

Code Mode의 핵심 mental model:

> **parallelize locally, compose locally, return selectively.**

```text
Monty != arbitrary CPython
        ↓
registered capabilities = host boundary
        ↓
rich intermediate values stay local
        ↓
filter / combine / compare
        ↓
final expression = compact model result
```

## 왜 필요한가

긴 세션에서는 이미 읽은 규칙보다 익숙한 CPython/shell 습관이 다시 이길 수 있다. 특히 ADR 0005 이후 Runtime은 raw capability result를 자동 pruning하지 않으므로 **마지막 expression을 모델이 직접 잘 설계해야 한다.**

```python
# ❌ only stdout이 필요한데 전체 object 반환
cmd = await run_command("git status --short")
cmd

# ✅ local reduction
cmd = await run_command("git status --short")
cmd["stdout"]
```

## 권위 계층

### Outer MCP contract

`bootstrap`, `code_mode`, `task`, `wsl_exec`의 input/output은 current MCP schema가 authority다. 옛 `timeout`, lifecycle action, field를 기억으로 만들지 않는다.

### Inner capability contract

Exact name/signature/default/return은 live `CAPABILITIES`가 authority다.

중요:

```text
CAPABILITIES = metadata/signature discovery
CAPABILITIES != callable mapping
```

```python
# ❌
await CAPABILITIES["run_command"]("git status")

# ✅
await run_command("git status")
```

Wiki는 routing/idiom을, repo docs는 구현 상세를 소유한다.

## 모델이 반드시 아는 최소 contract

### 1. Monty는 arbitrary CPython이 아니다

Host I/O와 shell은 registered capability를 사용한다.

```text
open() / subprocess / os.system / arbitrary import
→ 기본값으로 사용하지 않음

file I/O → FileSystem capabilities
shell    → run_command
```

불확실하면 추측하지 말고 live contract를 본다.

### 2. `code`는 logic, `PAYLOAD`는 opaque data

Multiline/quoting-sensitive input은 outer `payload` string으로 보내고 Monty 안에서 `PAYLOAD`를 사용한다.

### 3. Dependency는 sequential, independent work만 gather

```python
status, readme = await asyncio.gather(
    run_command("git status --short"),
    read_file("README.md"),
)
```

Semantic dependency가 있으면 순차 await한다.

### 4. Capability return은 local intermediate data

전체 반환값을 기본적으로 model context에 내보내지 않는다.

```python
cmd = await run_command("git branch --show-current")
cmd["stdout"].strip()
```

여러 결과는 Monty에서 작은 object로 조립한다.

### 5. Final expression이 durable program result

마지막 expression은 다음 reasoning step에 필요한 최소 정보로 의도적으로 만든다. Inline completion과 `task(get)`은 같은 retained output을 전달한다.

### 6. `print()`는 durable result가 아니다

`print()` 의미는 console/progress다. 현재 ChatGPT path가 live console delivery를 보장하지 않아도 필요한 정보는 final expression에 둔다.

### 7. Task lifecycle은 Monty 밖이다

```text
launch/program       → code_mode
automatic awareness  → ordinary result.tracked_tasks
explicit inspection  → task(list) detailed TaskView
result pickup        → task(get)
cancel/dismiss       → task
```

ADR 0006 채택 후 background rediscovery는 ordinary tool result에 항상 포함되는 `tracked_tasks`를 사용한다. 모델이 polling cadence나 다음 `task(list)` 시점을 기억하는 것을 정상 workflow의 전제로 두지 않는다. Terminal Task를 발견하면 결과가 아직 유용할 때 `task(get)`으로 읽고, 처리한 뒤 `task(dismiss)`한다.

### 8. Failure 뒤에는 기억으로 retry하지 않는다

```text
failure
→ ERROR_CASE
→ current schema / CAPABILITIES / source
→ corrected call
```

`ERROR_CASE.md`는 failure-triggered on-demand memory로 유지한다.

## Guidance surface 책임

| Surface | 책임 | 넣지 않는 것 |
|---|---|---|
| MCP description/instructions | environment + tool routing + live-contract-first | signature catalog, 긴 tutorial |
| Bootstrap | fresh-session mental model + 핵심 operating rules | repo implementation detail |
| CAPABILITIES map | need → primitive 선택 | exact runtime authority |
| live CAPABILITIES | exact inner contract | workflow prose |
| Code Mode reminder | drift가 잦은 invariant 재강조 | exact signature catalog |
| repo docs | implementation/maintenance | 매 세션 preload |

## Preload 결정

대표 ordering:

```text
intro
→ USER_RULES
→ GPT Dive routing
→ Code Mode operating guide
→ CAPABILITIES selection map
→ search navigation
→ code-mode reminder
→ skills navigation
```

`code-mode-CAPABILITIES-ref.md`는 useful on-demand reference로 남기되 **fresh-session preload에서는 제거**한다. Exact contract는 live `CAPABILITIES`가 이미 소유한다.

`workflow/code-mode-reminder.md`는 bootstrap의 late re-anchor와 periodic reminder가 함께 재사용한다. 거의 같은 reminder 문서를 새로 만들지 않는다.

## 폐기한 대안

| 대안 | 폐기 이유 |
|---|---|
| 모든 guidance를 MCP instructions에 몰기 | 항상 붙는 prompt 비대화 |
| exact signatures를 bootstrap에 고정 | live registry와 두 번째 authority 생성 |
| Runtime이 raw result 자동 pruning | intent를 추측해 legitimate fields 제거 가능 |
| `print()`를 final fallback으로 사용 | console/result 의미 재혼합 |
| 모든 작업 gather | dependency correctness 훼손 |
| ERROR_CASE 항상 preload | 정상 context 비용 대비 가치 낮음 |
| background completion을 `task(list)` polling으로 기억 | automatic TrackedTasks 목적을 훼손하고 모델 기억에 correctness를 의존 |

## 귀결

- 모델이 Code Mode를 "Python shell"보다 local reduction runtime으로 이해하게 한다.
- stale exact signature duplication을 줄인다.
- Raw capability object의 불필요한 context 유입을 guidance 단계에서 줄인다.
- 모델은 ordinary result의 `tracked_tasks`를 자동 completion-awareness surface로 해석하고, `task(list)`를 polling obligation으로 사용하지 않는다.
- Runtime은 guidance 실패를 보상하는 자동 repair/pruning machinery를 추가하지 않는다.

## Non-goal

- Monty runtime/capability schema 변경
- awareness transport 변경 — ADR 0006
- raw evidence API — ADR 0008
- naming cleanup — ADR 0009
- prompt만으로 compliance를 완전히 보장

## 구현 불변조건

- outer schema / live `CAPABILITIES`가 각각 exact authority다.
- Monty != CPython, PAYLOAD, dependency/gather, local reduction, final expression을 bootstrap에서 명시한다.
- `CAPABILITIES[...]`를 callable로 가르치지 않는다.
- raw `run_command()` object 전체 반환을 default example로 쓰지 않는다.
- `print()`를 durable result로 가르치지 않는다.
- Task lifecycle action은 top-level `task`가 소유하고, automatic awareness는 ordinary result의 `tracked_tasks`가 소유한다.
- background completion discovery가 모델의 `task(list)` polling 기억에 의존하지 않도록 가르친다.
- exact CAPABILITIES ref를 preload authority로 사용하지 않는다.
- failure 후 ERROR_CASE + current contract 확인을 안내한다.

## 참고 문서

- `docs/runtime/adr/0004-always-durable-code-mode-runtime.md`
- `docs/runtime/adr/0005-code-mode-output-contract.md`
- `docs/runtime/adr/0006-tracked-tasks-connector-projection.md`
- `docs/pydantic/code-mode.md`
- `~/wiki/bootstrap/intro.md`, `~/wiki/bootstrap/preload.json`
- `~/wiki/workflow/code-mode.md`
- `~/wiki/workflow/code-mode-CAPABILITIES-map.md`
- `~/wiki/workflow/code-mode-reminder.md`
- `~/wiki/ERROR_CASE.md`