---
title: ADR - Code Mode Output Contract as a Local Reduction Boundary
created: 2026-08-29
updated: 2026-08-31
type: decision
status: accepted
---

# ADR 0005 — Code Mode Output Contract: Local Reduction, Explicit Console

> 이 문서는 기존 `ADR 0005 — Post-Renewal Architecture Simplification`을 같은 번호에서 전면 교체한다.
> 이전 문서는 리팩토링 작업 내역을 기록했지만, 실제 ADR 작성 회의의 핵심 문제와 결정 맥락을 놓쳤다.
> 복원 근거는 `source-adr-0005-root-cause.md`에 보존한다.
>
> Execution/Task lifecycle의 권위는 계속 ADR 0004다. 이 ADR은 **프로그램 출력 의미와 model-context 경계**만 결정한다.

## 결정 요약

Code Mode를 **programmable local reduction boundary**로 취급한다.

```text
independent capabilities
        ├─ A ─┐
        ├─ B ─┼─ asyncio.gather()
        └─ C ─┘
             ↓
      large values stay local
             ↓
      filter / combine / compare
             ↓
      optional print() progress
             ↓
       final expression
             ↓
    compact caller/model result
```

의미를 다음처럼 분리한다.

```text
capability return
    = Monty 내부 프로그램 데이터

print()
    = 명시적 console / progress

final expression
    = caller/model에게 반환할 프로그램 결과

Execution / Task
    = 프로그램의 durable lifecycle / awareness
```

이 네 의미는 서로 대체하거나 자동 복제하지 않는다.

## 최우선 최적화 대상: LLM-facing contract

사용자는 이 output을 직접 들여다보는 것을 목표로 하지 않는다. 이 surface의 최우선 소비자는 **LLM AI**다. 따라서 목표는 사람이 보기에 짧거나 예쁜 형식이 아니라, **복잡성이 커질수록 모델의 분기·필드 선택·후속 호출 오류가 증가할 가능성을 낮추는 것**이다.

요구사항은 다음과 같다.

- model-visible metadata는 **엄청 간소화**한다. 정상 경로의 판단에 필요하지 않은 label, backend, pid, timestamp, elapsed 같은 정보는 싣지 않는다.
- `execution_id`는 남긴다. 최종 `output`이 원하는 결과가 아니거나 이상할 때 retained result/raw artifact를 다시 조회할 수 있는 recovery/debug handle이기 때문이다.
- `result.result.result` 같은 JSON nesting과 의미가 겹치는 wrapper를 만들지 않는다. **모델이 실제로 받는 MCP structured output의 최상위도 outcome object 자체여야 하며**, SDK/host projection이 의미 없는 `{"result": ...}` 한 겹을 자동 추가하는 경우에도 이를 정상 contract로 승인하지 않는다. LLM이 실제 결과까지 도달하기 위해 불필요한 경로를 추론하게 하지 않는다.
- 짧은 이름보다 **일관되고 명시적인 vocabulary**를 우선한다. `id` 대신 모든 runtime surface에서 `execution_id`를 사용한다.
- 사람이 보기에는 다소 중복처럼 보여도 `kind`는 유지한다. 명시적 discriminator는 LLM이 결과 shape를 추론하지 않고 바로 분기하게 해 오류 가능성을 낮춘다.
- machine contract에 별도 emoji delimiter/text framing protocol을 만들지 않는다. 눈에 잘 띄는 `🔵🟢🟣 ... 🟣🟢🔵` 같은 표식은 debug/presentation layer에서는 쓸 수 있지만, runtime parser가 알아야 하는 두 번째 protocol로 만들지 않는다.
- 최종 `output`의 내부 형식은 Monty program이 목적에 맞게 string/list/dict 등으로 조립한다. Runtime은 그 값을 다시 해석하거나 장식하지 않는다.

이를 한 문장으로 요약하면:

```text
one discriminator
+ one identifier vocabulary
+ one output vocabulary
+ minimum metadata
+ no duplicate semantic wrappers
```

## 왜 필요한가

Code Mode의 중요한 목적은 여러 capability를 로컬에서 실행하고, 큰 중간값을 model context에 넣지 않은 채 Monty 안에서 선별·조합한 뒤 작은 결과만 반환하는 것이다.

