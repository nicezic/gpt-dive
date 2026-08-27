from __future__ import annotations

import time
from pathlib import Path

from gpt_dive.execution_manager import ExecutionManager
from gpt_dive.task_runtime import TaskRuntime, ack_task, collect_task, refresh_task
from gpt_dive.task_store import TaskStore


def _wait_terminal(executions: ExecutionManager, execution_id: str) -> None:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if executions.status(execution_id)["status"] != "running":
            return
        time.sleep(0.02)
    raise AssertionError("execution did not become terminal")


def test_raw_shell_task_success_and_failure_share_runtime(tmp_path: Path) -> None:
    executions = ExecutionManager(tmp_path / "executions")
    executions._systemd_available = False
    store = TaskStore(tmp_path / "tasks.sqlite3")

    ok_execution = str(executions.start("printf OK", timeout=3)["execution_id"])
    ok = store.create(execution_id=ok_execution, label="raw-ok")
    failed_execution = str(
        executions.start("printf BAD; exit 7", timeout=3)["execution_id"]
    )
    failed = store.create(execution_id=failed_execution, label="raw-fail")

    _wait_terminal(executions, ok_execution)
    _wait_terminal(executions, failed_execution)

    ok_task = refresh_task(TaskRuntime(executions, store), ok)
    failed_task = refresh_task(TaskRuntime(executions, store), failed)
    assert ok_task["state"] == "completed"
    assert failed_task["state"] == "failed"

    collected = collect_task(TaskRuntime(executions, store), str(ok["task_id"]))
    assert collected["ready"] is True
    assert collected["result"]["stdout"] == "OK"

    text_execution = str(
        executions.start("printf '%s' '-m gpt_dive.code_mode_worker'", timeout=3)[
            "execution_id"
        ]
    )
    text_task = store.create(execution_id=text_execution, label="raw-text")
    _wait_terminal(executions, text_execution)
    text_collected = collect_task(
        TaskRuntime(executions, store), str(text_task["task_id"])
    )
    assert text_collected["task"]["state"] == "completed"
    assert text_collected["result"]["stdout"] == "-m gpt_dive.code_mode_worker"


def test_missing_execution_becomes_lost_and_can_be_acked(tmp_path: Path) -> None:
    executions = ExecutionManager(tmp_path / "executions")
    executions._systemd_available = False
    store = TaskStore(tmp_path / "tasks.sqlite3")
    task = store.create(execution_id="missing-execution", label="missing")

    refreshed = refresh_task(TaskRuntime(executions, store), task)
    assert refreshed["state"] == "lost"

    acked = ack_task(TaskRuntime(executions, store), str(task["task_id"]))
    assert acked == {"task_id": task["task_id"], "state": "lost", "acked": True}
    assert store.list_tasks() == []


def test_probe_status_labels_extracts_static_status() -> None:
    from gpt_dive.task_runtime import probe_status_labels

    tasks = [
        {"task_id": str(i), "state": "working", "status": f"status-{i}"}
        for i in range(4)
    ]
    labels = probe_status_labels(tasks)
    assert labels == {
        "0": "status-0",
        "1": "status-1",
        "2": "status-2",
        "3": "status-3",
    }


def test_probe_status_labels_only_probes_working_tasks() -> None:
    from gpt_dive.task_runtime import probe_status_labels

    tasks = [
        {"task_id": "1", "state": "working", "status": "active"},
        {"task_id": "2", "state": "completed", "status": "done"},
        {"task_id": "3", "state": "cancelled", "status": "stopped"},
    ]
    labels = probe_status_labels(tasks)
    assert labels == {"1": "active"}
