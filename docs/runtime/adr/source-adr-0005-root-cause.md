# Source — ADR 0005 Root Cause Session

> Forensic source note for reconstructing or replacing `docs/runtime/adr/0005-post-renewal-simplification.md`.
>
> Target repository path requested by the user:
> `docs/runtime/adr/source-adr-0005-root-cause.md`
>
> This file is intentionally more detailed than an ADR. It preserves the session evidence, mistakes,
> observed runtime behavior, and decision evolution that a concise ADR should be derived from.

## 0. Provenance and boundaries

### Purpose

This source exists because the user re-opened ADR 0005 and judged that it had missed the core problem.
The session then reconstructed the actual root issue from live `@u26` behavior, current source, and Git history.

The most important recovered point is:

```text
The problem was not primarily "TrackedTasks".

The deeper problem was the Code Mode return/output contract:

Monty runtime
    ├─ intermediate capability results
    ├─ print() / console-like progress
    ├─ asyncio.gather() concurrency
    └─ final expression
             ↓
GPT Dive projection
             ↓
model-visible context

The projection did not preserve the originally intended separation cleanly.
```

### Evidence classes used below

- **DIRECT** — visible user/assistant message or actual tool response in this session.
- **SOURCE** — current source or Git-history evidence retrieved during this session.
- **AGY** — read-only Git-history investigation performed by `agy_worker`.
- **INFERENCE** — conclusion drawn from the observed behavior; not claimed as independently proven.
- **DECISION** — direction explicitly accepted by the user during the session.

### Explicit exclusions

This document does **not** contain hidden system/developer prompts or raw private chain-of-thought.
Where useful, it records only user-visible reasoning summaries and the observable evidence behind them.

At the end of the session, the `@u26` connector became unavailable. Therefore the final requested write to
the user's live `~/gpt-dive` worktree could not be completed in that turn. The forensic content itself was
still produced as a standalone file for later placement at the target path.

---

# 1. Session context before the root-cause discussion

## 1.1 Harness direction was already being reconsidered

The broader architectural discussion immediately before the output investigation had established:

```text
user
  ↓
thin chat UI / TUI / ACP client
  ↓
~/gpt-dive
  ↓
root Agent / Session runtime
  ├─ provider/model registry
  ├─ conversation/session state
  ├─ tool loop
  ├─ code_mode
  └─ task
```

The assistant initially misunderstood this and suggested an external harness such as OpenCode/Goose.
The user corrected that interpretation:

```text
~/gpt-dive is already a harness.
The intended direction is to make GPT Dive itself the main/root harness,
not to put another harness in front of it.
```

Relevant current-source facts retrieved earlier in the session:

- `src/gpt_dive/model_registry.py`
  - already owns multiple provider/model aliases.
- `src/gpt_dive/model_call.py`
  - already constructs `pydantic_ai.Agent(build_model(...))`.
- current public MCP surface:
  - `bootstrap`
  - `code_mode`
  - `task`
- `experiments/conduit_acp_stdio`
  - already demonstrated an ACP-facing projection path.

This matters because the output contract being discussed is not merely a tool-return cosmetic issue.
If GPT Dive becomes the root harness, this contract becomes part of the harness's central execution UX.

---

# 2. TrackedTasks investigation that exposed the deeper problem

## 2.1 Original user memory

The user remembered the original TrackedTasks design as:

```text
original output
+
Tracked Task awareness
  = background work + current state
```

This was not supposed to replace the normal result.

Historical plan evidence found in the session:

```text
plans/plan-260824-task-execution-awareness-v1.md

ordinary @dive tool return
→ original structured result unchanged
→ compact TrackedTasks TextContent appended
```

Historical ADR evidence also said:

```text
TrackedTasks is additive metadata,
not a replacement for Code Mode output.
```

## 2.2 Current source still implements additive middleware

Current source inspection showed `_tracked_tasks_middleware` behavior equivalent to:

```python
awareness = TextContent(type="text", text=f"\n\n{text}\n")

return result.model_copy(
    update={"content": [*result.content, awareness]}
)
```

That is important:

```text
primary CallToolResult
    +
additional TextContent
```

not:

```text
primary result replaced by task metadata
```

## 2.3 Live observation: ChatGPT connector did not show the appended awareness

The assistant launched a background AGY history investigation:

```text
label: Trace pre-TrackedTasks return design
execution_id: 3Qf5hA
mode: task
```

Initial return:

