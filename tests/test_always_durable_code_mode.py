from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path

import pytest

import gpt_dive.execution_manager as execution_manager
from gpt_dive import app
from gpt_dive.code_mode_protocol import CODE_MODE_WORKER_PROTOCOL
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
) -> app.CodeModeOutcome:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        outcome = await app.task(
            app.TaskGetRequest(action="get", execution_id=execution_id)
        )
        if isinstance(outcome, app.CodeModeTask):
            await asyncio.sleep(0.01)
            continue
        assert isinstance(outcome, (app.CodeModeCompleted, app.CodeModeError))
        return outcome
    raise AssertionError("Code Mode Task did not finish")


@pytest.mark.parametrize(
    ("outcome_type", "fields"),
    [
        (app.CodeModeCompleted, {"kind", "execution_id", "output"}),
        (app.CodeModeTask, {"kind", "execution_id", "state"}),
        (app.CodeModeError, {"kind", "execution_id", "code", "message"}),
    ],
)
def test_public_outcome_models_lock_llm_contract_fields(
    outcome_type: type, fields: set[str]
) -> None:
    assert set(outcome_type.model_fields) == fields
    assert outcome_type.model_config["extra"] == "forbid"


def test_inline_completion_returns_typed_output_without_publication_or_print_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = install_manager(monkeypatch, tmp_path / "executions")
    expected = {"answer": 3, "items": [1, "two", {"three": 3}]}

    outcome = asyncio.run(
        app.code_mode(
            label="inline completion",
            code="""print('INTERMEDIATE NOISE')
{'answer': 3, 'items': [1, 'two', {'three': 3}]}""",
            cwd=str(tmp_path),
        )
    )

    assert isinstance(outcome, app.CodeModeCompleted)
    assert outcome.model_dump() == {
        "kind": "completed",
        "execution_id": outcome.execution_id,
        "output": expected,
    }
    record = manager.store.get(outcome.execution_id)
    assert record["state"] == "completed"
    assert record["published_at"] is None
    assert record["request_path"] == ""
    assert not (manager.root / outcome.execution_id / "input.json").exists()
    envelope = json.loads(Path(str(record["stdout_path"])).read_text())
    assert envelope == {
        "v": CODE_MODE_WORKER_PROTOCOL,
        "ok": True,
        "output": expected,
    }


def test_inline_runtime_failure_exposes_compact_error_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_manager(monkeypatch, tmp_path / "executions")

    outcome = asyncio.run(
        app.code_mode(
            label="runtime failure",
            code="raise ValueError('X' * 100_000)",
            cwd=str(tmp_path),
        )
    )

    assert isinstance(outcome, app.CodeModeError)
    assert outcome.model_dump() == {
        "kind": "error",
        "execution_id": outcome.execution_id,
        "code": "execution_error",
        "message": "Code Mode Execution failed.",
    }


