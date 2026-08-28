from __future__ import annotations

import asyncio
import signal
import time
from pathlib import Path

import pytest

import gpt_dive.worker_subprocess as worker_subprocess_module
from gpt_dive.command_runtime import run_command
from gpt_dive.execution_context import ExecutionContext


def context_for_test(root: Path, *, duration_seconds: float = 60) -> ExecutionContext:
    return ExecutionContext.for_test(
        duration_seconds=duration_seconds,
        artifact_dir=root / "artifacts",
    )


def test_run_command_cancellation_reaps_the_process_group(tmp_path: Path) -> None:
    pid_path = tmp_path / "command.pid"

    async def scenario() -> int:
        task = asyncio.create_task(
            run_command(
                f"echo $$ > {pid_path}; exec sleep 30",
                cwd=str(tmp_path),
                context=context_for_test(tmp_path),
            )
        )
        deadline = time.monotonic() + 2
        while not pid_path.is_file() and time.monotonic() < deadline:
            await asyncio.sleep(0.01)
        pid = int(pid_path.read_text().strip())
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return pid

    pid = asyncio.run(scenario())

    assert not Path(f"/proc/{pid}").exists()


def test_run_command_timeout_is_terminal_and_bounded(tmp_path: Path) -> None:
    started = time.monotonic()
    result = asyncio.run(
        run_command(
            "sleep 30",
            cwd=str(tmp_path),
            context=context_for_test(tmp_path, duration_seconds=9.15),
        )
    )

    assert result["exit_code"] == 124
    assert time.monotonic() - started < 2


def test_run_command_truncates_context_and_retains_bounded_spill(
    tmp_path: Path,
) -> None:
    result = asyncio.run(
        run_command(
            "yes X | head -c 20000",
            cwd=str(tmp_path),
            context=context_for_test(tmp_path),
        )
    )

    assert result["truncated"] is True
    assert len(result["stdout"]) <= 8000
    spill = Path(result["spill_path"])
    assert spill.is_file()
    assert b"===== stdout =====" in spill.read_bytes()


def test_worker_subprocess_final_reap_timeout_is_bounded_and_preserves_partial_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StuckStream:
        _buffer = b"partial stdout data"

    class StuckProcess:
        pid = 8888
        returncode = None
        stdout = StuckStream()
        stderr = None

        async def wait(self) -> int:
            await asyncio.Event().wait()
            return 0

    proc = StuckProcess()
    signals: list[int] = []
    monkeypatch.setattr(
        worker_subprocess_module.os,
        "killpg",
        lambda _pid, sig: signals.append(sig),
    )

    async def scenario() -> worker_subprocess_module.CleanupOutcome:
        async def hung_communicate() -> tuple[bytes, bytes]:
            await asyncio.Event().wait()
            return b"", b""

        communicate_task = asyncio.create_task(hung_communicate())
        return await worker_subprocess_module.terminate_and_reap(
            proc,  # type: ignore[arg-type]
            communicate_task,
            grace_seconds=0.02,
            final_grace_seconds=0.02,
            log_label="TEST",
        )

    started = time.monotonic()
    cleanup = asyncio.run(scenario())

    assert time.monotonic() - started < 1.5
    assert cleanup.stdout == b"partial stdout data"
    assert cleanup.stderr == b""
    assert cleanup.reaped is False
    assert signals == [signal.SIGTERM, signal.SIGKILL]
    assert not worker_subprocess_module._PENDING_CLEANUP_TASKS


def test_run_bounded_worker_reports_reap_failure_without_fake_returncode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StuckStream:
        _buffer = b"partial before reap failure"

    class UnreapableProcess:
        pid = 9999
        returncode = None
        stdout = StuckStream()
        stderr = None

        async def communicate(self, _input: bytes | None = None) -> tuple[bytes, bytes]:
            await asyncio.Event().wait()
            return b"", b""

        async def wait(self) -> int:
            await asyncio.Event().wait()
            return 0

    proc = UnreapableProcess()

    async def fake_create_subprocess_exec(
        *_args: object, **_kwargs: object
    ) -> UnreapableProcess:
        return proc

    monkeypatch.setattr(
        worker_subprocess_module.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    monkeypatch.setattr(worker_subprocess_module.os, "killpg", lambda *_args: None)
    original_terminate = worker_subprocess_module.terminate_and_reap

    async def fast_terminate(
        process: object,
        task: object,
        *,
        grace_seconds: float = 0.02,
        final_grace_seconds: float = 0.02,
        log_label: str = "WORKER",
    ) -> worker_subprocess_module.CleanupOutcome:
        return await original_terminate(
            process,  # type: ignore[arg-type]
            task,  # type: ignore[arg-type]
            grace_seconds=0.02,
            final_grace_seconds=0.02,
            log_label=log_label,
        )

    monkeypatch.setattr(worker_subprocess_module, "terminate_and_reap", fast_terminate)

    outcome = asyncio.run(
        worker_subprocess_module.run_bounded_worker(
            ["echo", "hi"],
            timeout=0.01,
            grace_seconds=0.01,
            termination_grace_seconds=0.02,
        )
    )

    assert outcome.timed_out is True
    assert outcome.returncode is None
    assert outcome.reaped is False
    assert outcome.stdout_text == "partial before reap failure"
    failure = worker_subprocess_module.worker_failure(
        outcome, kind="test", timeout=0.01
    )
    assert failure is not None
    assert failure["cleanup_failed"] is True
    assert not worker_subprocess_module._PENDING_CLEANUP_TASKS