```json
{
  "result": {
    "kind": "task",
    "execution_id": "3Qf5hA",
    "label": "Trace pre-TrackedTasks return design",
    "state": "accepted"
  }
}
```

The user then asked to "poke" it.

`task(get)` returned:

```json
{
  "result": {
    "action": "get",
    "task": {
      "execution_id": "3Qf5hA",
      "label": "Trace pre-TrackedTasks return design",
      "state": "running",
      "elapsed_seconds": 65
    },
    "ready": false,
    "unavailable": false,
    "result": null
  }
}
```

The user immediately noticed the important integration symptom:

> `output 에 전혀 Tracked Task 가 안 나오네?`

The observed model-visible `@u26.code_mode` response contained the structured result but no appended
TrackedTasks text.

The assistant summarized the observed projection as:

```text
gpt-dive MCP raw CallToolResult
├─ structuredContent  ───────────────► visible to the assistant
└─ content[]
    └─ TrackedTasks TextContent ─────► not visible in current connector output
```

**INFERENCE, not fully proven at transport level:** the current ChatGPT connector/projection appears to
surface structured content while dropping or hiding the appended `TextContent`.

This issue was later explicitly moved **out of scope** for the new ADR work. It remains a separate bug.

---

# 3. Live execution artifacts and AGY tail investigation

## 3.1 Finding the execution spool

The user asked whether the running AGY task could be inspected using `tail -10`.

A first filename search for `3Qf5hA` found nothing.

Source search then found the runtime artifact layout:

```text
~/.local/state/gpt-dive/
├─ runtime-v2.sqlite3
└─ executions-v2/<id>/
   ├─ request.json
   ├─ stdout.log
   ├─ stderr.log
   ├─ outcome.json
   ├─ input.json
   └─ capability-output/
```

Relevant documentation found:

```text
docs/runtime/operations.md
```

and `run_command` documentation confirmed bounded live spool behavior.

The assistant then tailed:

```sh
tail -20 ~/.local/state/gpt-dive/executions-v2/3Qf5hA/stdout.log
tail -20 ~/.local/state/gpt-dive/executions-v2/3Qf5hA/stderr.log
```

At first the files were empty.

A later tail showed the AGY result had been written.

## 3.2 AGY task completion

Final `task(get)` state:

```json
{
  "execution_id": "3Qf5hA",
  "state": "completed",
  "elapsed_seconds": 134,
  "ready": true
}
```

Provider details inside the AGY result:

```text
provider: antigravity
model_name: gemini-3.7-flash-high
conversation_id: 1ad101d5-2b2f-4efd-bfc5-a67025a4cb5e
```

The AGY investigation was expensive:

```text
input_tokens:    ~220k
output_tokens:    ~27k
thinking_tokens:  ~19k
```

This itself reinforced the user's standing preference:
historical investigation should be tightly scoped and should not become a context dump.

---

# 4. Historical return contract before TrackedTasks

This section is based on the AGY read-only Git investigation.

## 4.1 Baseline before TrackedTasks

Baseline commit reported by AGY:

```text
7f06fb107c04145ed71f22580948180a5b6f2138
refactor: clarify code mode effective cwd
2026-08-23
```

Public signature at that point:

```python
async def code_mode(
    code: str | None = None,
    cwd: str | None = None,
    payload: str | None = None,
    background: bool = False,
    action: Literal["status", "result", "cancel"] | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
```

No:

- `label`
- `mode`
- `status_cmd`
- current `CodeModeOutcome` union

## 4.2 Foreground return

Historical `src/gpt_dive/code_runtime.py`:

```python
result: dict[str, Any] = {"result": state.output}

if capture.output:
    result["stdout"] = capture.output

return result
```

Historical test:

```python
assert asyncio.run(code_mode("1 + 2")) == {"result": 3}
```

Meaning:

```text
state.output
= final Monty expression

capture.output
= text emitted through Monty print callback
```

Examples reconstructed in the discussion:

### Example A — value only

```python
1 + 2
```

Return:

```json
{
  "result": 3
}
```

### Example B — print plus value

```python
print("hello")
1 + 2
```

Return:

```json
{
  "result": 3,
  "stdout": "hello\n"
}
```

### Example C — capability result as final expression

```python
info = await read_file("README.md")
info
```

Return conceptually:

```json
{
  "result": "<README contents>"
}
```

### Example D — `run_command()` nuance

```python
cmd = await run_command("echo hi")
cmd
```

`run_command()` itself returns a dictionary such as:

```json
{
  "exit_code": 0,
  "stdout": "hi\n",
  "stderr": "",
  "duration_ms": 8,
  "truncated": false
}
```