그런데 현재 `code_runtime.py`는 Monty의 `print_callback`을 `CollectString()`에 누적한 뒤 실행이 끝나면 최종 결과에 다시 붙인다.

```python
capture = CollectString()
...
print_callback=capture
...
result = {"result": state.output}
if capture.output:
    result["stdout"] = capture.output
```

이 구조는 서로 다른 두 의미를 하나의 최종 응답으로 합친다.

```text
실행 중
    print("A")
    await capability()
    print("B")

원래 의미
    A → capability → B
    console/progress의 발생 순서

기존 final projection
    {
      result: <final value>,
      stdout: "A\nB\n"
    }
```

문자열 내부 순서는 남지만, `print()`가 **실행 중 console event**였다는 의미는 사라지고 종료 시점의 두 번째 payload처럼 보인다.

더 큰 문제는 context pollution이다.

```python
data = await read_file("huge.md")
print(data)
{"summary": summarize(data)}
```

이 경우 프로그램은 이미 큰 데이터를 로컬에서 요약했는데도, 누적 `stdout` 때문에 원본이 다시 model context로 들어갈 수 있다.

```text
large capability result
        ↓
     Monty local
        ↓
 compact summary selected
        ↓
     final result

하지만 print(data)까지 누적되면
        ↓
large original + compact summary
        ↓
model context 중복
```

이는 Code Mode가 제공하려던 context 절감 효과를 뒤집는다.

또한 `run_command()` 자체가 `stdout` 필드를 가진 dict를 반환할 수 있어, 바깥의 누적 `stdout`과 의미가 겹친다.

```text
result.stdout
    = capability가 반환한 shell stdout

outer stdout
    = Monty print() 누적 문자열
```

같은 이름이 서로 다른 개념을 가리키는 것도 계약을 불명확하게 만든다.

## 결정

### 1. Capability return은 기본적으로 Monty 내부에 머문다

Capability의 전체 반환값을 자동으로 console이나 최종 응답에 복제하지 않는다.

```python
data = await read_file(...)
# data stays local unless the program explicitly selects or prints it
```

필요한 데이터만 최종 expression으로 선택한다.

```python
data = await read_file(...)
{"head": data[:500]}
```

이 원칙이 Code Mode의 context 절감 경계다.

### 2. `asyncio.gather()`는 의도된 first-class idiom이다

서로 독립적인 capability는 병렬 실행할 수 있어야 한다.

```python
files, git, readme = await asyncio.gather(
    list_directory("."),
    run_command("git status --short"),
    read_file("README.md", limit=80),
)

{
    "dirty": bool(git["stdout"].strip()),
    "file_count": len(files.splitlines()),
    "readme_head": readme[:500],
}
```

핵심은 단순한 병렬화가 아니다.

```text
parallelize locally
      ↓
compose locally
      ↓
return selectively
```

중간 결과의 크기와 개수는 최종 model-context 크기를 결정하지 않아야 한다.

### 3. `print()`는 console / progress다

`print()`는 프로그램이 **명시적으로 외부에 보여주고 싶은 중간 관찰이나 진행 상황**을 표현한다.

```python
result = await read_file(...)
print("README loaded")
```

전체 값을 보여주고 싶다면 그것도 명시적 선택이다.

```python
print(result)
```

하지만 `print()` 결과를 실행 종료 시 자동으로 두 번째 durable result payload로 재생하는 것은 이 의미와 맞지 않는다.

Console의 transport 방식은 이 ADR이 고정하지 않는다. 이후 TUI/ACP/Web client가 live streaming을 요구하면 발생 순서를 보존하는 transport를 별도로 설계할 수 있다.

### 4. Final expression이 정상적인 프로그램 결과다

Monty의 마지막 expression은 caller/model이 받아야 할 **선별된 durable program result**다.

```text
final Monty expression
        ↓
retained Execution result
        ├─ inline delivery
        └─ task(get) delivery
```

Inline 완료와 나중의 `task(get)`은 전달 시점만 다르며, 같은 Execution의 같은 프로그램 결과를 보여야 한다.

### 5. Output semantics와 lifecycle semantics를 분리한다

다음은 서로 독립적인 관심사다.

