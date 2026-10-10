from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import signal
from pathlib import Path
from typing import Any, NamedTuple

from .runtime_env import build_runtime_path

logger = logging.getLogger("gpt_dive.runtime")

_STDERR_TAIL_CHARS = 2000


class WorkerOutcome(NamedTuple):
    """Raw transport envelope returned by one bounded worker process.

    NamedTuple(네임드터플): 필드 접근이 가능한 불변 경량 타입 — 오타 시
    런타임 KeyError 대신 정적 검사(pyright)가 잡아 준다.
    """

    returncode: int | None
    stdout_text: str
    stderr_text: str
    timed_out: bool
    reaped: bool


class CleanupOutcome(NamedTuple):
    """Bounded process cleanup result without inventing an exit status."""

    stdout: bytes
    stderr: bytes
    reaped: bool


class WorkerCleanupError(RuntimeError):
    """Raised when cancellation could not confirm that a worker was reaped."""


_PENDING_CLEANUP_TASKS: set[asyncio.Task[Any]] = set()
_COMMUNICATE_CANCEL_GRACE_SECONDS = 0.5
_PROCESS_WAIT_GRACE_SECONDS = 0.5
_TASK_CANCEL_DRAIN_SECONDS = 0.25


def _consume_task_result(task: asyncio.Task[Any], *, log_label: str) -> None:
    """Retrieve a completed task result so asyncio never reports it as unhandled."""
    if task.cancelled():
        return
    try:
        task.result()
    except Exception:
        logger.exception("%s DEFERRED CLEANUP TASK FAILED", log_label)


def _retain_pending_cleanup_task(task: asyncio.Task[Any], *, log_label: str) -> None:
    """Keep explicit ownership of a cleanup waiter that ignored cancellation."""
    if task.done():
        _consume_task_result(task, log_label=log_label)
        return
    _PENDING_CLEANUP_TASKS.add(task)

    def finished(done_task: asyncio.Task[Any]) -> None:
        _PENDING_CLEANUP_TASKS.discard(done_task)
        _consume_task_result(done_task, log_label=log_label)

    task.add_done_callback(finished)
    logger.error(
        "%s CLEANUP TASK RETAINED pending_cleanup_tasks=%d",
        log_label,
        len(_PENDING_CLEANUP_TASKS),
    )


async def _cancel_and_drain_task(
    task: asyncio.Task[Any], *, timeout: float, log_label: str
) -> bool:
    """Cancel a task, drain it when possible, or retain it for deferred cleanup."""
    task.cancel()
    done, _ = await asyncio.wait([task], timeout=timeout)
    if task in done:
        _consume_task_result(task, log_label=log_label)
        return True
    _retain_pending_cleanup_task(task, log_label=log_label)
    return False


def stderr_tail(stderr_text: str) -> str:
    """Best-effort diagnostics tail shared by every worker caller."""
    return stderr_text[-_STDERR_TAIL_CHARS:]


def credentialed_python_worker(module: str) -> tuple[list[str], dict[str, str]]:
    """Launch an AI worker under the existing creds scope, with the shared PATH."""
    home_bin = Path.home() / ".local" / "bin"
    project = Path(__file__).resolve().parents[2]
    command = [
        str(home_bin / "creds"),
        "run",
        "ai",
        "--",
        str(home_bin / "uv"),
        "run",
        "--project",
        str(project),
        "--python",
        "3.14",
        "python",
        "-m",
        module,
    ]
    env = os.environ.copy()
    env["PATH"] = build_runtime_path(inherited=env.get("PATH"))
    return command, env


def parse_worker_json(outcome: WorkerOutcome) -> dict[str, Any]:
    """Decode one successful worker response, preserving its stderr evidence."""
    result = json.loads(outcome.stdout_text)
    if outcome.stderr_text:
        result["worker_stderr"] = stderr_tail(outcome.stderr_text)
    return result


def worker_failure(
    outcome: WorkerOutcome, *, kind: str, timeout: float
) -> dict[str, Any] | None:
    """Shared failure detection for one bounded worker run.

    Returns the base ``{"ok": False, "error": ...}`` payload when cleanup
    could not confirm reap, the worker timed out, or it exited nonzero. Returns
    None when the caller may proceed to parse the envelope. Lane-specific fields
    (labels, tails, partial output) stay with each caller.
    """
    if not outcome.reaped:
        return {
            "ok": False,
            "timed_out": outcome.timed_out,
            "cleanup_failed": True,
            "error": f"{kind} worker could not be reaped after termination",
        }
    if outcome.timed_out:
        return {
            "ok": False,
            "timed_out": True,
            "error": f"{kind} worker timed out after {timeout} seconds",
        }
    if outcome.returncode != 0:
        return {
            "ok": False,
            "error": f"{kind} worker exited with code {outcome.returncode}",
        }
    return None


