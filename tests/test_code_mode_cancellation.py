from __future__ import annotations

import asyncio
import signal
from pathlib import Path

import pytest


def test_code_mode_survives_repeated_async_capability_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import gpt_dive
    import gpt_dive.app as app_module

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
                app_module,
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

        async def communicate(self) -> tuple[bytes, bytes]:
            self.started.set()
            await self.done.wait()
            self.returncode = -signal.SIGTERM
            self.reaped = True
            return b"", b""

    proc = FakeProcess()
    killed: list[tuple[int, int]] = []

    async def fake_create_subprocess_exec(*_args: object, **_kwargs: object) -> FakeProcess:
        return proc

    def fake_killpg(pid: int, sig: int) -> None:
        killed.append((pid, sig))
        proc.done.set()

    monkeypatch.setattr(
        agy_worker_module.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    monkeypatch.setattr(agy_worker_module.os, "killpg", fake_killpg)

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