```text
program result        final expression
console/progress      print()
Execution lifecycle   accepted/running/completed/failed/...
Task awareness        published/dismissed
```

Task publication 여부가 프로그램 결과의 의미를 바꾸지 않는다.

TrackedTasks awareness는 program `output`과 별개다. ADR 0006은 model-visible ordinary result에 top-level sibling `tracked_tasks`를 추가할 수 있지만, 그 field를 `output` 내부에 넣거나 primary outcome을 `result` wrapper로 다시 감싸지 않는다.

이 ADR의 compactness 요구는 `code_mode` / `task(get)` normal outcome에 한정된다. 별도 Task-awareness surface인 explicit `task(list)`의 detailed Task fields나 passive TrackedTasks의 elapsed 표시를 축약·제거하는 근거로 사용하지 않는다.

### 6. Output bounding은 final-result seam에서 한다

큰 intermediate capability result는 Monty가 reduction을 수행할 수 있도록 로컬에서 사용할 수 있어야 한다.

따라서 개별 capability 결과마다 Web-facing truncation/spill semantics를 강제하지 않는다.

```text
capability outputs
      ↓
Monty local computation
      ↓
final successful result
      ↓
optional bounded spill / preview adapter
      ↓
caller/model
```

최종 결과 자체가 지나치게 크면 `docs/pydantic/tool-output-limits.md`의 final-output seam처럼 정확한 원본을 로컬에 보존하고 작은 preview만 반환하는 정책을 적용할 수 있다.

그 정책은 inline result와 동일 Execution의 `task(get)`에 동일하게 적용되어야 한다.

### 7. Public outcome은 LLM이 한 번에 분기할 수 있는 최소 union으로 통일한다

`code_mode`와 `task(get)`은 서로 다른 return 언어를 만들지 않는다. 둘 다 동일한 outcome vocabulary를 사용한다.

```text
CodeModeOutcome
├─ completed  → execution_id + output
├─ task       → execution_id + state
└─ error      → execution_id + code + message
```

#### Completed

```json
{
  "kind": "completed",
  "execution_id": "abc123",
  "output": {
    "answer": 42
  }
}
```

`output`은 **final Monty expression 자체**다. 내부에 다시 `result`, `output`, `data` wrapper를 자동 추가하지 않는다.

이 섹션의 JSON은 primary outcome fields를 설명한다. ADR 0006의 cross-cutting `tracked_tasks`는 실제 model-visible ordinary result에서 top-level sibling으로 추가될 수 있으며, `output` 의미에는 포함되지 않는다.

Monty가 string을 마지막 expression으로 반환하면:

```json
{
  "kind": "completed",
  "execution_id": "abc123",
  "output": "Everything looks good."
}
```

Monty가 list를 조립하면 그대로 list다.

```json
{
  "kind": "completed",
  "execution_id": "abc123",
  "output": [
    "=== a ===",
    {"value": 123},
    "=== b ==="
  ]
}
```

#### Task

```json
{
  "kind": "task",
  "execution_id": "abc123",
  "state": "running"
}
```

`kind`가 lifecycle-aware outcome임을 명시하고, `state`는 현재 Execution 상태만 말한다. 정상 task outcome에 backend/pid/timestamp/elapsed 같은 진단 metadata를 싣지 않는다.

#### Error

```json
{
  "kind": "error",
  "execution_id": "abc123",
  "code": "runtime_error",
  "message": "Monty execution failed."
}
```

정상 error surface는 원인 분류와 사람이/모델이 이해할 message까지만 제공한다. 더 깊은 traceback, cleanup detail, retained raw evidence는 `execution_id`를 통해 필요할 때 조회한다.

`label`은 completed/error primary outcome에서 제거한다. 호출 직전에 이미 알고 있는 정보를 반복하기 때문이다. 여러 Execution을 구분해야 하는 automatic `tracked_tasks`와 `task(list)` awareness surface에서는 label이 여전히 가치가 있으므로 유지한다.

이 public contract에서 **모델이 실제로 받는 structured output 자체가 outcome object 한 겹**이어야 한다. 따라서 다음 shape는 contract 위반이다.

```json
{
  "result": {
    "kind": "completed",
    "execution_id": "abc123",
    "output": 42
  }
}
```

