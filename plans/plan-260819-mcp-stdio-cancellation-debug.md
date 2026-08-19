# MCP stdio cancellation diagnostics

## Problem Statement

GPT Dive intermittently surfaces `ToolError: UNKNOWN` / `ExceptionGroup: unhandled errors in a TaskGroup` while the local tunnel later reports that the GPT Dive stdio pipe is already closed. The Web-visible wrapper hides the first actionable exception, so the current system cannot reliably distinguish a tunnel-triggered cancellation, GPT Dive server lifecycle failure, MCP SDK/AnyIO cancellation bug, or a child-worker cleanup problem.

A second observation increases the value of testing the child-worker boundary: direct `agy_worker()` calls inside `code_mode` have intermittently failed without a useful underlying error. The current `wsl2_async + agy` route is only an operational workaround introduced after those failures; it is not evidence that AGY is the root cause.

The current AGY implementation starts a subprocess in a new session, creates a `proc.communicate()` task, and waits through `asyncio.shield()`. Timeout cleanup terminates the process group and reaps the communication task, but there is no explicit outer-cancellation cleanup path. This is a concrete lifecycle gap worth testing, not a proven explanation for the 2026-08-19 incident.

## Solution

Make the first failure observable at the GPT Dive/MCP boundary, then test and harden cancellation semantics without adding recovery machinery that could hide the bug.

The implementation will:

- emit high-signal lifecycle/error diagnostics to stderr/journald while keeping stdout protocol-only;
- preserve the real exception tree and process/server exit reason;
- correlate request and AGY child lifecycle events when identifiers are available;
- add an external-behavior regression test for cancelling an active AGY worker;
- ensure cancellation cleans up the AGY process/communication task and then propagates cancellation normally;
- add a focused concurrent/cancellation canary to prove the MCP process remains healthy after cancellation;
- move the investigation boundary to MCP Python SDK / AnyIO only if the AGY path is clean and the failure still reproduces.

## User Stories

1. As the operator, I want a generic Web `TaskGroup / UNKNOWN` failure to have a corresponding journald root exception, so that I can diagnose the real failing boundary.
2. As the operator, I want GPT Dive stdout reserved for MCP JSON-RPC, so that diagnostics cannot corrupt the transport they are meant to debug.
3. As the operator, I want process start/stop and server-exit reasons in diagnostics, so that I can tell whether stdio closed because of EOF, cancellation, exception, or signal.
4. As the operator, I want request lifecycle events correlated by the identifiers already available to GPT Dive, so that overlapping requests can be ordered without inventing tunnel-only identifiers.
5. As the operator, I want nested `ExceptionGroup` / `BaseExceptionGroup` failures preserved recursively, so that cancellation noise does not hide the actionable child exception.
6. As the operator, I want runtime dependency versions captured at process start, so that incidents spanning upgrades can be compared accurately.
7. As the operator, I want cancelling an active AGY worker to terminate its process group and reap its communication task, so that no orphan child survives the cancelled request.
8. As the operator, I want AGY cancellation re-raised after cleanup, so that the MCP framework receives normal cancellation semantics instead of a swallowed or transformed success.
9. As the operator, I want timeout behavior to continue preserving partial AGY state, so that hardening cancellation does not regress the existing timeout contract.
10. As the operator, I want a subsequent normal MCP/Code Mode request to succeed after a forced AGY cancellation, so that cancellation cannot silently poison the receive loop or stdio session.
11. As the operator, I want concurrent Code Mode activity stressed alongside AGY cancellation/timeout, so that timing-sensitive lifecycle bugs are exercised rather than only happy-path unit behavior.
12. As the operator, I want the canary to detect orphan AGY processes and unnecessary GPT Dive/tunnel restarts, so that apparent request success cannot hide leaked runtime state.
13. As the operator, I want concurrent file reads/writes treated as a secondary hypothesis unless file-level evidence appears, so that complexity such as locking is not added without causal evidence.
14. As the operator, I want automatic retry, alternate transport, and broad crash recovery left out of this change, so that the first failure remains visible and the implementation stays small.
15. As the operator, I want the runtime operations document to stay compact while this plan owns the implementation hypotheses and acceptance criteria, so that long-lived docs do not accumulate temporary theories.

## Implementation Decisions

