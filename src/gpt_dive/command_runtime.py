from __future__ import annotations

import asyncio
import contextlib
import fnmatch
import os
import shlex
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, BinaryIO, TypedDict

from .execution_store import ExecutionStore, parse_time, utc_now
from .runtime_env import DENIED_MODEL_ENV_PATTERNS, build_runtime_path
from .worker_subprocess import terminate_and_reap

_RUN_COMMAND_POLICY_SECONDS = 43190.0
_RUN_COMMAND_CLEANUP_RESERVE_SECONDS = 9.0
_SPOOL_BYTES_PER_STREAM = 8 * 1024 * 1024
_CONTEXT_CHARS = 8000
_DRAIN_CHUNK_BYTES = 64 * 1024
WSL_EXEC_TIMEOUT_SECONDS = 600.0


class RuntimeRecord(TypedDict):
    execution_id: str
    store: ExecutionStore
    work_deadline_monotonic: float
    next_run_ordinal: int


def runtime_record(
    record: dict[str, Any], *, store: ExecutionStore
) -> RuntimeRecord:
    """Project an Execution into the fields needed by child capabilities."""
    remaining = max(
        0.0,
        (parse_time(str(record["work_deadline_at"])) - utc_now()).total_seconds(),
    )
    return {
        "execution_id": str(record["execution_id"]),
        "store": store,
        "work_deadline_monotonic": time.monotonic() + remaining,
        "next_run_ordinal": 1,
    }


def remaining_seconds(record: RuntimeRecord) -> float:
    return max(0.0, record["work_deadline_monotonic"] - time.monotonic())


def child_budget(record: RuntimeRecord, policy_seconds: float) -> float:
    if policy_seconds <= 0:
        raise ValueError("child capability policy must be greater than 0")
    remaining = remaining_seconds(record)
    if remaining <= 0:
        raise TimeoutError("Execution work budget is exhausted")
    return min(policy_seconds, remaining)


def _run_command_root() -> Path:
    return Path(tempfile.gettempdir()) / "gpt-dive-run-command"


def _run_command_execution_directory(execution_id: str) -> Path:
    return _run_command_root() / execution_id


def _run_command_directory(execution_id: str, run_ordinal: int) -> Path:
    return _run_command_execution_directory(execution_id) / str(run_ordinal)


def _ensure_private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)


def _prepare_run_command_directory(execution_id: str, run_ordinal: int) -> Path:
    root = _run_command_root()
    execution_directory = _run_command_execution_directory(execution_id)
    directory = _run_command_directory(execution_id, run_ordinal)
    for candidate in (root, execution_directory, directory):
        _ensure_private_directory(candidate)
    return directory


def _allocate_run_command_ordinal(record: RuntimeRecord) -> int:
    run_ordinal = record["next_run_ordinal"]
    record["next_run_ordinal"] = run_ordinal + 1
    return run_ordinal


def remove_run_command_evidence_directory(execution_id: str) -> None:
    with contextlib.suppress(FileNotFoundError):
        shutil.rmtree(_run_command_execution_directory(execution_id))


def materialize_run_command_stream(
    record: RuntimeRecord, run_ordinal: int, stream: str
) -> Path:
    if stream not in {"stdout", "stderr"}:
        raise ValueError("stream must be 'stdout' or 'stderr'")
    path = _run_command_directory(record["execution_id"], run_ordinal) / stream
    if path.is_file():
        return path

    evidence = record["store"].get_run_command_evidence(
        record["execution_id"], run_ordinal
    )
    directory = _prepare_run_command_directory(record["execution_id"], run_ordinal)
    path = directory / stream
    if not path.is_file():
        with _open_private_binary(path) as handle:
            handle.write(bytes(evidence[stream]))
    return path

def _open_private_binary(path: Path) -> BinaryIO:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    return os.fdopen(descriptor, "wb")


