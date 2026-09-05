from __future__ import annotations

import json
import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest

import gpt_dive.execution_worker as execution_worker_module
from gpt_dive.execution_store import ExecutionStore, parse_time
from gpt_dive.execution_worker import run_execution


def create_execution(
    store: ExecutionStore,
    root: Path,
    *,
    label: str = "store test",
    publish: bool = False,
) -> dict[str, object]:
    execution_id = "a" * 6
    artifact_dir = root / execution_id
    artifact_dir.mkdir(exist_ok=True)
    return store.create(
        execution_id=execution_id,
        kind="code_mode",
        label=label,
        cwd=str(root),
        backend="popen",
        systemd_unit=None,
        work_timeout_seconds=43190,
        cleanup_timeout_seconds=10,
        request_path=artifact_dir / "request.json",
        artifact_dir=artifact_dir,
        stdout_path=artifact_dir / "stdout.log",
        stderr_path=artifact_dir / "stderr.log",
        outcome_path=artifact_dir / "outcome.json",
        publish=publish,
    )


def test_store_removes_obsolete_run_command_schema(tmp_path: Path) -> None:
    path = tmp_path / "runtime.sqlite3"
    ExecutionStore(path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "ALTER TABLE executions ADD COLUMN "
            "run_command_next_ordinal INTEGER NOT NULL DEFAULT 1"
        )
        connection.execute("DROP TABLE run_command_evidence")
        connection.execute(
            """
            CREATE TABLE run_command_evidence (
                execution_id TEXT NOT NULL,
                run_ordinal INTEGER NOT NULL,
                stdout BLOB NOT NULL,
                stderr BLOB NOT NULL,
                stdout_overflow INTEGER NOT NULL,
                stderr_overflow INTEGER NOT NULL,
                outcome TEXT NOT NULL,
                exit_code INTEGER,
                created_at TEXT NOT NULL,
                PRIMARY KEY (execution_id, run_ordinal)
            )
            """
        )

    ExecutionStore(path)

    with sqlite3.connect(path) as connection:
        execution_columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(executions)")
        }
        evidence_columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(run_command_evidence)")
        }
    assert "run_command_next_ordinal" not in execution_columns
    assert evidence_columns == {
        "execution_id",
        "run_ordinal",
        "stdout",
        "stderr",
        "stdout_overflow",
        "stderr_overflow",
        "exit_code",
        "duration_ms",
    }