Therefore the old outer runtime returned:

```json
{
  "result": {
    "exit_code": 0,
    "stdout": "hi\n",
    "stderr": "",
    "duration_ms": 8,
    "truncated": false
  }
}
```

If Monty also did:

```python
print("shell finished")
cmd
```

then two different concepts named around stdout appeared:

```json
{
  "result": {
    "exit_code": 0,
    "stdout": "hi\n",
    "stderr": "",
    "duration_ms": 8,
    "truncated": false
  },
  "stdout": "shell finished\n"
}
```

This naming collision/ambiguity is part of the root problem.

## 4.3 Background return before TrackedTasks

Historical `background=True` launch returned raw `JobManager` metadata roughly like:

```json
{
  "job_id": "<uuid>",
  "status": "running",
  "status_message": "Command is running asynchronously.",
  "backend": "systemd | popen",
  "systemd_unit": null,
  "pid": 123,
  "created_at": "...",
  "updated_at": "...",
  "poll_interval_ms": 1000,
  "retention_days": 5
}
```

Historical result collection:

```python
return {"job_id": job_id, **worker_result}
```

Success shape:

```json
{
  "job_id": "...",
  "result": "<final expression>",
  "stdout": "..."
}
```

## 4.4 TrackedTasks transition commits

AGY reported this minimal transition:

```text
4f7f30d  docs(runtime): define task execution awareness v1
ce1375d  feat(runtime): add task-aware background code mode
b88ce13  feat(runtime): add task lifecycle controls
c403232  feat(runtime): add automatic tracked tasks awareness
```

Important distinction:

### `ce1375d`

With a task label, background launch began returning a compact task projection:

```python
return {
    "task_id": task["task_id"],
    "execution_id": task["execution_id"],
    "label": task["label"],
    "state": task["state"],
}
```

### `c403232`

The automatic TrackedTasks middleware was additive:

```python
result = await call_next(ctx)

...

awareness = TextContent(type="text", text=f"\n\n{text}\n")

return result.model_copy(
    update={"content": [*result.content, awareness]}
)
```

Historical test explicitly preserved the primary result:

```python
assert result.structured_content == {"answer": 3}
assert result.content[0].text == "PRIMARY"
assert "TrackedTasks" in result.content[-1].text
```

That evidence strongly supports the user's memory:

```text
TrackedTasks was intended as awareness appended to normal output,
not as a replacement for the normal output contract.
```

---

# 5. The actual root problem discovered: `stdout` was not console semantics

The user focused on:

```python
{"result": state.output}
+ stdout if capture.output exists
```

and asked what this really meant.

The discussion clarified:

```text
result
= final program value

stdout
= Monty print() capture accumulated during execution
```

The user then identified the flaw:

> `stdout`이 console.log 개념인데... 안 좋은건... 순서가 싱크가 아니라 마지막에 덜렁 나오네?

That is the pivotal root-cause observation.

## 5.1 Expected console semantics

Given:

```python
print("A")
x = await capability()
print("B")
```

the conceptual execution is:

```text
A
capability runs
B
```

A console/progress channel should preserve the fact that `A` occurred before the capability and `B`
occurred after it.

## 5.2 Actual old projection

Because GPT Dive used `CollectString()` and returned it only at completion, the caller saw:

```json
{
  "result": "<final result>",
  "stdout": "A\nB\n"
}
```

The text order inside the string is preserved, but its **relationship to capability events and the
execution timeline is no longer represented at the output boundary**.

In other words:

```text
during execution
    print
    capability
    print
    capability
    print

becomes

after execution
    final result
    one accumulated string
```

This is batch output, not console UX.

---

# 6. Context pollution: the original intent was inverted by the projection

The user then stated that the original intent was the console-like behavior just described, but asked
whether the implementation had turned it into a context dump.

Answer reached in the session: **yes, potentially severely**.

Problem example:

```python
data = await read_file("huge.md")
print(data)
{"summary": summarize(data)}
```

At the end, the model can receive:

```text
final result
    summary

plus outer stdout
    huge original document again
```

A more pathological example:

```python
a = await read_file(...)
print(a)

b = await repo_search(...)
print(b)

c = await run_command(...)
print(c)

{"final": ...}
```

The final context can contain:

```text
A large intermediate result
B large intermediate result
C large intermediate result
+
compact final answer
```

That is the opposite of the intended Code Mode advantage.

The desired principle recovered in the session:

