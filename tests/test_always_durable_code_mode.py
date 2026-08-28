from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

import pytest

from gpt_dive import app
from gpt_dive.execution_manager import ExecutionManager


def install_manager(monkeypatch: pytest.MonkeyPatch, root: Path) -> ExecutionManager:
    manager = ExecutionManager(
        root,
        work_timeout_seconds=12,
        cleanup_timeout_seconds=2,
    )
    manager._systemd_available = False
    monkeypatch.setattr(app, "executions", manager)
    return manager


async def wait_task_ready(
    execution_id: str, *, timeout: float = 6.0
) -> app.TaskGetOutput:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        outcome = await app.task(
            app.TaskGetRequest(action="get", execution_id=execution_id)
        )
        assert isinstance(outcome, app.TaskGetOutput)
        if outcome.ready or outcome.unavailable:
            return outcome
        await asyncio.sleep(0.05)
    raise AssertionError("Code Mode Task did not finish")


def test_inline_completion_keeps_execution_unpublished(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = install_manager(monkeypatch, tmp_path / "executions")

    outcome = asyncio.run(
        app.code_mode(label="inline arithmetic", code="1 + 2", cwd=str(tmp_path))
    )

    assert isinstance(outcome, app.CodeModeCompleted)
    assert outcome.result == {"result": 3}
    record = manager.store.get(outcome.execution_id)
    assert record["state"] == "completed"
    assert record["published_at"] is None
    assert record["request_path"] == ""
    assert not (manager.root / outcome.execution_id / "input.json").exists()


def test_inline_wait_expiry_publishes_same_continuing_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = install_manager(monkeypatch, tmp_path / "executions")
    monkeypatch.setattr(app, "_INLINE_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(app, "_INLINE_RESPONSE_DEADLINE_SECONDS", 1.0)

    async def scenario() -> None:
        outcome = await app.code_mode(
            label="slow arithmetic",
            code="await run_command('sleep 0.4; printf SLOW')",
            cwd=str(tmp_path),
        )
        assert isinstance(outcome, app.CodeModeTask)
        execution_id = outcome.execution_id
        assert manager.store.get_task(execution_id)["execution_id"] == execution_id

        first = await wait_task_ready(execution_id)
        second = await app.task(
            app.TaskGetRequest(action="get", execution_id=execution_id)
        )
        assert isinstance(second, app.TaskGetOutput)
        assert first.result == second.result
        assert first.result is not None
        assert first.result["kind"] == "completed"
        assert first.result["result"]["result"]["stdout"] == "SLOW"

        dismissed = await app.task(
            app.TaskDismissRequest(action="dismiss", execution_id=execution_id)
        )
        assert isinstance(dismissed, app.TaskDismissOutput)
        assert dismissed.dismissed is True

    asyncio.run(scenario())


def test_transport_cancellation_publishes_instead_of_cancelling_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = install_manager(monkeypatch, tmp_path / "executions")

    async def scenario() -> None:
        call = asyncio.create_task(
            app.code_mode(
                label="transport loss",
                code="await run_command('sleep 5')",
                cwd=str(tmp_path),
            )
        )
        deadline = time.monotonic() + 3
        while not manager.store.list_executions() and time.monotonic() < deadline:
            await asyncio.sleep(0.01)
        execution_id = str(manager.store.list_executions()[0]["execution_id"])

        call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await call

        task = manager.store.get_task(execution_id)
        assert task["cancel_requested"] is False
        assert task["state"] in {"accepted", "running"}
        await app.task(
            app.TaskCancelRequest(action="cancel", execution_id=execution_id)
        )

    asyncio.run(scenario())


def test_inline_cutoff_publishes_accepted_task_during_stalled_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = install_manager(monkeypatch, tmp_path / "executions")
    release_launch = threading.Event()

    def stalled_spawn(_execution_id: str, *, backend: str, unit: str | None) -> None:
        assert backend == "popen"
        assert unit is None
        release_launch.wait(timeout=0.3)

    monkeypatch.setattr(manager, "_spawn_worker", stalled_spawn)
    monkeypatch.setattr(app, "_INLINE_WAIT_SECONDS", 0.02)
    monkeypatch.setattr(app, "_INLINE_RESPONSE_DEADLINE_SECONDS", 0.2)

    async def scenario() -> None:
        started = time.monotonic()
        outcome = await app.code_mode(
            label="bounded launch",
            code="1 + 2",
            cwd=str(tmp_path),
        )
        assert time.monotonic() - started < 0.12

        assert isinstance(outcome, app.CodeModeTask)
        record = manager.store.get(outcome.execution_id)
        assert record["state"] == "accepted"
        assert record["published_at"] is not None
        release_launch.set()

    asyncio.run(scenario())


def test_post_acceptance_response_timeout_returns_structured_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = install_manager(monkeypatch, tmp_path / "executions")
    monkeypatch.setattr(manager, "_spawn_worker", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(app, "_INLINE_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(app, "_INLINE_RESPONSE_DEADLINE_SECONDS", 0.08)

    async def stalled_wait(
        _execution_id: str, *, wait_deadline: float
    ) -> dict[str, object]:
        assert wait_deadline > 0
        await asyncio.sleep(0.2)
        return {}

    monkeypatch.setattr(app, "_wait_for_execution", stalled_wait)

    async def scenario() -> None:
        started = time.monotonic()
        outcome = await app.code_mode(
            label="bounded response shaping",
            code="1 + 2",
            cwd=str(tmp_path),
        )
        assert time.monotonic() - started < 0.16

        assert isinstance(outcome, app.CodeModeError)
        assert outcome.error.code == "response_deadline_exceeded"
        assert manager.store.get(outcome.execution_id)["state"] == "accepted"
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            if manager.store.get(outcome.execution_id)["published_at"] is not None:
                break
            await asyncio.sleep(0.01)
        assert manager.store.get_task(outcome.execution_id)["execution_id"] == (
            outcome.execution_id
        )

    asyncio.run(scenario())


def test_launcher_timeout_is_reported_as_launch_interrupted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = install_manager(monkeypatch, tmp_path / "executions")

    def timeout_after_acceptance(
        _execution_id: str, *, backend: str, unit: str | None
    ) -> None:
        assert backend == "popen"
        assert unit is None
        raise TimeoutError("launcher response timed out")

    monkeypatch.setattr(manager, "_spawn_worker", timeout_after_acceptance)

    outcome = asyncio.run(
        app.code_mode(label="launch timeout", code="1 + 2", cwd=str(tmp_path))
    )

    assert isinstance(outcome, app.CodeModeError)
    assert outcome.error.code == "launch_interrupted"
    assert outcome.error.message == "launcher response timed out"
    record = manager.store.get(outcome.execution_id)
    assert record["state"] == "failed"
    assert record["reason"] == "launch_interrupted"


def test_immediate_task_mode_uses_execution_id_as_handle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = install_manager(monkeypatch, tmp_path / "executions")
    release_launch = threading.Event()

    def stalled_spawn(_execution_id: str, *, backend: str, unit: str | None) -> None:
        assert backend == "popen"
        assert unit is None
        release_launch.wait(timeout=0.2)

    monkeypatch.setattr(manager, "_spawn_worker", stalled_spawn)
    monkeypatch.setattr(app, "_INLINE_RESPONSE_DEADLINE_SECONDS", 0.15)

    async def scenario() -> None:
        started = time.monotonic()
        outcome = await app.code_mode(
            label="immediate awareness",
            code="1 + 2",
            cwd=str(tmp_path),
            mode="task",
        )
        assert time.monotonic() - started < 0.1
        assert isinstance(outcome, app.CodeModeTask)
        assert manager.store.get_task(outcome.execution_id)["execution_id"] == (
            outcome.execution_id
        )
        release_launch.set()

    asyncio.run(scenario())
