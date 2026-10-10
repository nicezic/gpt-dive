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


def test_fresh_store_records_unique_error_events_and_groups_ty_codes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runtime.sqlite3"
    store = ExecutionStore(path)
    error = {
        "category": "monty",
        "code": "MontyTypingError",
        "detail": "sensitive path not retained",
        "diagnostics": [
            {"code": "unknown-argument", "message": "sensitive input"},
            {"code": "invalid-syntax", "message": "sensitive input"},
        ],
    }
    store.record_error_event("aaaaaa", error)
    store.record_error_event("aaaaaa", error)
    store.record_error_event("bbbbbb", error)

    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT error_json FROM error_events ORDER BY event_id"
        ).fetchall()
        categories = connection.execute(
            """
            SELECT json_extract(error_json, '$.category'),
                   json_extract(error_json, '$.code'), COUNT(*)
            FROM error_events GROUP BY 1, 2
            """
        ).fetchall()
        diagnostic_counts = connection.execute(
            """
            SELECT json_extract(d.value, '$.code'), COUNT(*)
            FROM error_events e, json_each(e.error_json, '$.diagnostics') d
            GROUP BY 1 ORDER BY 1
            """
        ).fetchall()

    assert len(rows) == 2
    assert "sensitive" not in str(rows)
    assert categories == [("monty", "MontyTypingError", 2)]
    assert diagnostic_counts == [("invalid-syntax", 2), ("unknown-argument", 2)]


@pytest.mark.parametrize(
    ("transition", "expected_code"),
    [
        ("cancel_accepted", "cancelled"),
        ("cancel_running", "cancelled"),
        ("lost", "lost"),
        ("launch_interrupted", "launch_interrupted"),
        ("deadline_exceeded", "deadline_exceeded"),
        ("worker_failed", "execution_error"),
    ],
)
def test_terminal_error_is_recorded_without_result_read(
    tmp_path: Path, transition: str, expected_code: str
) -> None:
    store = ExecutionStore(tmp_path / "runtime.sqlite3")
    create_execution(store, tmp_path)
    if transition != "cancel_accepted" and transition != "launch_interrupted":
        assert store.claim("a" * 6, worker_pid=123, worker_start_ticks=456)
    if transition == "cancel_accepted":
        store.request_cancel("a" * 6)
    elif transition == "cancel_running":
        store.request_cancel("a" * 6)
        store.finish("a" * 6, exit_code=0)
    elif transition == "lost":
        store.mark_lost("a" * 6, reason="worker_disappeared")
    elif transition == "launch_interrupted":
        store.fail_accepted("a" * 6, reason="launch_interrupted")
    elif transition == "deadline_exceeded":
        store.finish("a" * 6, exit_code=None, deadline_exceeded=True)
    else:
        store.finish("a" * 6, exit_code=1)
    with sqlite3.connect(store.path) as conn:
        row = conn.execute("SELECT error_json FROM error_events").fetchone()
        assert conn.execute("SELECT COUNT(*) FROM error_events").fetchone()[0] == 1
    assert json.loads(row[0])["code"] == expected_code


def test_upstream_worker_error_wins_over_runtime_fallback(tmp_path: Path) -> None:
    store = ExecutionStore(tmp_path / "runtime.sqlite3")
    create_execution(store, tmp_path)
    store.record_error_event(
        "a" * 6, {"category": "monty", "code": "MontyTypingError"}
    )
    store.claim("a" * 6, worker_pid=123, worker_start_ticks=456)
    store.finish("a" * 6, exit_code=1)
    with sqlite3.connect(store.path) as conn:
        events = conn.execute("SELECT error_json FROM error_events").fetchall()
    assert len(events) == 1
    assert json.loads(events[0][0])["code"] == "MontyTypingError"


def test_event_storage_failure_does_not_break_error_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from gpt_dive.code_mode_worker import _emit_error
    from gpt_dive.execution_manager import ExecutionManager

    store = ExecutionStore(tmp_path / "runtime.sqlite3")
    manager = ExecutionManager(tmp_path / "executions", store=store)

    def locked_db() -> sqlite3.Connection:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(store, "_connect", locked_db)
    result = manager._record_result(
        {"kind": "code_mode"},
        {"execution_id": "aaaaaa", "state": "cancelled", "reason": "cancelled"},
    )
    assert result["error"]["code"] == "cancelled"

    _emit_error(
        "MontyTypingError", "typed error", category="monty",
        store=store, execution_id="aaaaaa",
    )
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "MontyTypingError"
    assert "ERROR_EVENT persistence failed" in caplog.text


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