def _sanitized_environment() -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not any(
            fnmatch.fnmatchcase(key, pattern)
            for pattern in DENIED_MODEL_ENV_PATTERNS
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


def _read_shell_outputs(
    stdout_path: Path,
    stderr_path: Path,
    *,
    stdout_overflow: bool,
    stderr_overflow: bool,
) -> tuple[str, str, bool]:
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
    return stdout, stderr, any(
        (
            stdout_overflow,
            stderr_overflow,
            stdout_context_truncated,
            stderr_context_truncated,
        )
    )


async def _run_shell_process(
    command: str,
    *,
    cwd: str | None,
    env: dict[str, str] | None,
    timeout: float,
    stdout_path: Path,
    stderr_path: Path,
    log_label: str,
) -> tuple[int | None, bool, bool, bool, bool]:
    proc = await asyncio.create_subprocess_exec(
        "/bin/bash",
        "-lc",
        command,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
        cwd=cwd,
        env=env,
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
    cancelled = False
    try:
        await asyncio.wait_for(asyncio.shield(communicate_task), timeout=timeout)
    except TimeoutError:
        timed_out = True
        cleanup = await terminate_and_reap(
            proc,
            communicate_task,
            grace_seconds=4.0,
            final_grace_seconds=4.0,
            log_label=log_label,
        )
        if not cleanup.reaped:
            raise RuntimeError(
                f"{log_label.lower()} process group could not be reaped"
            ) from None
    except asyncio.CancelledError:
        cleanup = await terminate_and_reap(
            proc,
            communicate_task,
            grace_seconds=4.0,
            final_grace_seconds=4.0,
            log_label=log_label,
        )
        if not cleanup.reaped:
            raise RuntimeError(
                f"{log_label.lower()} process group could not be reaped"
            ) from None
        cancelled = True
    return (
        proc.returncode,
        timed_out,
        stdout_task.result() if stdout_task.done() else True,
        stderr_task.result() if stderr_task.done() else True,
        cancelled,
    )


async def run_wsl_command(
    command: str,
    *,
    cwd: str | None,
    timeout: float = WSL_EXEC_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Run one raw WSL shell with bounded output and process-group cleanup."""
    if not command.strip():
        raise ValueError("command must not be empty")
    run_cwd = str(Path(cwd).expanduser().resolve()) if cwd else None
    if run_cwd is not None and not Path(run_cwd).is_dir():
        raise ValueError(f"cwd does not exist or is not a directory: {run_cwd}")
    with tempfile.TemporaryDirectory(prefix="gpt-dive-wsl-exec-") as temporary:
        stdout_path = Path(temporary) / "stdout.log"
        stderr_path = Path(temporary) / "stderr.log"
        (
            returncode,
            timed_out,
            stdout_overflow,
            stderr_overflow,
            cancelled,
        ) = await _run_shell_process(
                command,
                cwd=run_cwd,
                env=None,
                timeout=timeout,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                log_label="WSL EXEC",
            )
        stdout, stderr, truncated = _read_shell_outputs(
            stdout_path,
            stderr_path,
            stdout_overflow=stdout_overflow,
            stderr_overflow=stderr_overflow,
        )
    if cancelled:
        raise asyncio.CancelledError
    if timed_out:
        stderr = f"{stderr}\n[wsl_exec] timed out after {timeout:g} seconds".lstrip()
    return {
        "exit_code": 124 if timed_out else returncode,
        "stdout": stdout,
        "stderr": stderr,
        "truncated": truncated,
    }


async def run_command(
    command: str,
    *,
    cwd: str,
    record: RuntimeRecord,
) -> dict[str, Any]:
    """Run one awaited local shell command inside the owning Execution.

    The command inherits Runtime cwd, sanitized environment, guard-bin PATH, and
    remaining work budget. For deliberately longer work, an explicit
    ``systemd-run --user --unit=gd-detached-<name> --collect ...`` handoff leaves
    GPT Dive Runtime and must be observed with systemd/journald.
    """
    if not command.strip():
        raise ValueError("command must not be empty")
    effective_budget = child_budget(record, _RUN_COMMAND_POLICY_SECONDS)
    command_timeout = effective_budget - _RUN_COMMAND_CLEANUP_RESERVE_SECONDS
    if command_timeout <= 0:
        raise TimeoutError("insufficient Execution budget to start run_command")

    run_ordinal = _allocate_run_command_ordinal(record)
    directory = _prepare_run_command_directory(record["execution_id"], run_ordinal)
    stdout_path = directory / "stdout"
    stderr_path = directory / "stderr"
    environment = _sanitized_environment()
    runtime_path = environment["PATH"]
    guarded_command = f"export PATH={shlex.quote(runtime_path)}; {command}"
    started = time.monotonic()
    (
        returncode,
        timed_out,
        stdout_overflow,
        stderr_overflow,
        cancelled,
    ) = await _run_shell_process(
        guarded_command,
        cwd=cwd,
        env=environment,
        timeout=command_timeout,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        log_label="RUN COMMAND",
    )
    stdout, stderr, truncated = _read_shell_outputs(
        stdout_path,
        stderr_path,
        stdout_overflow=stdout_overflow,
        stderr_overflow=stderr_overflow,
    )
    exit_code = 124 if timed_out else returncode
    duration_ms = int((time.monotonic() - started) * 1000)
    with contextlib.suppress(Exception):
        record["store"].persist_run_command_evidence(
            record["execution_id"],
            run_ordinal,
            stdout=stdout_path.read_bytes(),
            stderr=stderr_path.read_bytes(),
            stdout_overflow=stdout_overflow,
            stderr_overflow=stderr_overflow,
            exit_code=exit_code,
            duration_ms=duration_ms,
        )

    if cancelled:
        raise asyncio.CancelledError
    if exit_code is None:
        raise RuntimeError("run_command exited without an exit code")
    return {
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "duration_ms": duration_ms,
        "truncated": truncated,
    }
