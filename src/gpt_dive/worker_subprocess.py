from __future__ import annotations

import asyncio
import logging
import os
import signal
from typing import Any

logger = logging.getLogger("gpt_dive.runtime")

_STDERR_TAIL_CHARS = 2000


def stderr_tail(stderr_text: str, *, limit: int = _STDERR_TAIL_CHARS) -> str:
    """Best-effort diagnostics tail shared by every worker caller."""
    return stderr_text[-limit:]


async def _terminate_and_reap(
    proc: asyncio.subprocess.Process,
    communicate_task: asyncio.Task[tuple[bytes, bytes]],
    *,
    log_label: str,
) -> tuple[bytes, bytes]:
    """Terminate one detached process group and reap its stdio task."""
    logger.warning("%s TERMINATE pid=%s", log_label, proc.pid)
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        logger.info("%s TERMINATE SKIP pid=%s reason=already-exited", log_label, proc.pid)
    stdout, stderr = await communicate_task
    logger.info(
        "%s CLEANUP DONE pid=%s returncode=%s",
        log_label,
        proc.pid,
        getattr(proc, "returncode", None),
    )
    return stdout, stderr


async def run_bounded_worker(
    command: list[str],
    *,
    stdin_payload: bytes | None = None,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    timeout: float,
    grace_seconds: float = 2.0,
    log_label: str = "WORKER",
) -> dict[str, Any]:
    """Run one detached worker process under a bounded timeout.

    Lifecycle semantics (owned here once for every worker caller):

    - the child starts in its own session so cancellation reaches the whole group;
    - the communicate task is shielded, with a small grace window after ``timeout``
      so self-exiting workers can still flush their envelope;
    - on timeout the group gets SIGTERM and whatever partial output was buffered;
    - on caller cancellation the group is terminated and CancelledError re-raises;
    - output is decoded with errors="replace".

    Returns ``{returncode, stdout_text, stderr_text, timed_out}``; envelope
    parsing and error shaping stay with each caller.
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
        stdout, stderr = await _terminate_and_reap(
            proc, communicate_task, log_label=log_label
        )
    except asyncio.CancelledError:
        logger.warning("%s CANCELLED pid=%s", log_label, proc.pid)
        await _terminate_and_reap(proc, communicate_task, log_label=log_label)
        raise

    logger.info(
        "%s DONE pid=%s returncode=%s",
        log_label,
        proc.pid,
        getattr(proc, "returncode", None),
    )
    return {
        "returncode": proc.returncode,
        "stdout_text": stdout.decode(errors="replace").strip(),
        "stderr_text": stderr.decode(errors="replace").strip(),
        "timed_out": timed_out,
    }