def test_inline_wait_expiry_publishes_same_continuing_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = install_manager(monkeypatch, tmp_path / "executions")
    monkeypatch.setattr(app, "_INLINE_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(app, "_INLINE_RESPONSE_DEADLINE_SECONDS", 1.0)

    async def scenario() -> None:
        outcome = await app.code_mode(
            label="slow arithmetic",
            code="await run_command('sleep 0.12; printf SLOW')",
            cwd=str(tmp_path),
        )
        assert isinstance(outcome, app.CodeModeTask)
        execution_id = outcome.execution_id
        assert outcome.model_dump() == {
            "kind": "task",
            "execution_id": execution_id,
            "state": outcome.state,
        }
        assert manager.store.get_task(execution_id)["execution_id"] == execution_id

        first = await wait_task_ready(execution_id)
        second = await app.task(
            app.TaskGetRequest(action="get", execution_id=execution_id)
        )
        assert isinstance(first, app.CodeModeCompleted)
        assert isinstance(second, app.CodeModeCompleted)
        assert first.model_dump() == second.model_dump()
        assert first.execution_id == execution_id
        assert first.output["stdout"] == "SLOW"
        assert set(first.model_dump()) == {"kind", "execution_id", "output"}

        dismissed = await app.task(
            app.TaskDismissRequest(action="dismiss", execution_id=execution_id)
        )
        assert isinstance(dismissed, app.TaskDismissOutput)
        assert dismissed.dismissed is True

    asyncio.run(scenario())


def test_task_get_keeps_lost_execution_in_error_vocabulary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = install_manager(monkeypatch, tmp_path / "executions")

    async def scenario() -> None:
        started = await app.code_mode(
            label="retained result",
            code="{'answer': 3}",
            cwd=str(tmp_path),
            mode="task",
        )
        assert isinstance(started, app.CodeModeTask)
        completed = await wait_task_ready(started.execution_id)
        assert isinstance(completed, app.CodeModeCompleted)

        record = manager.store.get(started.execution_id)
        Path(str(record["stdout_path"])).unlink()

        first = await app.task(
            app.TaskGetRequest(action="get", execution_id=started.execution_id)
        )
        second = await app.task(
            app.TaskGetRequest(action="get", execution_id=started.execution_id)
        )
        assert isinstance(first, app.CodeModeError)
        assert isinstance(second, app.CodeModeError)
        assert first.model_dump() == {
            "kind": "error",
            "execution_id": started.execution_id,
            "code": "lost",
            "message": "Code Mode Execution outcome is no longer observable.",
        }
        assert second.model_dump() == first.model_dump()

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

    def stalled_popen(*_args: object, **_kwargs: object) -> None:
        release_launch.wait(timeout=0.3)

    monkeypatch.setattr(execution_manager.subprocess, "Popen", stalled_popen)
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
    monkeypatch.setattr(
        execution_manager.subprocess,
        "Popen",
        lambda *_args, **_kwargs: None,
    )
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
        assert outcome.model_dump() == {
            "kind": "error",
            "execution_id": outcome.execution_id,
            "code": "response_deadline_exceeded",
            "message": (
                "Code Mode Execution was accepted, but response shaping did not "
                "finish before the response deadline."
            ),
        }
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

    def timeout_popen(*_args: object, **_kwargs: object) -> None:
        raise TimeoutError("launcher response timed out")

    monkeypatch.setattr(execution_manager.subprocess, "Popen", timeout_popen)

    outcome = asyncio.run(
        app.code_mode(label="launch timeout", code="1 + 2", cwd=str(tmp_path))
    )

    assert isinstance(outcome, app.CodeModeError)
    assert outcome.model_dump() == {
        "kind": "error",
        "execution_id": outcome.execution_id,
        "code": "launch_interrupted",
        "message": "Code Mode Worker could not be launched.",
    }
    record = manager.store.get(outcome.execution_id)
    assert record["state"] == "failed"
    assert record["reason"] == "launch_interrupted"
    assert "launcher response timed out" in Path(str(record["stderr_path"])).read_text()


def test_immediate_task_mode_uses_execution_id_as_handle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = install_manager(monkeypatch, tmp_path / "executions")
    release_launch = threading.Event()

    def stalled_popen(*_args: object, **_kwargs: object) -> None:
        release_launch.wait(timeout=0.2)

    monkeypatch.setattr(execution_manager.subprocess, "Popen", stalled_popen)
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
        assert outcome.model_dump() == {
            "kind": "task",
            "execution_id": outcome.execution_id,
            "state": outcome.state,
        }
        assert manager.store.get_task(outcome.execution_id)["execution_id"] == (
            outcome.execution_id
        )
        collected = await app.task(
            app.TaskGetRequest(action="get", execution_id=outcome.execution_id)
        )
        assert isinstance(collected, app.CodeModeTask)
        assert collected.model_dump() == outcome.model_dump()
        release_launch.set()

    asyncio.run(scenario())