```text
large intermediate data stays inside Monty/local runtime
                     ↓
            filter / combine / compare
                     ↓
       only compact selected result escapes
```

---

# 7. Monty `print()` itself was not the problem

Current `src/gpt_dive/code_runtime.py` inspection found:

```python
capture = CollectString()

...

state = await session.feed_start(
    ...,
    print_callback=capture,
    ...
)

while not isinstance(state, MontyComplete):
    state = await state.resume_auto()

result = {"result": state.output}

if capture.output:
    result["stdout"] = capture.output
```

The runtime also has a shared capability boundary in:

```text
CallableRegistry._track_async_callable()
```

The session then checked upstream/reference Monty behavior.

Evidence found in the Monty source showed that the print target/callback is attached to the session
driver and remains part of the `feed_start` / `resume_auto` flow.

Conclusion:

```text
Monty print callback
    = can occur during execution in order

GPT Dive CollectString
    = accumulates those prints

final output projection
    = emits the accumulated string only at completion
```

So the defect is not:

```text
Monty print cannot behave like console.log
```

It is:

```text
GPT Dive turns an event-like callback into a final accumulated field.
```

---

# 8. Correct intended semantics for `print()`

The user asked whether the caller/model would need to store a capability result in a variable and then
explicitly `print()` it.

The answer reached:

```python
result = await read_file(...)
print(result)
```

Yes — if the intermediate capability value should be shown in the console.

If it should remain internal:

```python
result = await read_file(...)
# no print
```

If only a compact status should be shown:

```python
result = await read_file(...)
print("README loaded")
```

If only a small portion is useful:

```python
print(result[:1000])
```

This was accepted as a desirable property, not a limitation.

The runtime should **not automatically print capability return values**, because that would again turn
Code Mode into a context dump.

Recovered role split:

```text
capability return
    = internal program data

print()
    = explicit console/progress emission

final expression
    = caller/model return
```

---

# 9. `asyncio.gather()` and why it matters to the design

The user specifically emphasized that `asyncio.gather()` exists to make execution faster.

The intended Code Mode pattern was reconstructed as:

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

Conceptual flow:

```text
multiple slow/independent capabilities
        ├─ A ─┐
        ├─ B ─┼─ run concurrently
        └─ C ─┘
             ↓
       large results remain local
             ↓
      Monty filters/composes
             ↓
     compact final expression
             ↓
        model context
```

This is a key reason Code Mode exists.

## 9.1 Async print ordering

For sequential awaits:

```python
print("A")
x = await foo()
print("B")
```

order is deterministic:

```text
A
B
```

For concurrent work:

```python
a, b = await asyncio.gather(
    job_a(),
    job_b(),
)
```

possible runtime console order:

```text
A start
B start
B done
A done
```

The correct console behavior is to preserve **actual occurrence order**, not source listing order.

The session considered a simple ordered recorder:

```text
seq=1 start
seq=2 A start
seq=3 B start
seq=4 B done
seq=5 A done
seq=6 done
```

However, the user consistently preferred avoiding unnecessary complexity. The immediate ADR should not
inflate into a full event framework unless required.

---

# 10. Minimal output design direction agreed in the session

The assistant initially proposed a richer structure:

```json
{
  "output": {...},
  "transcript": [
    {"seq": 1, "type": "console", "text": "..."},
    {"seq": 2, "type": "capability", "name": "read_file", "phase": "started"}
  ]
}
```

The useful part of that proposal was the separation:

```text
output
= final value

console/transcript
= ordered execution information
```

But the discussion also established an anti-bloat constraint:

```text
Do NOT copy complete capability results into transcript.
```

The more fundamental, simpler rule accepted by the user was:

```text
print()
    = console-like progress

final expression
    = compact durable result

intermediate capability returns
    = stay inside Monty unless explicitly selected
```

Streaming to a UI/TUI/ACP client can be a later transport concern.

---

# 11. ADR writing meeting: scope explicitly locked

At 2026-08-29 19:14 KST, the user wrote the ADR meeting notes.

## 11.1 User's stated core problems

The user explicitly listed:

```text
# ADR 작성 회의

## 핵심 문제

- 제외 scope: "return 현재 백그라운드 돌고 있는 Task 안 나옴"
- 응답 개선
  - 원래 의도와 다르게 설계 됨.
- 기존 설계 파악
  - context 쓰레기 심각
  - 핵심 정보 안내 하지 않음.
    - Monty runtime 문법과 python 문법은 다르다.
- output 출력개선
  - 원래 의미했던 gather.io() 후, 선별 context out.
- preview 개선
  - 포맷 다시 확정. 당분간 debug형태+context 낭비 고려.
```

