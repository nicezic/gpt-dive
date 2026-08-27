from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from gpt_dive.execution_manager import ExecutionManager


def wait_done(manager: ExecutionManager, execution_id: str, timeout: float = 3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = manager.status(execution_id)
        if state["status"] != "running":
            return state
        time.sleep(0.03)
    raise AssertionError("execution did not finish")


def test_async_job_survives_new_manager_instance(tmp_path):
    manager = ExecutionManager(tmp_path)
    started = manager.start(
        "printf 'JOB_OK\\n'; sleep 0.15; printf 'DONE\\n'", timeout=2
    )
    reloaded = ExecutionManager(tmp_path)
    state = wait_done(reloaded, started["execution_id"])
    assert state["status"] == "completed"
    result = reloaded.result(started["execution_id"])
    assert result["exit_code"] == 0
    assert result["stdout"] == "JOB_OK\nDONE\n"


def test_cancel_marks_job_cancelled(tmp_path):
    manager = ExecutionManager(tmp_path)
    started = manager.start("sleep 30", timeout=60)
    manager.cancel(started["execution_id"])
    state = wait_done(manager, started["execution_id"])
    assert state["status"] == "cancelled"


def test_cleanup_removes_terminal_job_older_than_retention(tmp_path):
    manager = ExecutionManager(tmp_path, retention_days=5)
    started = manager.start("true", timeout=2)
    wait_done(manager, started["execution_id"])
    execution_dir = tmp_path / started["execution_id"]
    meta = manager._read_meta(execution_dir)
    meta["updated_at"] = (
        (datetime.now(UTC) - timedelta(days=6)).isoformat().replace("+00:00", "Z")
    )
    manager._write_meta(execution_dir, meta)
    assert manager.cleanup() == 1
    assert not execution_dir.exists()


def test_completed_child_is_reaped(tmp_path):
    manager = ExecutionManager(tmp_path)
    started = manager.start("true", timeout=2)
    wait_done(manager, started["execution_id"])
    deadline = time.monotonic() + 1.0
    proc = manager._proc_info(started["pid"])
    while time.monotonic() < deadline and proc is not None and proc["state"] == "Z":
        time.sleep(0.05)
        proc = manager._proc_info(started["pid"])
    assert proc is None or proc["state"] != "Z"


def test_cancel_requested_wins_even_if_exit_marker_exists(tmp_path):
    manager = ExecutionManager(tmp_path)
    started = manager.start("sleep 30", timeout=60)
    execution_dir = tmp_path / started["execution_id"]
    meta = manager._read_meta(execution_dir)
    meta["cancel_requested"] = True
    manager._write_meta(execution_dir, meta)
    (execution_dir / "exit_code").write_text("143\n")
    state = manager.status(started["execution_id"])
    assert state["status"] == "cancelled"
    unit = started.get("systemd_unit")
    if unit:
        import subprocess

        subprocess.run(["systemctl", "--user", "stop", unit], check=False)


def test_refresh_recovers_when_exit_code_appears_after_orphan_detection(
    tmp_path: Path,
) -> None:
    manager = ExecutionManager(tmp_path)
    started = manager.start("echo hello", timeout=5)
    execution_id = str(started["execution_id"])
    execution_dir = tmp_path / execution_id

    meta = manager._read_meta(execution_dir)
    meta["status"] = "failed"
    meta["status_message"] = (
        "Runner disappeared without an exit marker; recovered as an orphaned execution."
    )
    manager._write_meta(execution_dir, meta)

    (execution_dir / "exit_code").write_text("0\n")

    state = manager.status(execution_id)
    assert state["status"] == "completed"
    assert state["exit_code"] == 0
    assert state["status_message"] == "Command completed."
