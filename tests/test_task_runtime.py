from __future__ import annotations

import time
from pathlib import Path

from gpt_dive.job_manager import JobManager
from gpt_dive.task_runtime import ack_task, collect_task, refresh_task
from gpt_dive.task_store import TaskStore


def _wait_terminal(jobs: JobManager, execution_id: str) -> None:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if jobs.status(execution_id)["status"] != "running":
            return
        time.sleep(0.02)
    raise AssertionError("execution did not become terminal")


def test_raw_shell_task_success_and_failure_share_runtime(tmp_path: Path) -> None:
    jobs = JobManager(tmp_path / "jobs")
    jobs._systemd_available = False
    store = TaskStore(tmp_path / "tasks.sqlite3")

    ok_execution = str(jobs.start("printf OK", timeout=3)["job_id"])
    ok = store.create(execution_id=ok_execution, label="raw-ok")
    failed_execution = str(jobs.start("printf BAD; exit 7", timeout=3)["job_id"])
    failed = store.create(execution_id=failed_execution, label="raw-fail")

    _wait_terminal(jobs, ok_execution)
    _wait_terminal(jobs, failed_execution)

    ok_task = refresh_task(jobs, store, ok)
    failed_task = refresh_task(jobs, store, failed)
    assert ok_task["state"] == "completed"
    assert failed_task["state"] == "failed"

    collected = collect_task(jobs, store, str(ok["task_id"]))
    assert collected["ready"] is True
    assert collected["result"]["stdout"] == "OK"

    text_execution = str(
        jobs.start("printf '%s' '-m gpt_dive.code_mode_worker'", timeout=3)["job_id"]
    )
    text_task = store.create(execution_id=text_execution, label="raw-text")
    _wait_terminal(jobs, text_execution)
    text_collected = collect_task(jobs, store, str(text_task["task_id"]))
    assert text_collected["task"]["state"] == "completed"
    assert text_collected["result"]["stdout"] == "-m gpt_dive.code_mode_worker"


def test_missing_execution_becomes_lost_and_can_be_acked(tmp_path: Path) -> None:
    jobs = JobManager(tmp_path / "jobs")
    jobs._systemd_available = False
    store = TaskStore(tmp_path / "tasks.sqlite3")
    task = store.create(execution_id="missing-execution", label="missing")

    refreshed = refresh_task(jobs, store, task)
    assert refreshed["state"] == "lost"

    acked = ack_task(jobs, store, str(task["task_id"]))
    assert acked == {"task_id": task["task_id"], "state": "lost", "acked": True}
    assert store.list_tasks() == []
