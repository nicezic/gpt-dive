from __future__ import annotations

import asyncio
import fnmatch
import os
import shlex
import time
from pathlib import Path
from typing import Any, BinaryIO

from pydantic_ai_harness.shell import LLM_API_KEY_ENV_PATTERNS

from .execution_context import ExecutionContext
from .runtime_env import build_runtime_path
from .worker_subprocess import terminate_and_reap

_RUN_COMMAND_POLICY_SECONDS = 3590.0
_RUN_COMMAND_CLEANUP_RESERVE_SECONDS = 9.0
_SPOOL_BYTES_PER_STREAM = 8 * 1024 * 1024
_CONTEXT_CHARS = 8000
_DRAIN_CHUNK_BYTES = 64 * 1024
_DENIED_ENV_PATTERNS = (
    *LLM_API_KEY_ENV_PATTERNS,
    "MINIMAX_*",
    "AIAPIFLOW_*",
)


def _open_private_binary(path: Path) -> BinaryIO:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    return os.fdopen(descriptor, "wb")


def _sanitized_environment() -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not any(
            fnmatch.fnmatchcase(key, pattern) for pattern in _DENIED_ENV_PATTERNS
        )
    }
    guard_bin = Path(__file__).resolve().parent / "guard-bin"
    environment["PATH"] = build_runtime_path(
        guard_bin, inherited=environment.get("PATH")
    )
    return environment


async def _drain_stream(
    stream: asyncio.StreamReader,
    path: Path,
    *,
    max_bytes: int,
) -> bool:
    written = 0
    overflow = False
    with _open_private_binary(path) as handle:
        while chunk := await stream.read(_DRAIN_CHUNK_BYTES):
            remaining = max_bytes - written
            if remaining > 0:
                piece = chunk[:remaining]
                handle.write(piece)
                written += len(piece)
            if len(chunk) > remaining:
                overflow = True
    return overflow


async def _wait_and_drain(
    proc: asyncio.subprocess.Process,
    stdout_drain: asyncio.Task[bool],
    stderr_drain: asyncio.Task[bool],
) -> tuple[bytes, bytes]:
    await proc.wait()
    await asyncio.gather(stdout_drain, stderr_drain)
    return b"", b""


def _read_bounded_text(path: Path, max_chars: int) -> tuple[str, bool]:
    if max_chars <= 0 or not path.is_file():
        return "", path.is_file() and path.stat().st_size > 0
    byte_window = max(4096, max_chars * 4)
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size <= byte_window:
            text = handle.read().decode(errors="replace")
        else:
            half = byte_window // 2
            head = handle.read(half)
            handle.seek(max(0, size - half))
            tail = handle.read(half)
            text = (
                head.decode(errors="replace")
                + "\n… output truncated …\n"
                + tail.decode(errors="replace")
            )
    if len(text) <= max_chars:
        return text, size > byte_window
    head_chars = max_chars // 2
    tail_chars = max_chars - head_chars - len("\n… output truncated …\n")
    if tail_chars <= 0:
        return text[:max_chars], True
    return (
        text[:head_chars] + "\n… output truncated …\n" + text[-tail_chars:],
        True,
    )


def _copy_stream(source: Path, target: BinaryIO) -> None:
    with source.open("rb") as handle:
        while chunk := handle.read(_DRAIN_CHUNK_BYTES):
            target.write(chunk)


def _write_spill(stdout_path: Path, stderr_path: Path, spill_path: Path) -> None:
    with _open_private_binary(spill_path) as target:
        target.write(b"===== stdout =====\n")
        _copy_stream(stdout_path, target)
        target.write(b"\n===== stderr =====\n")
        _copy_stream(stderr_path, target)


async def run_command(
    command: str,
    *,
    cwd: str,
    context: ExecutionContext,
) -> dict[str, Any]:
    """Run one awaited local shell command inside the owning Execution.

    The command inherits Runtime cwd, sanitized environment, guard-bin PATH, and
    remaining work budget. For deliberately longer work, an explicit
    ``systemd-run --user --unit=gd-detached-<name> --collect ...`` handoff leaves
    GPT Dive Runtime and must be observed with systemd/journald.
    """
    if not command.strip():
        raise ValueError("command must not be empty")
    effective_budget = context.child_budget(_RUN_COMMAND_POLICY_SECONDS)
    command_timeout = effective_budget - _RUN_COMMAND_CLEANUP_RESERVE_SECONDS
    if command_timeout <= 0:
        raise TimeoutError("insufficient Execution budget to start run_command")

    stdout_path = context.spill_path(prefix="run-command-stdout")
    stderr_path = context.spill_path(prefix="run-command-stderr")
    environment = _sanitized_environment()
    runtime_path = environment["PATH"]
    guarded_command = f"export PATH={shlex.quote(runtime_path)}; {command}"
    started = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        "/bin/bash",
        "-lc",
        guarded_command,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
        cwd=cwd,
        env=environment,
    )
    assert proc.stdout is not None
    assert proc.stderr is not None
    stdout_task = asyncio.create_task(
        _drain_stream(proc.stdout, stdout_path, max_bytes=_SPOOL_BYTES_PER_STREAM)
    )
    stderr_task = asyncio.create_task(
        _drain_stream(proc.stderr, stderr_path, max_bytes=_SPOOL_BYTES_PER_STREAM)
    )
    communicate_task = asyncio.create_task(
        _wait_and_drain(proc, stdout_task, stderr_task)
    )
    timed_out = False
    try:
        await asyncio.wait_for(
            asyncio.shield(communicate_task), timeout=command_timeout
        )
    except TimeoutError:
        timed_out = True
        cleanup = await terminate_and_reap(
            proc,
            communicate_task,
            grace_seconds=4.0,
            final_grace_seconds=4.0,
            log_label="RUN COMMAND",
        )
        if not cleanup.reaped:
            raise RuntimeError(
                "run_command process group could not be reaped"
            ) from None
    except asyncio.CancelledError:
        cleanup = await terminate_and_reap(
            proc,
            communicate_task,
            grace_seconds=4.0,
            final_grace_seconds=4.0,
            log_label="RUN COMMAND",
        )
        if not cleanup.reaped:
            raise RuntimeError(
                "run_command process group could not be reaped"
            ) from None
        raise

    stdout_overflow = stdout_task.result() if stdout_task.done() else True
    stderr_overflow = stderr_task.result() if stderr_task.done() else True
    stdout_size = stdout_path.stat().st_size
    stderr_size = stderr_path.stat().st_size
    if stdout_size and stderr_size:
        stdout_budget = _CONTEXT_CHARS // 2
        stderr_budget = _CONTEXT_CHARS - stdout_budget
    elif stdout_size:
        stdout_budget, stderr_budget = _CONTEXT_CHARS, 0
    else:
        stdout_budget, stderr_budget = 0, _CONTEXT_CHARS
    stdout, stdout_context_truncated = _read_bounded_text(stdout_path, stdout_budget)
    stderr, stderr_context_truncated = _read_bounded_text(stderr_path, stderr_budget)
    truncated = any(
        (
            stdout_overflow,
            stderr_overflow,
            stdout_context_truncated,
            stderr_context_truncated,
        )
    )
    spill_path: Path | None = None
    if truncated:
        spill_path = context.spill_path(prefix="run-command")
        _write_spill(stdout_path, stderr_path, spill_path)
    stdout_path.unlink(missing_ok=True)
    stderr_path.unlink(missing_ok=True)

    return {
        "exit_code": 124 if timed_out else proc.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "truncated": truncated,
        **({"spill_path": str(spill_path)} if spill_path is not None else {}),
    }
