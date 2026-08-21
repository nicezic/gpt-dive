# GPT Dive Runtime Context

GPT Dive Runtime owns the canonical language for durable execution and meaningful asynchronous work that ChatGPT Web SOL must be able to rediscover without blocking its foreground flow.

## Language

**Task**:
Meaningful asynchronous work that Web SOL should remain aware of until it reaches a terminal state and is explicitly handled.
_Avoid_: Job, process, background job when referring to this logical work.

**Execution**:
The durable runtime instance that performs one Task in the v1 model.
_Avoid_: Job when referring to the canonical runtime concept; PID or process when referring to durable execution identity.

**TrackedTasks**:
The compact projection of outstanding Tasks surfaced to Web SOL during ordinary tool activity so detached work is not forgotten.
_Avoid_: Job list, Execution list, task registry when referring to the Web-facing projection.

**Lost**:
A Task whose backing Execution or retained result can no longer be found. Lost work is not reconstructed or recovered; it remains lost until acknowledged.
_Avoid_: stale when the runtime has definitively lost the backing state.