- The highest-value observability seam is the MCP process/server lifecycle, not individual tools. Diagnostics must describe request cancellation/error and server/process exit without requiring every capability to implement its own framework.
- Runtime diagnostics use Python logging/stderr. Stdout remains exclusively the MCP transport.
- Exception-group logging preserves the nested exception structure and traceback rather than projecting the failure to only the outer group message.
- Lifecycle logging is intentionally compact: process/server start and exit, request start/completion/cancel/error, and AGY child start/done/timeout/cancel/terminate/cleanup. It is not a full request transcript.
- Correlation uses identifiers actually available in the GPT Dive/MCP layer. Tunnel workflow IDs must not be invented or assumed to cross the stdio boundary.
- The AGY worker cancellation path must perform deterministic child cleanup before propagating outer cancellation. Cancellation is not converted into a normal error result.
- Existing timeout semantics remain intact: timeout still terminates the process group, reaps communication, and preserves useful partial stdout/stderr state.
- Cleanup logic should be shared between timeout and cancellation only if doing so reduces duplication without obscuring their different return/propagation semantics.
- Concurrent project-file read/write is not treated as the primary cause without direct file-level evidence. No file-locking protocol is introduced by this spec.
- The current `wsl2_async + agy` operational workaround may remain during validation, but it is neither the fix nor proof of the direct worker capability's root cause.
- If the AGY cancellation path passes regression and stress tests while the intermittent failure persists, the next investigation boundary is MCP Python SDK / AnyIO request cancellation and stdio receive-loop behavior.
- No automatic retry, fallback transport, or broad self-healing layer is introduced. The objective is correct lifecycle semantics plus evidence preservation.

## Testing Decisions

- Prefer the highest external-behavior seam available: cancel a live request/worker and verify observable cleanup plus continued server usability, rather than asserting private helper call sequences alone.
- Extend the existing AGY worker test seam that already fakes subprocess creation, `wait_for`, process-group termination, and partial output. Add a cancellation case that proves the child is terminated/reaped and cancellation propagates.
- Preserve the existing timeout regression as a distinct behavior test. A cancellation hardening change must not remove partial timeout state or change the timeout result contract.
- Add a runtime-level test/canary that forces cancellation while an AGY child is active, then performs a normal follow-up MCP/Code Mode request. Passing means the server/stdio path remains usable.
- Capture stderr separately from stdout in the runtime seam. Diagnostic output may appear on stderr; protocol output must not be polluted by diagnostic text.
- Exercise recursive exception-group logging with a synthetic nested group or equivalent controlled failure and verify the actionable inner exception is present in diagnostics.
- Verify startup diagnostics include the versions needed to correlate incidents, without making exact version values part of test expectations.
- Run a bounded stress canary with concurrent ordinary Code Mode operations plus repeated forced AGY cancellation/timeout. The canary should fail on orphan AGY children, unexpected GPT Dive/tunnel restart, unusable follow-up requests, or recurrence of an unaccounted `TaskGroup / UNKNOWN`.
- Do not add file-contention tests unless a future incident produces stale/partial/ENOENT or related file-level evidence. The current failure signature is stdio/lifecycle-oriented.

## Out of Scope

- File locking or transactional project-file access between Web SOL and AGY.
- Automatic retry of failed MCP/Code Mode requests.
- Alternate/fallback MCP transports.
- General crash-recovery or self-healing infrastructure.
- Replacing the current tunnel client.
- Changing Pydantic AI/Harness behavior without evidence that the failure reaches that layer.
- Treating the current `wsl2_async + agy` workaround as the final architecture decision.
- Broad logging of request payloads, file contents, prompts, or other noisy/sensitive data.

## Further Notes

Implementation on 2026-08-19 produced a failing canary at the intended high seam: cancelling an outer Code Mode task returned `CancelledError` to the caller while the active async host capability remained running. The Code Mode registry now tracks active async host-call tasks and cancels/awaits them during `aclose()`. With that common cleanup in place, capability cancellation reaches `agy_worker()`, whose cancellation path terminates and reaps the AGY process group before re-raising `CancelledError`. Repeated forced cancellation followed by a normal Code Mode call now passes.

Targeted cancellation/diagnostic tests, the full test suite, and type checking passed after the implementation; final lint/review status is recorded by the implementation workflow rather than treated as causal evidence.

The 2026-08-19 captured incident established that the tunnel reached its MCP connection TTL, then failed to write to the GPT Dive stdio pipe because it was already closed, after which systemd restarted the service. It did not establish why the pipe closed first.

The current AGY hypothesis is prioritized because the direct worker path has a history of intermittent generic Code Mode failures and because the implementation has an explicit timeout-cleanup path but no explicit outer-cancellation cleanup path around a shielded `proc.communicate()` task. This is enough to justify targeted testing, not enough to assign root cause.

Success means the next failure is attributable from local evidence, AGY cancellation cannot leak a child/communication task, and forced cancellation does not poison the MCP server/stdio session. If those conditions hold and the intermittent issue remains, investigation moves to the MCP SDK / AnyIO cancellation boundary rather than adding unrelated fallback complexity.