async def terminate_and_reap(
    proc: asyncio.subprocess.Process,
    communicate_task: asyncio.Task[tuple[bytes, bytes]],
    *,
    grace_seconds: float = 4.0,
    final_grace_seconds: float = 4.0,
    communicate_cancel_grace_seconds: float = _COMMUNICATE_CANCEL_GRACE_SECONDS,
    process_wait_grace_seconds: float = _PROCESS_WAIT_GRACE_SECONDS,
    log_label: str,
) -> CleanupOutcome:
    """Terminate one isolated process group and reap its stdio task with SIGKILL escalation."""
    logger.warning("%s TERMINATE (SIGTERM) pid=%s", log_label, proc.pid)
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        logger.info(
            "%s TERMINATE SKIP pid=%s reason=already-exited", log_label, proc.pid
        )
    done, _ = await asyncio.wait([communicate_task], timeout=grace_seconds)
    if communicate_task in done:
        stdout, stderr = communicate_task.result()
    else:
        logger.warning(
            "%s ESCALATE (SIGKILL) pid=%s grace=%.1fs exceeded",
            log_label,
            proc.pid,
            grace_seconds,
        )
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
        done, _ = await asyncio.wait([communicate_task], timeout=final_grace_seconds)
        if communicate_task in done:
            stdout, stderr = communicate_task.result()
        else:
            logger.error("%s FINAL REAP TIMEOUT pid=%s", log_label, proc.pid)
            partial_out = (
                bytes(getattr(proc.stdout, "_buffer", b""))
                if getattr(proc, "stdout", None)
                else b""
            )
            partial_err = (
                bytes(getattr(proc.stderr, "_buffer", b""))
                if getattr(proc, "stderr", None)
                else b""
            )
            communicate_task.cancel()
            final_done, _ = await asyncio.wait(
                [communicate_task], timeout=communicate_cancel_grace_seconds
            )
            if communicate_task in final_done and not communicate_task.cancelled():
                try:
                    stdout, stderr = communicate_task.result()
                except Exception:
                    stdout, stderr = partial_out, partial_err
            else:
                stdout, stderr = partial_out, partial_err
                if communicate_task not in final_done:
                    _retain_pending_cleanup_task(communicate_task, log_label=log_label)

    if proc.returncode is None:
        wait_task = asyncio.create_task(proc.wait())
        done_proc, _ = await asyncio.wait(
            [wait_task], timeout=process_wait_grace_seconds
        )
        if wait_task in done_proc:
            _consume_task_result(wait_task, log_label=log_label)
        else:
            logger.error("%s PROC WAIT TIMEOUT pid=%s", log_label, proc.pid)
            await _cancel_and_drain_task(
                wait_task,
                timeout=_TASK_CANCEL_DRAIN_SECONDS,
                log_label=log_label,
            )

    if proc.returncode is not None:
        logger.info(
            "%s CLEANUP DONE pid=%s returncode=%s",
            log_label,
            proc.pid,
            proc.returncode,
        )
    else:
        logger.error(
            "%s CLEANUP UNREAPED pid=%s returncode=None",
            log_label,
            proc.pid,
        )
    return CleanupOutcome(stdout, stderr, proc.returncode is not None)


async def run_bounded_worker(
    command: list[str],
    *,
    stdin_payload: bytes | None = None,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    timeout: float,
    grace_seconds: float = 2.0,
    termination_grace_seconds: float = 4.0,
    log_label: str = "WORKER",
) -> WorkerOutcome:
    """Run one isolated worker process under a bounded timeout.

    Lifecycle semantics (owned here once for every worker caller):

    - the child starts in its own session so cancellation reaches the whole group;
    - the communicate task is shielded, with a small grace window after ``timeout``
      so self-exiting workers can still flush their envelope;
    - on timeout the group gets SIGTERM, escalates to SIGKILL after grace_seconds,
      and returns whatever partial output was buffered;
    - on caller cancellation the group is terminated; CancelledError re-raises only
      after reap is confirmed, otherwise WorkerCleanupError reports the cleanup failure;
    - output is decoded with errors="replace".

    Returns a :class:`WorkerOutcome`; envelope parsing and error shaping
    stay with each caller.
    """
    proc = await asyncio.create_subprocess_exec(
        *command,
        stdin=(
            asyncio.subprocess.PIPE
            if stdin_payload is not None
            else asyncio.subprocess.DEVNULL
        ),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
        cwd=cwd,
        env=env,
    )
    logger.info("%s START pid=%s", log_label, proc.pid)

    communicate_task = asyncio.create_task(proc.communicate(stdin_payload))
    timed_out = False
    try:
        stdout, stderr = await asyncio.wait_for(
            asyncio.shield(communicate_task), timeout=timeout + grace_seconds
        )
    except TimeoutError:
        logger.warning("%s TIMEOUT pid=%s timeout=%.1f", log_label, proc.pid, timeout)
        timed_out = True
        cleanup = await terminate_and_reap(
            proc,
            communicate_task,
            grace_seconds=termination_grace_seconds,
            log_label=log_label,
        )
        stdout, stderr = cleanup.stdout, cleanup.stderr
    except asyncio.CancelledError:
        logger.warning("%s CANCELLED pid=%s", log_label, proc.pid)
        cleanup = await terminate_and_reap(
            proc,
            communicate_task,
            grace_seconds=termination_grace_seconds,
            log_label=log_label,
        )
        if not cleanup.reaped:
            raise WorkerCleanupError(
                f"{log_label} worker pid={proc.pid} could not be reaped after cancellation"
            ) from None
        raise

    logger.info(
        "%s DONE pid=%s returncode=%s",
        log_label,
        proc.pid,
        getattr(proc, "returncode", None),
    )
    return WorkerOutcome(
        returncode=proc.returncode,
        stdout_text=stdout.decode(errors="replace").strip(),
        stderr_text=stderr.decode(errors="replace").strip(),
        timed_out=timed_out,
        reaped=proc.returncode is not None,
    )