def test_store_migrates_current_evidence_schema_without_dropping_rows(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runtime.sqlite3"
    store = ExecutionStore(path)
    create_execution(store, tmp_path)
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE run_command_evidence")
        connection.execute(
            """
            CREATE TABLE run_command_evidence (
                execution_id TEXT NOT NULL,
                run_ordinal INTEGER NOT NULL,
                stdout BLOB NOT NULL,
                stderr BLOB NOT NULL,
                stdout_overflow INTEGER NOT NULL,
                stderr_overflow INTEGER NOT NULL,
                PRIMARY KEY (execution_id, run_ordinal)
            )
            """
        )
        connection.execute(
            "INSERT INTO run_command_evidence VALUES (?, ?, ?, ?, ?, ?)",
            ("aaaaaa", 1, b"stdout", b"stderr", 0, 0),
        )

    migrated = ExecutionStore(path).get_run_command_evidence("aaaaaa", 1)

    assert migrated["stdout"] == b"stdout"
    assert migrated["stderr"] == b"stderr"
    assert migrated["exit_code"] is None
    assert migrated["duration_ms"] is None


def test_execution_and_task_share_one_identity_but_not_one_lifecycle(
    tmp_path: Path,
) -> None:
    store = ExecutionStore(tmp_path / "runtime.sqlite3")
    created = create_execution(store, tmp_path)

    assert created["state"] == "accepted"
    with pytest.raises(KeyError):
        store.get_task("a" * 6)

    assert store.claim("a" * 6, worker_pid=123, worker_start_ticks=456)
    assert not store.claim("a" * 6, worker_pid=789, worker_start_ticks=999)

    published = store.publish("a" * 6)
    assert published["execution_id"] == created["execution_id"]
    assert published["state"] == "running"

    completed = store.finish("a" * 6, exit_code=0)
    assert completed["state"] == "completed"
    assert store.get_task("a" * 6)["state"] == "completed"

    dismissed = store.dismiss("a" * 6)
    assert dismissed["dismissed_at"] is not None
    with pytest.raises(KeyError):
        store.get_task("a" * 6)


def test_cancel_before_claim_prevents_worker_authorization(tmp_path: Path) -> None:
    store = ExecutionStore(tmp_path / "runtime.sqlite3")
    create_execution(store, tmp_path)

    cancelled = store.request_cancel("a" * 6)

    assert cancelled["state"] == "cancelled"
    assert cancelled["reason"] == "cancelled"
    assert not store.claim("a" * 6, worker_pid=123, worker_start_ticks=456)


def test_rejected_worker_claim_cannot_run_user_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("gpt_dive.execution_worker._become_subreaper", lambda: None)
    store = ExecutionStore(tmp_path / "runtime.sqlite3")
    created = create_execution(store, tmp_path)
    marker = tmp_path / "side-effect"
    request_path = Path(str(created["request_path"]))
    request_path.write_text(
        json.dumps({"v": 1, "command": f"touch {marker}", "cwd": str(tmp_path)})
    )
    store.request_cancel("a" * 6)

    assert run_execution(store, "a" * 6) == 0
    assert not marker.exists()
    assert not request_path.exists()
    assert store.get("a" * 6)["request_path"] == ""


def test_deadline_cleanup_consumes_the_absolute_reserve_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ExecutionStore(tmp_path / "runtime.sqlite3")
    created = create_execution(store, tmp_path)
    Path(str(created["request_path"])).write_text(
        json.dumps({"v": 1, "command": "sleep 30", "cwd": str(tmp_path)})
    )

    class UnreapableProcess:
        pid = 4242
        returncode: int | None = None

        def poll(self) -> int | None:
            return self.returncode

    process = UnreapableProcess()
    cleanup_calls: list[int] = []

    def fail_cleanup(candidate: UnreapableProcess) -> bool:
        cleanup_calls.append(candidate.pid)
        candidate.returncode = -9
        return False

    work_deadline = parse_time(str(created["work_deadline_at"]))
    monkeypatch.setattr(execution_worker_module, "_become_subreaper", lambda: None)
    monkeypatch.setattr(execution_worker_module, "process_start_ticks", lambda _pid: 1)
    monkeypatch.setattr(execution_worker_module.signal, "signal", lambda *_args: None)
    monkeypatch.setattr(
        execution_worker_module.subprocess,
        "Popen",
        lambda *_args, **_kwargs: process,
    )
    monkeypatch.setattr(execution_worker_module, "_terminate_child", fail_cleanup)
    monkeypatch.setattr(
        execution_worker_module,
        "utc_now",
        lambda: work_deadline + timedelta(seconds=1),
    )

    assert run_execution(store, "a" * 6) == 1
    assert cleanup_calls == [process.pid]
    terminal = store.get("a" * 6)
    assert terminal["state"] == "lost"
    assert terminal["reason"] == "cleanup_unconfirmed"


def test_cancel_request_wins_a_concurrent_finish_transition(tmp_path: Path) -> None:
    store = ExecutionStore(tmp_path / "runtime.sqlite3")
    create_execution(store, tmp_path)
    assert store.claim("a" * 6, worker_pid=123, worker_start_ticks=456)

    store.request_cancel("a" * 6)
    terminal = store.finish("a" * 6, exit_code=0)

    assert terminal["state"] == "cancelled"
    assert terminal["reason"] == "cancelled"


def test_required_label_is_bounded(tmp_path: Path) -> None:
    store = ExecutionStore(tmp_path / "runtime.sqlite3")
    with pytest.raises(ValueError, match="must not be empty"):
        create_execution(store, tmp_path, label="  ")

    with pytest.raises(ValueError, match="80 characters"):
        create_execution(store, tmp_path, label="x" * 81)