현재 사용하는 MCP SDK 2.0.0은 generic/Union return annotation을 structured output으로 변환할 때 `{"result": value}`를 자동 추가할 수 있다. 이 SDK 편의 wrapper는 transport implementation detail일 뿐 model-facing semantic value가 없으므로 public contract로 승인하지 않는다.

따라서 구현은 특정 Pydantic helper 자체가 아니라 **advertised `outputSchema`와 실제 `structuredContent`가 outcome object를 top-level에 직접 노출한다는 결과**를 만족해야 한다. `RootModel` 같은 object model은 가능한 구현 수단일 뿐이며, 이 ADR이 고정하는 public contract 자체는 아니다.

이 결정은 새 semantic wrapper를 추가하는 것이 아니라 **SDK-generated wrapper를 제거하기 위한 public projection constraint**다.

## 폐기한 대안

### 모든 capability return을 자동 출력

폐기한다. Code Mode를 다시 tool-result context dump로 만든다.

프로그램이 결과를 계산에만 사용할지, 일부만 반환할지, console에 보여줄지는 Monty code가 선택해야 한다.

### 누적 `print()`를 최종 `stdout` 필드로 계속 반환

폐기한다. Console/progress와 final result의 의미를 다시 합치며, 큰 intermediate data를 model context에 재주입할 수 있다.

### 지금 바로 범용 ordered event/transcript system 도입

폐기한다. 실제 live client 요구보다 앞서 event bus, sequence schema, persistence를 만들 필요가 없다.

현재 필요한 것은 먼저 **semantic contract를 바로잡는 것**이다.

### TrackedTasks 누락 문제와 함께 해결

폐기한다. TrackedTasks는 Task awareness 문제이고, 이 ADR의 program output 문제와 다른 경계다.

서버 middleware가 append한 awareness가 현재 ChatGPT connector projection에서 보이지 않는 현상은 별도 버그로 추적한다.

### SubAgent의 ToolOutputLimits를 모든 Code Mode capability에 적용

폐기한다. SubAgent와 Code Mode의 reduction seam이 다르다.

Code Mode는 큰 intermediate value를 Monty에서 직접 처리할 수 있어야 하므로 최종 program result 이전에 이를 Web-facing preview로 바꾸면 핵심 이점을 잃는다.

## 귀결

- 모델은 capability의 큰 결과를 변수에 유지한 채 필요한 부분만 가공해서 반환할 수 있다.
- `asyncio.gather()`로 latency를 줄여도 model-context 사용량이 capability 결과 총량에 비례하지 않는다.
- `print()`는 명시적 관찰 행위가 되고, 정상적인 durable result와 구분된다.
- public Code Mode projection은 더 이상 `CollectString` capture를 completed outcome의 `stdout`으로 재생하지 않으며, final expression만 `output`으로 노출한다.
- inline delivery와 Task delivery가 같은 프로그램 결과 계약을 공유한다.
- 이후 TUI/ACP/Web streaming이 필요해도 final result contract를 다시 뜯지 않고 별도 console transport를 추가할 수 있다.

## 범위 밖 후속 작업

### ADR 0006 — TrackedTasks connector projection

현재 서버 middleware는 primary `CallToolResult`에 TrackedTasks `TextContent`를 append하는 것으로 확인됐지만, ChatGPT connector output에서는 해당 awareness가 보이지 않았다.

이 현상은 별도 조사한다. 이 ADR의 output redesign 이유로 사용하지 않는다.

### ADR 0007 — Bootstrap / model guidance

모델에게 다음 실행 idiom을 명확히 안내하는 일은 중요하지만 별도 작업이다.

```text
Monty != arbitrary CPython
CAPABILITIES = supported host boundary
long/quoted data → PAYLOAD
independent work → asyncio.gather()
print() → console/progress
final expression → compact result
```

### ADR 0008 — Raw execution evidence recovery

정상 경로는 compact result만 model context에 넣는다.

결과가 이상해 보일 때는 `execution_id`를 recovery handle로 사용한다. Evidence의 저장·discovery·selected-read 방식은 ADR 0008이 소유한다.

### Temporary debug preview

Output contract를 구현·검증하는 동안 MCP preview는 실제 Monty code와 실제 received output을 보여주는 debug-oriented 형식을 유지한다. 동일 정보를 CALL/INPUT 같은 두 표현으로 중복하지 않는다.

