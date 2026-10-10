from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from gpt_dive import app
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
        kind="test",
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


def test_active_tracked_tasks_projects_structured_views_with_session_scoping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    raw_tasks = [
        {
            "execution_id": f"e{index:05d}",
            "label": f"task-{index}",
            "state": "running",
            "reason": None,
            "accepted_at": "2026-09-06T00:00:00Z",
            "finished_at": None,
            "published_at": "2026-09-06T00:00:01Z",
            "updated_at": "2026-09-06T00:00:02Z",
            "elapsed_seconds": index * 10,
        }
        for index in range(12)
    ]
    monkeypatch.setattr(app, "_task_list", lambda *, limit=None: raw_tasks[:limit])

    # Unscoped projection (no ctx) returns up to TRACKED_TASKS_LIMIT (8)
    all_views = asyncio.run(app._tracked_tasks_snapshot())
    assert len(all_views) == app.TRACKED_TASKS_LIMIT
    assert all(isinstance(v, app.TrackedTaskView) for v in all_views)
    assert all_views[0].execution_id == "e00000"
    assert all_views[0].elapsed_seconds == 0

    # Session-scoped projection only returns tasks published within that session
    ctx1: Any = SimpleNamespace(
        session=SimpleNamespace(_connection=SimpleNamespace(state={}))
    )
    app._record_session_task(ctx1, "e00001")
    app._record_session_task(ctx1, "e00003")

    scoped_views = asyncio.run(app._tracked_tasks_snapshot(ctx1))
    assert [v.execution_id for v in scoped_views] == ["e00001", "e00003"]
    assert scoped_views[0].label == "task-1"
    assert scoped_views[1].label == "task-3"

    # Other session with no published tasks gets empty projection
    ctx2: Any = SimpleNamespace(
        session=SimpleNamespace(_connection=SimpleNamespace(state={}))
    )
    empty_views = asyncio.run(app._tracked_tasks_snapshot(ctx2))
    assert empty_views == []


def test_tracked_tasks_guidance_is_first_then_every_ninth_followup() -> None:
    ctx: Any = SimpleNamespace(
        session=SimpleNamespace(_connection=SimpleNamespace(state={}))
    )
    task = app.TrackedTaskView(
        execution_id="abc123",
        label="build",
        state="running",
        reason=None,
        elapsed_seconds=1,
    )

    outputs = [app._tracked_tasks_guidance(ctx, [task]) for _ in range(19)]

    assert outputs[0] == app._TRACKED_TASKS_GUIDANCE
    assert all(value is None for value in outputs[1:9])
    assert outputs[9] == app._TRACKED_TASKS_GUIDANCE
    assert all(value is None for value in outputs[10:18])
    assert outputs[18] == app._TRACKED_TASKS_GUIDANCE


def test_tracked_tasks_guidance_resets_when_tasks_disappear_or_change() -> None:
    ctx: Any = SimpleNamespace(
        session=SimpleNamespace(_connection=SimpleNamespace(state={}))
    )
    first = app.TrackedTaskView(
        execution_id="abc123",
        label="build",
        state="running",
        reason=None,
        elapsed_seconds=1,
    )
    second = app.TrackedTaskView(
        execution_id="def456",
        label="tests",
        state="running",
        reason=None,
        elapsed_seconds=1,
    )

    assert app._tracked_tasks_guidance(ctx, [first]) == app._TRACKED_TASKS_GUIDANCE
    assert app._tracked_tasks_guidance(ctx, [first]) is None
    assert (
        app._tracked_tasks_guidance(ctx, [first, second]) == app._TRACKED_TASKS_GUIDANCE
    )
    assert app._tracked_tasks_guidance(ctx, [second, first]) is None
    assert app._tracked_tasks_guidance(ctx, []) is None
    assert app._tracked_tasks_guidance(ctx, [first]) == app._TRACKED_TASKS_GUIDANCE


def test_active_tasks_are_projected_before_terminal_backlog(tmp_path: Path) -> None:
    manager = manager_for_test(tmp_path / "executions")
    completed = manager.start("true", label="old done", publish=True)
    wait_ready(manager, str(completed["execution_id"]))
    running = manager.start("sleep 2", label="active", publish=True)

    projected = manager.tasks(limit=1)

    assert projected[0]["execution_id"] == running["execution_id"]
    manager.cancel(str(running["execution_id"]))