The typo `gather.io()` was understood as `asyncio.gather()`.

## 11.2 Explicit phase 2

The user separately proposed:

```text
후속작업 phase2
- 원본 stdout 은 조합 후 이상하면 원래 소스 조회 기능.
  - python코드가 하니까. 컨텍스트 부담x.
  - sqlite화? just /tmp? TTL 1 day 삭제.
- ~/wiki/ERROR_CASE.md 개편
```

This is a different concern from the primary output contract.

The key principle:

```text
normal path
    compact output only

if compact result looks wrong
    inspect raw source artifact on demand
```

That avoids paying model-context cost for raw data during every successful execution.

The session noted that the current execution artifact directory already provides a natural place for
raw retained evidence:

```text
~/.local/state/gpt-dive/executions-v2/<id>/
```

Therefore a separate SQLite blob design should not be assumed necessary.

## 11.3 Explicit separate future work

The user listed:

```text
## 별도 추후 작업

- "return 현재 백그라운드 돌고 있는 Task 안 나옴" 버그
- bootstrap 및 안내 체계 문제
  - AI는 전혀 모르고 있음
```

This scope separation is critical.

The new output ADR must not become a TrackedTasks transport ADR.

---

# 12. Model guidance failure: Monty is not simply Python

The user explicitly called out missing guidance:

```text
Monty runtime 문법과 python 문법은 다르다.
```

This matters operationally because the assistant repeatedly treated Monty snippets as if arbitrary
CPython patterns were safe.

Known project guidance already says:

```text
Monty is not CPython.
Use registered capabilities.
Do not assume open()/subprocess.
Inspect live CAPABILITIES instead of inventing signatures.
PAYLOAD is exposed as PAYLOAD.
```

The root-cause source should preserve that the output redesign and bootstrap/model guidance are related
but separate:

```text
Output contract problem
    = runtime projection / context behavior

Bootstrap/model guidance problem
    = model does not know intended execution idioms
```

Both caused poor Code Mode usage, but they should not be fixed in one giant ADR.

---

# 13. Preview debugging itself became a context-waste example

The user requested a temporary debug-like display for MCP calls.

Initially the assistant displayed:

```text
CALL
@u26.code_mode({
  "label": "...",
  "code": "...",
  "payload": "..."
})

INPUT
{
  "label": "...",
  "code": "...",
  "payload": "..."
}
```

The user pointed out that `CALL` and `INPUT` were identical information and therefore pointless
duplication.

This was another concrete example of the same general anti-pattern:

```text
useful data
    ↓
unnecessary second representation
    ↓
persistent context waste
```

The user proposed a more compact preview.

Accepted temporary format:

```text
# 🔎 Inspect output capture boundary · code_mode · cwd=~/gpt-dive · mode=auto
```

followed by the actual Monty program:

```python
await repo_search(
    query=PAYLOAD,
    path=CWD,
    max_results=8,
    max_tokens=5000,
)
```

and, if present:

```text
payload: short semantic summary
```

During temporary debugging, the actual tool `OUTPUT` should also be shown.

Accepted rules:

```text
preview header
    = emoji + human label + code_mode + useful execution options

actual label
    = plain text, no emoji

python block
    = actual Monty program

payload display
    = short summary; literal only when tiny

OUTPUT
    = temporarily show actual received response
      without expanding oversized/spilled data
```

---

# 14. Documentation update for the preview rule

The assistant found the canonical operating guidance in:

```text
~/wiki/workflow/code-mode-reminder.md
```

`USER_RULES.md` already routed documentation work through `/docs`, so the preview rule was updated in
the workflow file rather than duplicated across multiple files.

The initial updated section was still too verbose.

The user then asked:

> 꼭 필수 핵심 정보만으로 서술했는지 검사

The assistant identified redundant parts:

- preview description repeated in prose and rules
- payload handling repeated
- two examples where one was enough
- schema-enforced details unnecessarily repeated

A compact final version was agreed:

