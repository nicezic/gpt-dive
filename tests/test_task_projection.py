from __future__ import annotations

import time
from pathlib import Path

import pytest

from gpt_dive.app import projection_revision, render_tracked_tasks
from gpt_dive.execution_manager import ExecutionManager, ExecutionNotFoundError


def manager_for_test(root: Path) -> ExecutionManager:
    manager = ExecutionManager(
        root,
        work_timeout_seconds=5,
        cleanup_timeout_seconds=2,
    )
    manager._systemd_available = False
    return manager


def wait_ready(
    manager: ExecutionManager, execution_id: str, *, timeout: float = 5.0
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = manager.task_with_result(execution_id)
        if result["ready"] or result.get("unavailable"):
            return result
        time.sleep(0.03)
    raise AssertionError("Task did not become ready")


def test_get_is_non_destructive_and_dismiss_only_removes_awareness(
    tmp_path: Path,
) -> None:
    manager = manager_for_test(tmp_path / "executions")
    started = manager.start(
        "printf TASK_OK",
        label="task result",
        kind="conduit",
        publish=True,
    )
    execution_id = str(started["execution_id"])

    first = wait_ready(manager, execution_id)
    second = manager.task_with_result(execution_id)

    assert isinstance(first["result"], dict)
    assert isinstance(second["result"], dict)
    assert first["result"]["stdout"] == "TASK_OK"
    assert second["result"]["stdout"] == "TASK_OK"
    dismissed = manager.dismiss_task(execution_id)
    assert dismissed["dismissed"] is True
    assert manager.result(execution_id)["stdout"] == "TASK_OK"
    with pytest.raises(ExecutionNotFoundError):
        manager.task_with_result(execution_id)


def test_projection_revision_ignores_elapsed_time_but_tracks_state() -> None:
    base = {
        "execution_id": "a" * 6,
        "label": "compile",
        "state": "running",
        "reason": None,
        "finished_at": None,
        "elapsed_seconds": 1,
    }
    later = {**base, "elapsed_seconds": 99}
    completed = {
        **later,
        "state": "completed",
        "finished_at": "2026-08-27T00:00:00Z",
    }

    assert projection_revision([base]) == projection_revision([later])
    assert projection_revision([base]) != projection_revision([completed])


def test_tracked_tasks_is_bounded_and_uses_single_execution_id() -> None:
    tasks = [
        {
            "execution_id": f"e{index:05d}",
            "label": f"task-{index}",
            "state": "running",
            "reason": None,
            "elapsed_seconds": index,
        }
        for index in range(20)
    ]

    rendered = render_tracked_tasks(tasks, limit=3, max_bytes=4096)

    assert rendered.startswith("TrackedTasks\n")
    assert rendered.splitlines()[1] == "task-0 · 🧵 running · 0:00 · e00000"
    assert "task-0" in rendered and "task-2" in rendered
    assert "task-3" not in rendered
    assert "0:00" in rendered
    assert "elapsed_seconds" not in rendered
    assert "task_id" not in rendered


def test_active_tasks_are_projected_before_terminal_backlog(tmp_path: Path) -> None:
    manager = manager_for_test(tmp_path / "executions")
    completed = manager.start("true", label="old done", publish=True)
    wait_ready(manager, str(completed["execution_id"]))
    running = manager.start("sleep 2", label="active", publish=True)

    projected = manager.tasks(limit=1)

    assert projected[0]["execution_id"] == running["execution_id"]
    manager.cancel(str(running["execution_id"]))
