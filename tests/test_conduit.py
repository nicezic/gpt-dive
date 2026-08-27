from __future__ import annotations

import asyncio
import time
from pathlib import Path

from gpt_dive.conduit.runtime import ConduitRuntime
from gpt_dive.execution_manager import ExecutionManager
from gpt_dive.task_store import TaskStore


class RecordingPublisher:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def publish(self, event: dict[str, object]) -> str:
        self.events.append(event)
        return f"1-{len(self.events)}"


def _runtime(tmp_path: Path) -> tuple[ConduitRuntime, RecordingPublisher]:
    executions = ExecutionManager(tmp_path / "executions")
    executions._systemd_available = False
    task_store = TaskStore(tmp_path / "tasks.sqlite3")
    publisher = RecordingPublisher()
    return ConduitRuntime(
        executions=executions, task_store=task_store, publisher=publisher
    ), publisher


def test_conduit_mcp_surface_is_one_tool() -> None:
    from gpt_dive.conduit.server import mcp

    tools = asyncio.run(mcp.list_tools())
    assert [tool.name for tool in tools] == ["c"]


def test_start_returns_compact_snapshot_and_collect_is_non_destructive(
    tmp_path: Path,
) -> None:
    runtime, publisher = _runtime(tmp_path)

    started = runtime.call(
        action="start",
        label="ten-second-canary",
        command="sleep 0.12; printf DONE",
        timeout=3,
    )
    task_id = started["result"]["task_id"]
    execution_id = started["result"]["execution_id"]
    assert task_id != execution_id
    assert started["result"]["status"] == "running"
    assert not (runtime.rt.executions.root / execution_id / "conduit.json").exists()
    assert started["tasks"] == [
        {
            "id": task_id,
            "label": "ten-second-canary",
            "status": "running",
            "age_sec": started["tasks"][0]["age_sec"],
        }
    ]
    assert set(started["tasks"][0]) == {"id", "label", "status", "age_sec"}

    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        snapshot = runtime.call(action="sync", text="peek")
        if snapshot["tasks"][0]["status"] == "done":
            break
        time.sleep(0.03)
    else:
        raise AssertionError("canary execution did not complete")

    first = runtime.call(action="collect", task_id=task_id)
    second = runtime.call(action="collect", task_id=task_id)
    assert first["result"]["ready"] is True
    assert first["result"]["stdout"] == "DONE"
    assert second["result"]["stdout"] == "DONE"
    assert second["tasks"][0]["status"] == "done"
    assert "stdout" not in second["tasks"][0]
    actions = [event["action"] for event in publisher.events]
    assert actions[0] == "start"
    assert "sync" in actions[1:-2]
    assert actions[-2:] == ["collect", "collect"]


def test_ack_hides_terminal_task_but_keeps_result_retrievable(tmp_path: Path) -> None:
    runtime, publisher = _runtime(tmp_path)
    started = runtime.call(
        action="start",
        label="ack-canary",
        command="printf ACKME",
        timeout=3,
    )
    task_id = started["result"]["task_id"]
    execution_id = started["result"]["execution_id"]

    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        collected = runtime.call(action="collect", task_id=task_id)
        if collected["result"]["ready"]:
            break
        time.sleep(0.03)
    else:
        raise AssertionError("ack canary execution did not complete")

    acked = runtime.call(action="ack", task_id=task_id)
    assert acked["result"] == {"task_id": task_id, "status": "done", "acked": True}
    assert acked["tasks"] == []

    try:
        runtime.call(action="collect", task_id=task_id)
    except KeyError:
        pass
    else:
        raise AssertionError("acked Task awareness should be removed")
    assert runtime.rt.executions.result(execution_id)["stdout"] == "ACKME"
    assert publisher.events[-1]["action"] == "ack"


def test_ack_rejects_running_task(tmp_path: Path) -> None:
    runtime, _ = _runtime(tmp_path)
    started = runtime.call(
        action="start", label="still-running", command="sleep 1", timeout=3
    )
    task_id = started["result"]["task_id"]

    try:
        runtime.call(action="ack", task_id=task_id)
    except ValueError as exc:
        assert "terminal or lost task" in str(exc)
    else:
        raise AssertionError("running task should not be acked")


def test_snapshot_includes_other_tasks_from_shared_store(tmp_path: Path) -> None:
    runtime, _ = _runtime(tmp_path)
    execution_id = str(
        runtime.rt.executions.start("sleep 1", timeout=3)["execution_id"]
    )
    external = runtime.rt.task_store.create(
        execution_id=execution_id, label="external-task"
    )

    snapshot = runtime.call(action="sync", text="peek")

    assert snapshot["tasks"] == [
        {
            "id": external["task_id"],
            "label": "external-task",
            "status": "running",
            "age_sec": snapshot["tasks"][0]["age_sec"],
        }
    ]
    runtime.rt.executions.cancel(execution_id)