```markdown
## Dive call preview

Before each `@dive` call, show a compact preview:

```text
# 🔎 Inspect output capture boundary · code_mode · cwd=~/gpt-dive · mode=auto
```

```python
await repo_search(
    query=PAYLOAD,
    path=CWD,
    max_results=8,
    max_tokens=5000,
)
```

`payload`: output capture / print callback 경계 검색

Rules:

- Header: `# <emoji> <label> · code_mode · cwd=<cwd> · mode=<mode>`. Emoji is preview-only; the actual `label` is plain text.
- Show the actual Monty program in the `python` block.
- If `payload` exists, show only a short summary; tiny values may be shown literally.
- **Temporary:** after the call, show the actual `OUTPUT`; do not expand oversized or spilled data just for display.
```

---

# 15. A live Monty failure reinforced the PAYLOAD rule

While applying the compact preview documentation, the assistant made a concrete mistake.

It embedded a long Markdown `old_text` directly into Monty code.

The call failed with `MontyTypingError` including:

```text
Positional argument cannot follow keyword argument
Multiple values provided for parameter 2 (`old_text`)
Expected `,`, found `:`
```

Root cause:

```text
complex quoted data embedded directly in Monty source
    ↓
string quoting/parsing broke the program
```

Per project rules, the assistant then read:

```text
~/wiki/ERROR_CASE.md
```

and found an existing matching pattern:

```text
복잡한 shell/quoted data를 `code`에 넣어 parser 오류
→ data는 `payload` → `PAYLOAD`로 전달
```

Recovery:

```python
old_text, new_text = PAYLOAD.split("\n===NEW===\n", 1)
await edit_file(PATH, old_text=old_text, new_text=new_text)
```

The retry succeeded.

The error-case count was incremented:

```text
5 → 6
```

This failure is directly relevant to the bootstrap/guidance issue:

```text
The model still instinctively writes CPython-like inline literals
instead of respecting the Monty + PAYLOAD execution contract.
```

---

# 16. Wiki commit created during the session

The preview guidance and ERROR_CASE count were committed in the wiki repository.

Commit:

```text
eb721e4
docs: tighten code mode preview guidance
```

Reported commit summary:

```text
2 files changed, 17 insertions(+), 25 deletions(-)
```

Files committed:

```text
workflow/code-mode-reminder.md
ERROR_CASE.md
```

Other pre-existing uncommitted wiki changes were intentionally left untouched:

```text
bootstrap/reminder.json
workflow/pydantic-ai/code-mode.md
```

This was explicitly verified after the commit.

---

# 17. Current Code Mode return shape at time of investigation

Current source inspection earlier in the session showed the public discriminated union:

```python
class CodeModeCompleted:
    kind: "completed"
    execution_id: str
    label: str
    result: Any

class CodeModeTask:
    kind: "task"
    execution_id: str
    label: str
    state: ExecutionState

class CodeModeError:
    kind: "error"
    execution_id: str
    label: str
    error: CodeModeErrorDetail
```

Current architecture had moved from:

```text
foreground ephemeral execution
vs
background JobManager execution
```

to:

```text
every Code Mode call
    = always-durable Execution

mode=auto
    = wait inline within bounded delivery window

mode=task
    = publish Task immediately
```

This is a major runtime improvement, but the session concluded that **durability and task lifecycle do not
solve the output semantics problem by themselves**.

The output ADR needs to separate:

```text
Execution lifecycle identity
from
program return semantics
from
console/progress semantics
from
TrackedTasks awareness
```

---

# 18. Root-cause model reconstructed from the session

The most compact representation of the root problem is:

```text
ORIGINAL INTENT

independent capabilities
        ↓
asyncio.gather()
        ↓
large intermediate data stays local
        ↓
Monty filters / combines / compares
        ↓
print() emits optional progress
        ↓
final expression emits selected compact result
        ↓
small model context
```

What the old projection encouraged instead:

```text
capability results
        ↓
model may print intermediate data
        ↓
CollectString accumulates everything
        ↓
execution completes
        ↓
{
  result: final value,
  stdout: all captured print text
}
        ↓
