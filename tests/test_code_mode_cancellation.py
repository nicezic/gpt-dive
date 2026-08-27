from __future__ import annotations

import asyncio
import signal
from pathlib import Path

import pytest


def test_code_mode_survives_repeated_async_capability_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import gpt_dive
    import gpt_dive.code_capabilities as code_capabilities_module

    def make_fake_worker(
        started: asyncio.Event, blocker: asyncio.Event, cancelled: asyncio.Event
    ):
        async def fake_invoke_agy_worker(**_kwargs: object) -> dict[str, object]:
            started.set()
            try:
                await blocker.wait()
            finally:
                cancelled.set()
            return {"ok": True}

        return fake_invoke_agy_worker

    async def scenario() -> None:
        for _ in range(5):
            started = asyncio.Event()
            cancelled = asyncio.Event()
            blocker = asyncio.Event()

            monkeypatch.setattr(
                code_capabilities_module,
                "invoke_agy_worker",
                make_fake_worker(started, blocker, cancelled),
            )
            worker_task = asyncio.create_task(
                gpt_dive.code_mode("await agy_worker(task='research', timeout=30.0)")
            )
            await started.wait()
            ordinary_task = asyncio.create_task(gpt_dive.code_mode("40 + 2"))
            worker_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await worker_task
            assert cancelled.is_set()
            assert await ordinary_task == {"result": 42}
            assert await gpt_dive.code_mode("1 + 2") == {"result": 3}

    asyncio.run(scenario())