def test_dive_and_conduit_share_task_domain(tmp_path: Path) -> None:
    import gpt_dive
    import gpt_dive.app as app_module

    jobs_root = tmp_path / "executions"
    jobs_root.mkdir()
    task_db = tmp_path / "tasks.sqlite3"

    original_root = gpt_dive.executions.root
    original_systemd = gpt_dive.executions._systemd_available
    original_task_store = app_module.task_store
    try:
        gpt_dive.executions.root = jobs_root
        gpt_dive.executions._systemd_available = False
        app_module.task_store = TaskStore(task_db)

        conduit_jobs = ExecutionManager(jobs_root)
        conduit_jobs._systemd_available = False
        runtime = ConduitRuntime(
            executions=conduit_jobs,
            task_store=TaskStore(task_db),
            publisher=RecordingPublisher(),
        )

        conduit_started = runtime.call(
            action="start",
            label="from-conduit",
            command="sleep 0.3; printf CONDUIT",
            timeout=3,
        )
        conduit_task_id = str(conduit_started["result"]["task_id"])
        conduit_execution_id = str(conduit_started["result"]["execution_id"])

        dive_list = asyncio.run(gpt_dive.code_mode("await task_list()"))["result"][
            "tasks"
        ]
        assert conduit_task_id in {str(task["task_id"]) for task in dive_list}

        dive_started = asyncio.run(
            gpt_dive.code_mode(
                'x = 0\nfor _ in range(5000000):\n    x += 1\n{"origin": "dive"}',
                task={
                    "label": "from-dive",
                    "status": "TODOS 3/9",
                },
            )
        )
        dive_task_id = str(dive_started["task_id"])

        conduit_snapshot = runtime.call(action="sync", text="refresh")["tasks"]
        assert {str(task["id"]) for task in conduit_snapshot} == {
            conduit_task_id,
            dive_task_id,
        }
        dive_snapshot = next(
            task for task in conduit_snapshot if task["id"] == dive_task_id
        )
        assert dive_snapshot["status_label"] == "TODOS 3/9"

        runtime.rt.executions.cancel(conduit_execution_id)
        asyncio.run(
            gpt_dive.code_mode("await task_cancel(PAYLOAD)", payload=dive_task_id)
        )
    finally:
        app_module.task_store = original_task_store
        gpt_dive.executions.root = original_root
        gpt_dive.executions._systemd_available = original_systemd


def test_conduit_snapshot_is_bounded(tmp_path: Path) -> None:
    runtime, _ = _runtime(tmp_path)
    for index in range(9):
        runtime.rt.task_store.create(
            execution_id=f"missing-{index}",
            label=f"task-{index}",
            state="lost",
        )

    assert len(runtime.snapshot()) == 8


def test_every_action_returns_task_snapshot(tmp_path: Path) -> None:
    runtime, _ = _runtime(tmp_path)
    assert runtime.call(action="sync", text="hello") == {
        "result": {"text": "hello"},
        "tasks": [],
    }
    assert runtime.call(action="emit", text="answer") == {
        "result": {"emitted": True},
        "tasks": [],
    }


def test_emit_event_carries_optional_session_id(tmp_path: Path) -> None:
    runtime, publisher = _runtime(tmp_path)

    assert runtime.call(action="emit", session_id="acp-session-1", text="answer") == {
        "result": {"emitted": True},
        "tasks": [],
    }
    assert publisher.events[-1]["session_id"] == "acp-session-1"
    assert publisher.events[-1]["result"] == {"text": "answer"}

    runtime.call(action="emit", text="legacy")
    assert "session_id" not in publisher.events[-1]


def test_action_validation_is_explicit(tmp_path: Path) -> None:
    runtime, _ = _runtime(tmp_path)

    for action, message in [
        ("start", "requires command"),
        ("collect", "requires task_id"),
        ("ack", "requires task_id"),
        ("sync", "requires text"),
        ("emit", "requires text"),
    ]:
        try:
            runtime.call(action=action)
        except ValueError as exc:
            assert message in str(exc)
        else:
            raise AssertionError(f"{action} should have failed")

    try:
        runtime.call(action="emit", text="answer", session_id="   ")
    except ValueError as exc:
        assert "session_id must not be empty" in str(exc)
    else:
        raise AssertionError("blank emit session_id should have failed")

    try:
        runtime.call(action="start", command="true", label="x" * 81)
    except ValueError as exc:
        assert "80 characters or fewer" in str(exc)
    else:
        raise AssertionError("oversized label should have failed")

    try:
        runtime.call(action="future")
    except ValueError as exc:
        assert "start, sync, collect, ack, emit" in str(exc)
    else:
        raise AssertionError("unknown action should have failed")
