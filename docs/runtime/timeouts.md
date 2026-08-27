# GPT Dive Execution Deadlines

> Current contract for Code Mode lifetime, timeout ownership, and cleanup. Implementation authority: `src/gpt_dive/app.py` and `src/gpt_dive/worker_subprocess.py`. ADR 0003 preserves the decision rationale.

## Why this boundary exists

The tunnel's observed command-response budget is approximately 120 seconds. GPT Dive must finish or return a controlled application result before that outer transport becomes the first component to time out.

```text
ChatGPT Web request
       │
       ▼
tunnel response budget        approximately 120s (external constraint)
       │
       └─ GPT Dive foreground response deadline   110s
             ├─ execution cutoff                  100s
             └─ cancellation / cleanup window      10s
```

The 10-second difference is not extra work time. It is reserved for cancellation, child termination, output draining, and registry cleanup.

## Runtime choice

```text
Can the whole Monty program reliably finish within 100s?
├─ yes → code_mode(task omitted)
│        └─ synchronous foreground result
└─ no / uncertain → code_mode(task={label, status?})
                   ├─ immediate Task + Execution identity
                   └─ detached execution deadline: 600s
```

The caller chooses the branch at launch. GPT Dive does not automatically convert a timed-out foreground run into a Task because replay or continuation could duplicate side effects and change the return contract.

## Foreground behavior

```text
request accepted
├─ start absolute 110s response clock
├─ build registry + run Monty program
│
├─ finishes before 100s → return normal result
└─ reaches 100s cutoff
   ├─ cancel runtime task
   ├─ use remaining time for cleanup
   └─ return code_mode_timeout by 110s
```

The model cannot provide a Code Mode timeout value. A timeout result includes:

```text
error.code                     code_mode_timeout
error.timeout_seconds          110.0   # response deadline
error.execution_cutoff_seconds 100.0   # work cutoff
error.retry_as_task            true
error.cleanup_status           complete | failed | pending
```

`cleanup_status` is truthful runtime state:

```text
complete → cancellation cleanup finished before the response
failed   → cleanup finished with an explicit error
pending  → the response deadline arrived first; GPT Dive retained task ownership
           and will consume its eventual result or exception
```

`pending` is not detached user work and does not produce a collectable Runtime Task. It means only that internal cleanup remains owned by the server instead of becoming an unreferenced asyncio task.

## Detached Task behavior

```text
code_mode(task={label, status?})
├─ MCP call returns promptly
├─ TaskStore records awareness
├─ ExecutionManager runs the worker durably
└─ fixed outer execution deadline: 600s
   ├─ status / result / cancel → code_mode lifecycle actions
   └─ task_list / collect / cancel / ack → inner Task capabilities
```

The 600-second deadline is fixed application policy, not a user/model argument. Running executions can survive an MCP server restart; retained execution logs follow the runtime retention policy.

## Child capability timeouts

Model/worker capabilities such as `agy_worker`, `subagent_call`, `peer_review`, and `m3_evidence` still require their own `timeout` argument. That timeout limits the child call; it never extends the outer Code Mode lifetime.

```text
foreground outer lifetime  100s execution cutoff
└─ child timeout must fit inside the remaining foreground time

detached outer lifetime    600s execution deadline
└─ child timeout must fit inside the remaining detached time
```

Choose a child timeout from the work itself, with cleanup margin, and use the Task branch when the whole composition may exceed the foreground cutoff. A child timeout of 900 seconds inside a 600-second Task does not create a 900-second execution; the outer deadline still wins.

## Process cleanup boundary

Worker subprocess cleanup is bounded below the outer 10-second window:

```text
cancel / worker timeout
├─ SIGTERM + wait        4.00s
├─ SIGKILL + wait        4.00s
├─ communicate drain     0.50s
├─ process wait          0.50s
└─ waiter cancel drain   0.25s
                         ─────
maximum configured waits 9.25s + scheduling overhead
```

GPT Dive never invents a process exit code. If reap cannot be confirmed, the worker outcome keeps `returncode=null`, reports `reaped=false`, and retains any waiter that still ignores cancellation until its result or exception can be consumed.

## Design boundary

This policy contains application work only after a request reaches GPT Dive. It does not prove or repair a tunnel/session failure that occurs before GPT Dive logs request entry.

```text
request reaches GPT Dive handler
├─ yes → these deadlines bound Code Mode work
└─ no  → investigate tunnel / session / stdio lifecycle
```

## References

- `src/gpt_dive/app.py`
  - Foreground response clock, execution cutoff, cleanup ownership, and detached 600-second launch policy.
- `src/gpt_dive/worker_subprocess.py`
  - TERM/KILL/reap sequence and explicit un-reaped outcomes.
- `docs/runtime/adr/0003-single-code-mode-command-surface-and-fixed-deadlines.md`
  - Decision rationale, rejected alternatives, and acceptance boundary.
- `docs/runtime/operations.md`
  - Service reload and fresh-session schema acceptance procedure.
