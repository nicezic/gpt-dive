from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from gpt_dive.execution_manager import ExecutionManager


def popen_manager(
    root: Path,
    *,
    work_timeout_seconds: float = 5.0,
    cleanup_timeout_seconds: float = 2.0,
) -> ExecutionManager:
    manager = ExecutionManager(
        root,
        work_timeout_seconds=work_timeout_seconds,
        cleanup_timeout_seconds=cleanup_timeout_seconds,
    )
    manager._systemd_available = False
    return manager


def wait_terminal(
    manager: ExecutionManager, execution_id: str, *, timeout: float = 5.0
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = manager.status(execution_id)
        if state["state"] not in {"accepted", "running"}:
            return state
        time.sleep(0.03)
    raise AssertionError(f"Execution did not finish: {manager.status(execution_id)}")


def test_execution_survives_manager_reconstruction_and_preserves_output(
    tmp_path: Path,
) -> None:
    root = tmp_path / "executions"
    manager = popen_manager(root)
    started = manager.start(
        "printf '  leading\\ntrailing  \\n'",
        label="preserve output",
    )

    reloaded = popen_manager(root)
    terminal = wait_terminal(reloaded, str(started["execution_id"]))
    result = reloaded.result(str(started["execution_id"]))

    assert terminal["state"] == "completed"
    assert result["stdout"] == "  leading\ntrailing  \n"
    assert result["stderr"] == ""


def test_explicit_cancel_reaches_terminal_cancelled_state(tmp_path: Path) -> None:
    manager = popen_manager(tmp_path / "executions")
    started = manager.start("sleep 30", label="cancel me", publish=True)

    cancelled = manager.cancel(str(started["execution_id"]))
    terminal = wait_terminal(manager, str(started["execution_id"]))

    assert cancelled["cancel_requested"] is True
    assert terminal["state"] == "cancelled"
    assert terminal["reason"] == "cancelled"


def test_work_cutoff_is_failed_with_deadline_reason(tmp_path: Path) -> None:
    manager = popen_manager(
        tmp_path / "executions",
        work_timeout_seconds=0.15,
        cleanup_timeout_seconds=1.0,
    )
    started = manager.start("sleep 30", label="deadline")

    terminal = wait_terminal(manager, str(started["execution_id"]))

    assert terminal["state"] == "failed"
    assert terminal["reason"] == "deadline_exceeded"


def test_normal_completion_kills_daemonized_descendants_in_popen_backend(
    tmp_path: Path,
) -> None:
    manager = popen_manager(tmp_path / "executions")
    pid_path = tmp_path / "escaped.pid"
    command = (
        f"setsid sh -c 'echo $$ > {pid_path}; sleep 30' "
        ">/dev/null 2>&1 & printf spawned"
    )

    started = manager.start(command, label="tree containment")
    terminal = wait_terminal(manager, str(started["execution_id"]))
    escaped_pid = int(pid_path.read_text().strip())

    assert terminal["state"] == "completed"
    assert manager.result(str(started["execution_id"]))["stdout"] == "spawned"
    assert not Path(f"/proc/{escaped_pid}").exists()


def test_outcome_marker_recovers_terminal_state_after_worker_store_gap(
    tmp_path: Path,
) -> None:
    manager = popen_manager(tmp_path / "executions")
    execution_id = "b" * 32
    execution_dir = manager.root / execution_id
    execution_dir.mkdir()
    request_path = execution_dir / "request.json"
    stdout_path = execution_dir / "stdout.log"
    stderr_path = execution_dir / "stderr.log"
    outcome_path = execution_dir / "outcome.json"
    request_path.write_text("{}")
    stdout_path.write_text("OK")
    stderr_path.write_text("")
    outcome_path.write_text(json.dumps({"v": 1, "exit_code": 0, "reason": None}))
    manager.store.create(
        execution_id=execution_id,
        kind="shell",
        label="recover marker",
        cwd=str(tmp_path),
        backend="popen",
        systemd_unit=None,
        work_timeout_seconds=5,
        cleanup_timeout_seconds=2,
        request_path=request_path,
        artifact_dir=execution_dir,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        outcome_path=outcome_path,
    )
    assert manager.store.claim(
        execution_id,
        worker_pid=os.getpid() + 1_000_000,
        worker_start_ticks=None,
    )

    terminal = manager.status(execution_id)

    assert terminal["state"] == "completed"
    assert manager.result(execution_id)["stdout"] == "OK"


def test_retention_deletes_dismissed_terminal_execution(tmp_path: Path) -> None:
    manager = popen_manager(tmp_path / "executions")
    started = manager.start("true", label="retention", publish=True)
    execution_id = str(started["execution_id"])
    wait_terminal(manager, execution_id)
    manager.dismiss(execution_id)
    manager.retention_days = 0

    assert manager.cleanup() == 1
    assert not (manager.root / execution_id).exists()


def test_spawn_error_after_worker_claim_does_not_reclassify_or_delete_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = popen_manager(tmp_path / "executions")

    def claimed_then_error(
        execution_id: str, *, backend: str, unit: str | None
    ) -> None:
        assert manager.store.claim(
            execution_id,
            worker_pid=999_999_999,
            worker_start_ticks=None,
        )
        raise TimeoutError("ambiguous launcher response")

    monkeypatch.setattr(manager, "_spawn_worker", claimed_then_error)

    started = manager.start(
        "true",
        label="claimed launch",
        input_payload={"secret": "ephemeral"},
    )
    record = manager.store.get(str(started["execution_id"]))

    assert started["state"] == "running"
    assert record["reason"] is None
    assert Path(str(record["request_path"])).is_file()
    assert (Path(str(record["artifact_dir"])) / "input.json").is_file()


def test_spawn_error_before_claim_fails_closed_and_discards_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = popen_manager(tmp_path / "executions")

    def launch_error(execution_id: str, *, backend: str, unit: str | None) -> None:
        raise RuntimeError("launcher failed")

    monkeypatch.setattr(manager, "_spawn_worker", launch_error)

    with pytest.raises(RuntimeError, match="launcher failed"):
        manager.start(
            "true",
            label="unclaimed launch",
            input_payload={"secret": "ephemeral"},
        )

    record = manager.store.list_executions()[0]
    assert record["state"] == "failed"
    assert record["reason"] == "launch_interrupted"
    assert record["request_path"] == ""
    assert not (Path(str(record["artifact_dir"])) / "input.json").exists()