large intermediate data is injected back into model context
```

Therefore:

```text
The core defect is semantic:
console-like output and durable return were collapsed into one final response object.
```

---

# 19. Decisions reached

## DECISION 1 — TrackedTasks missing from current return is excluded

Separate bug:

```text
TrackedTasks middleware appears to append TextContent server-side,
but the current ChatGPT connector surface does not show it.
```

Do not redesign output around this bug.

## DECISION 2 — `print()` should mean console/progress

Intended meaning:

```text
print()
= explicit intermediate observation / progress
```

not:

```text
print()
= a second durable result payload automatically replayed at completion
```

## DECISION 3 — final expression is the caller result

```text
final Monty expression
= selected compact result that should enter caller/model context
```

## DECISION 4 — capability results stay internal by default

Do not automatically mirror full capability returns into console/transcript.

## DECISION 5 — `asyncio.gather()` is a first-class intended idiom

Use it for independent work to reduce wall-clock time.

Then process results inside Monty and return only the selected compact projection.

## DECISION 6 — avoid premature event-system complexity

The immediate contract should stay simple.

A richer ordered event stream can be introduced when a TUI/ACP/web client actually needs live streaming.

## DECISION 7 — raw source retention is phase 2

If a compact result appears suspicious, inspect the exact raw artifact on demand.

Candidate approach:

```text
execution artifact directory
+ bounded raw log/source
+ short TTL (~1 day proposed)
```

Do not pay model-context cost in the normal path.

## DECISION 8 — preview stays temporarily debug-oriented

Use:

```text
header
python
optional payload summary
actual OUTPUT
```

without duplicated JSON representations.

## DECISION 9 — bootstrap/model guidance is separate work

The model must be taught:

```text
Monty != CPython
CAPABILITIES are the supported host boundary
PAYLOAD carries opaque/quoted/long data
asyncio.gather() is for independent capability concurrency
print() is console-like
final expression is compact return
mode=task is detachment
```

But that guidance overhaul is not the same ADR as the output contract.

---

# 20. What ADR 0005 should not do again

The session strongly implies the following anti-patterns for a rewritten ADR:

```text
Do not start from "simplification" as an abstract goal.
Start from the observed broken semantics.

Do not center TrackedTasks.
It exposed the issue, but is explicitly out of scope.

Do not describe only current CodeModeOutcome classes.
Lifecycle shape is not the root output problem.

Do not treat Monty as ordinary Python.
The supported execution contract matters.

Do not propose automatic emission of every capability result.
That destroys the main context-saving benefit.

Do not create SQLite/event-bus/streaming machinery before the minimal contract is fixed.

Do not write a generic "reduce context" ADR without showing exactly how context was duplicated.

Do not lose the user's original intent:
parallelize locally, compose locally, return selectively.
```

---

# 21. Suggested ADR 0005 replacement thesis

This source is not itself the ADR, but the ADR derived from it should be able to state something close to:

```text
Code Mode is a programmable local reduction boundary.

Its contract should optimize for:
1. concurrent local capability execution,
2. local retention of large intermediate values,
3. explicit console/progress output when useful,
4. one compact final program result returned to the caller.