def test_code_mode_cancellation_reaps_real_agy_worker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import gpt_dive
    import gpt_dive.agy_worker as agy_worker_module
    import gpt_dive.worker_subprocess as worker_subprocess_module

    fake_agy = tmp_path / "agy"
    fake_agy.write_text("fake")
    monkeypatch.setattr(agy_worker_module, "AGY", fake_agy)

    class FakeProcess:
        pid = 6262
        returncode: int | None = None

        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.done = asyncio.Event()
            self.reaped = False

        async def communicate(
            self, _stdin_payload: object = None
        ) -> tuple[bytes, bytes]:
            self.started.set()
            await self.done.wait()
            self.returncode = -signal.SIGTERM
            self.reaped = True
            return b"", b""

    proc = FakeProcess()
    killed: list[tuple[int, int]] = []

    async def fake_create_subprocess_exec(
        *_args: object, **_kwargs: object
    ) -> FakeProcess:
        return proc

    def fake_killpg(pid: int, sig: int) -> None:
        killed.append((pid, sig))
        proc.done.set()

    monkeypatch.setattr(
        worker_subprocess_module.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    monkeypatch.setattr(worker_subprocess_module.os, "killpg", fake_killpg)

    async def scenario() -> None:
        task = asyncio.create_task(
            gpt_dive.code_mode("await agy_worker(task='research', timeout=120.0)")
        )
        await proc.started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await gpt_dive.code_mode("1 + 2") == {"result": 3}

    asyncio.run(scenario())

    assert killed == [(6262, signal.SIGTERM)]
    assert proc.reaped is True


def test_code_mode_cancellation_escalates_to_sigkill_when_sigterm_ignored(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import gpt_dive
    import gpt_dive.agy_worker as agy_worker_module
    import gpt_dive.worker_subprocess as worker_subprocess_module

    fake_agy = tmp_path / "agy"
    fake_agy.write_text("fake")
    monkeypatch.setattr(agy_worker_module, "AGY", fake_agy)

    class StubbornProcess:
        pid = 7373
        returncode: int | None = None

        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.done = asyncio.Event()
            self.reaped = False

        async def communicate(
            self, _stdin_payload: object = None
        ) -> tuple[bytes, bytes]:
            self.started.set()
            await self.done.wait()
            self.returncode = -signal.SIGKILL
            self.reaped = True
            return b"", b""

    proc = StubbornProcess()
    signals_sent: list[tuple[int, int]] = []

    async def fake_create_subprocess_exec(
        *_args: object, **_kwargs: object
    ) -> StubbornProcess:
        return proc

    def fake_killpg(pid: int, sig: int) -> None:
        signals_sent.append((pid, sig))
        if sig == signal.SIGKILL:
            proc.done.set()

    monkeypatch.setattr(
        worker_subprocess_module.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    monkeypatch.setattr(worker_subprocess_module.os, "killpg", fake_killpg)

    orig_terminate = worker_subprocess_module._terminate_and_reap

    async def fast_terminate(p, task, *, grace_seconds=0.05, log_label="WORKER"):
        return await orig_terminate(p, task, grace_seconds=0.05, log_label=log_label)

    monkeypatch.setattr(worker_subprocess_module, "_terminate_and_reap", fast_terminate)

    async def scenario() -> None:
        task = asyncio.create_task(
            gpt_dive.code_mode("await agy_worker(task='stubborn', timeout=120.0)")
        )
        await proc.started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await gpt_dive.code_mode("1 + 2") == {"result": 3}

    asyncio.run(scenario())

    assert signals_sent == [(7373, signal.SIGTERM), (7373, signal.SIGKILL)]
    assert proc.reaped is True


def test_worker_subprocess_final_reap_timeout_is_bounded_and_preserves_partial_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import time

    import gpt_dive.worker_subprocess as worker_subprocess_module

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

    def fake_killpg(pid: int, sig: int) -> None:
        signals.append(sig)

    monkeypatch.setattr(worker_subprocess_module.os, "killpg", fake_killpg)

    async def scenario() -> worker_subprocess_module.CleanupOutcome:
        async def hung_communicate() -> tuple[bytes, bytes]:
            await asyncio.Event().wait()
            return b"", b""

        communicate_task = asyncio.create_task(hung_communicate())
        return await worker_subprocess_module._terminate_and_reap(
            proc,  # type: ignore[arg-type]
            communicate_task,
            grace_seconds=0.02,
            final_grace_seconds=0.02,
            log_label="TEST",
        )

    t0 = time.monotonic()
    cleanup = asyncio.run(scenario())
    elapsed = time.monotonic() - t0

    assert elapsed < 1.5, f"Reap was not bounded: {elapsed}s"
    assert cleanup.stdout == b"partial stdout data"
    assert cleanup.stderr == b""
    assert cleanup.reaped is False
    assert signals == [signal.SIGTERM, signal.SIGKILL]
    assert not worker_subprocess_module._PENDING_CLEANUP_TASKS


def test_run_bounded_worker_reports_reap_failure_without_fake_returncode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import gpt_dive.worker_subprocess as worker_subprocess_module

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
    signals: list[int] = []

    async def fake_create_subprocess_exec(
        *_args: object, **_kwargs: object
    ) -> UnreapableProcess:
        return proc

    def fake_killpg(pid: int, sig: int) -> None:
        signals.append(sig)

    monkeypatch.setattr(
        worker_subprocess_module.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    monkeypatch.setattr(worker_subprocess_module.os, "killpg", fake_killpg)

    orig_terminate = worker_subprocess_module._terminate_and_reap

    async def fast_terminate(
        p: object,
        task: object,
        *,
        grace_seconds: float = 0.02,
        final_grace_seconds: float = 0.02,
        log_label: str = "WORKER",
    ) -> worker_subprocess_module.CleanupOutcome:
        return await orig_terminate(
            p,  # type: ignore[arg-type]
            task,  # type: ignore[arg-type]
            grace_seconds=0.02,
            final_grace_seconds=0.02,
            log_label=log_label,
        )

    monkeypatch.setattr(worker_subprocess_module, "_terminate_and_reap", fast_terminate)

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
    assert worker_subprocess_module.worker_failure(
        outcome, kind="test", timeout=0.01
    ) == {
        "ok": False,
        "timed_out": True,
        "cleanup_failed": True,
        "error": "test worker could not be reaped after termination",
    }
    assert not worker_subprocess_module._PENDING_CLEANUP_TASKS


def test_uncooperative_process_waiter_remains_explicitly_owned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import gpt_dive.worker_subprocess as worker_subprocess_module

    release_waiter: asyncio.Event

    class StuckProcess:
        pid = 10001
        returncode = None
        stdout = None
        stderr = None

        async def wait(self) -> int:
            while not release_waiter.is_set():
                try:
                    await release_waiter.wait()
                except asyncio.CancelledError:
                    continue
            return 0

    monkeypatch.setattr(worker_subprocess_module.os, "killpg", lambda *_args: None)

    async def scenario() -> None:
        nonlocal release_waiter
        release_waiter = asyncio.Event()

        async def communicate() -> tuple[bytes, bytes]:
            await asyncio.Event().wait()
            return b"", b""

        communicate_task = asyncio.create_task(communicate())
        cleanup = await worker_subprocess_module._terminate_and_reap(
            StuckProcess(),  # type: ignore[arg-type]
            communicate_task,
            grace_seconds=0.001,
            final_grace_seconds=0.001,
            communicate_cancel_grace_seconds=0.001,
            process_wait_grace_seconds=0.001,
            log_label="TEST",
        )
        assert cleanup.reaped is False
        assert len(worker_subprocess_module._PENDING_CLEANUP_TASKS) == 1

        release_waiter.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not worker_subprocess_module._PENDING_CLEANUP_TASKS

    asyncio.run(scenario())