이 운영 규칙의 authority는 `~/wiki/workflow/code-mode-reminder.md`다.

### ADR 0009 — Runtime terminology / naming boundary

`/grill-with-docs` 수준의 runtime 전체 용어 정리는 이번 ADR 구현 scope에서 제외한다. 현재 output contract를 고치는 작업과 동시에 전역 terminology까지 건드리면 변경 범위와 검증 부담이 지나치게 커진다.

다만 **이번 수정 경로에서 직접 만지는 이름은 적극적으로 일관화한다.** 새 이름을 추가하면서 옛 이름을 병존시키지 않는다.

- `execution_id` — durable Execution의 유일한 public identifier. 같은 의미를 `id`, `task_id`, `job_id`로 새로 표현하지 않는다.
- `kind` — public outcome discriminator (`completed | task | error`).
- `output` — final Monty expression이 caller/model에게 전달된 값. final program value를 뜻하는 `result.result` 계층은 제거한다.
- `state` — 아직 terminal output이 없는 Execution의 lifecycle state.
- `label` — Task awareness에서 사람이 여러 실행을 구분하기 위한 이름. completed program output metadata가 아니다.
- `print()` / console — final `output`과 별도인 진행/관찰 channel.

이 범위를 넘어선 repo-wide naming cleanup은 별도 terminology 작업으로 남긴다.

## 구현 불변조건


후속 구현과 리뷰는 최소한 다음을 만족해야 한다.

- final Monty expression이 정상적인 durable program result이며 public field 이름은 `output`이다.
- completed primary outcome fields는 `kind + execution_id + output`을 기본 shape로 하고, final program value를 `result.result` 같은 중첩으로 감싸지 않는다. ADR 0006의 cross-cutting `tracked_tasks` sibling metadata는 별도다.
- MCP tool의 advertised `outputSchema`와 실제 live `structuredContent` 모두 outcome object를 top-level에 직접 노출해야 하며, 최상위 `result` property/wrapper를 허용하지 않는다.
- task outcome은 `kind + execution_id + state`, error outcome은 `kind + execution_id + code + message`의 동일 union vocabulary를 사용한다.
- completed/error primary outcome에 `label`, `stdout`, backend, pid, timestamp, elapsed 등 판단에 불필요한 metadata를 추가하지 않는다. ADR 0006의 `tracked_tasks`는 별도 awareness metadata다.
- `execution_id`는 compact output이 이상할 때 retained/raw evidence를 조회하는 recovery/debug handle로 항상 유지한다.
- `print()`가 자동으로 두 번째 final payload가 되지 않는다.
- 큰 intermediate capability result가 Monty 내부에 머물 수 있다.
- 독립 capability 호출을 `asyncio.gather()`로 병렬화해도 선택된 최종 결과만 model context로 보낼 수 있다.
- inline 완료와 `task(get)`은 동일한 outcome vocabulary와 retained result 의미를 가진다.
- Execution lifecycle과 Task awareness가 output semantics를 바꾸지 않는다.
- final-output bounding이 필요하면 intermediate capability가 아니라 final result seam에 적용한다.
- TrackedTasks projection의 carrier/refresh semantics는 ADR 0006이 소유한다. `tracked_tasks`를 program `output` 내부에 섞지 않는다.

## 참고 문서

- `docs/runtime/adr/source-adr-0005-root-cause.md`
  - 이 ADR을 다시 쓰게 만든 원본 회의, live observation, Git-history 조사, 결정 변화의 forensic authority.
- `docs/runtime/adr/0004-always-durable-code-mode-runtime.md`
  - Execution/Task lifecycle, durability, publication, deadline의 decision authority. 이 ADR은 그 lifecycle을 변경하지 않는다.
- `src/gpt_dive/code_runtime.py`, `src/gpt_dive/app.py`
  - Monty final-expression capture와 public `output` projection / console separation의 구현 authority.
- `docs/pydantic/tool-output-limits.md`
  - large intermediate value는 Monty에 유지하고 final output seam에서만 spill/preview를 적용한다는 관련 정책.
- `docs/pydantic/code-mode.md`
  - 현재 Monty/capability programming contract의 사용자-facing 상세 설명.