Console output, final program output, execution lifecycle, and Task awareness are separate concerns.
The prior design blurred at least the first two by accumulating Monty print output and replaying it as
a final `stdout` field, which could re-inject large intermediate data into persistent model context.
```

That is the core design issue recovered in this session.

---

# 22. Timeline — condensed forensic index

All timestamps below use the message timestamps available in the chat where present.

## 2026-08-29 18:40 KST range

- AGY launched to inspect history before TrackedTasks.
- Execution ID: `3Qf5hA`.
- Goal: recover pre-TrackedTasks public return shape and minimal transition commits.

## 18:41 KST

User:

```text
함 찔러볼래?
```

`task(get)`:

```text
state=running
ready=false
elapsed_seconds=65
```

## 18:41–18:42 KST

User asks whether `tail -10` is possible.

Investigation finds:

```text
~/.local/state/gpt-dive/executions-v2/<id>/stdout.log
~/.local/state/gpt-dive/executions-v2/<id>/stderr.log
```

Initial tail is empty.

## 18:42 KST

User notices:

```text
output 에 전혀 Tracked Task 가 안 나오네?
```

This triggers explicit recognition of the connector projection problem.

## 18:43 KST

User asks to tail again.

AGY output is now present and task completes at approximately:

```text
finished_at: 2026-08-29T09:42:34Z
elapsed_seconds: 134
```

Historical result recovered.

## 18:45 KST

User asks for examples of:

```text
{"result": state.output}
+ stdout
```

The old foreground output semantics are explained in detail.

## 18:50 KST

User identifies the console synchronization problem:

```text
stdout이 console.log 개념인데...
순서가 싱크가 아니라 마지막에 덜렁 나오네?
```

This is the decisive root-cause turn.

## 18:51 KST

User asks to improve output first, before TrackedTasks.

Current `code_runtime.py` is inspected.

Findings:

```text
CollectString()
print_callback=capture
final {"result": state.output, "stdout": capture.output}
```

## 18:54 KST

User asks whether Monty `print()` can really be used like `console.log`.

Reference Monty source is inspected.

Conclusion:

```text
print callback itself can occur during execution;
GPT Dive's final aggregation is the problem.
```

## 18:57 KST

User recognizes context pollution:

```text
원래 내가 의도한거는 ... 그 의도인데...
실제 내부에서는 컨텍스트 쓰레기장이 되어버렸네?
```

The session explicitly connects printed intermediate data with final context reinjection.

## 18:58 KST

User asks how async changes the behavior.

Discussion establishes actual-occurrence ordering under concurrent tasks.

## 19:00 KST

User restates intended use:

```text
asyncio.gather로 실행 속도 높이고
결과를 예쁘게 가공해서
원하는 compact 버전으로 받아서 쓸 수 있나?
```

Answer: yes; this becomes the central design intent.

## 19:14 KST

User opens the ADR writing meeting and fixes scope.

Explicit exclusions and phase 2 are recorded.

## 19:15–19:18 KST

Preview format is redesigned to avoid duplicate CALL/INPUT representation.

Accepted form:

```text
# emoji label · code_mode · cwd · mode
python block
optional payload summary
temporary OUTPUT
```

## 19:21–19:39 KST

`/docs` guidance is inspected.

`workflow/code-mode-reminder.md` is updated and then aggressively compressed.

A Monty parser error occurs because long Markdown was embedded directly in `code`.

`ERROR_CASE.md` is read, matching pattern found, retry succeeds using PAYLOAD.

Wiki commit:

```text
eb721e4 docs: tighten code mode preview guidance
```

## 2026-08-30 05:41 KST

User asks:

```text
니가 docs/runtime/adr/0005-post-renewal-simplification.md 작성했었나?
```

Conversation/project history indicates the assistant was the authoring side of that document, and the user
had previously reopened it and criticized it for missing the core issue.

A fresh Git author verification was attempted but connector routing failed, so authorship was not
re-proven from Git in that turn.

## 05:42–05:47 KST

User asks whether this session can be extracted at nearly debug level and then requests:

```text
L3 으로 뽑아줘.
런타임 adr 에
source-adr-0005-root-cause.md
```

At that exact point the `@u26` connector became unavailable before the target-repo write could be made.

---

# 23. Key source paths and IDs for future verification

## Runtime source

```text
src/gpt_dive/code_runtime.py
src/gpt_dive/app.py
src/gpt_dive/command_runtime.py
src/gpt_dive/execution_manager.py
```

## Runtime docs

```text
docs/runtime/architecture.md
docs/runtime/operations.md
docs/runtime/adr/0005-post-renewal-simplification.md
docs/pydantic/code-mode.md
docs/pydantic/tool-output-limits.md
```

## Historical task-awareness artifacts

```text
plans/plan-260824-task-execution-awareness-v1.md
```

Historical commits reported by AGY:

```text
7f06fb1  pre-TrackedTasks baseline used in investigation
4f7f30d  define task execution awareness v1
ce1375d  task-aware background code mode
b88ce13  task lifecycle controls
c403232  automatic tracked tasks awareness
bd650a7  always-durable Code Mode runtime renewal
```

## Live execution IDs from this session

```text
3Qf5hA  AGY history investigation
iuNENg  search for execution output by ID
QhhivQ  locate execution spool path
d3fagg  first tail of AGY logs
AHbMyA  later tail showing AGY output
IEBBzw  inspect output capture boundary
kLFuBg  inspect Monty print ordering
```

## Wiki commit

```text
eb721e4 docs: tighten code mode preview guidance
```

## Execution artifact path pattern

```text
~/.local/state/gpt-dive/executions-v2/<execution_id>/
```

---

# 24. Final root-cause checklist

A future ADR/reimplementation review should be able to answer all of these:

- [ ] Is the final Monty expression the only normal durable program result?
- [ ] Does `print()` behave as console/progress rather than a second final payload?
- [ ] Can large intermediate capability results remain local and never enter model context?
- [ ] Is `asyncio.gather()` documented as the preferred pattern for independent capability calls?
- [ ] Does the model know Monty is not arbitrary CPython?
- [ ] Are large/quoted inputs carried through `PAYLOAD` rather than source literals?
- [ ] Are output semantics independent from Execution/Task lifecycle?
- [ ] Is the missing TrackedTasks connector projection tracked separately?
- [ ] Can raw execution evidence be inspected on demand without normal-path context cost?
- [ ] Does preview/debug rendering avoid representing the same information twice?
- [ ] Does the replacement ADR explain the original intent, the observed failure, and the minimal decision?

If any of these are missing, the rewritten ADR risks repeating the same loss of design intent that caused
this root-cause reconstruction to be necessary.
