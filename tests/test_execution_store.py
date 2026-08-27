from __future__ import annotations

import json
from pathlib import Path

import pytest

from gpt_dive.execution_store import ExecutionStore
from gpt_dive.execution_worker import run_execution


def create_execution(
    store: ExecutionStore,
    root: Path,
    *,
    label: str = "store test",
    publish: bool = False,
) -> dict[str, object]:
    execution_id = "a" * 32
    artifact_dir = root / execution_id
    artifact_dir.mkdir(exist_ok=True)
    return store.create(
        execution_id=execution_id,
        kind="code_mode",
        label=label,
        cwd=str(root),
        backend="popen",
        systemd_unit=None,
        work_timeout_seconds=3590,
        cleanup_timeout_seconds=10,
        request_path=artifact_dir / "request.json",
        artifact_dir=artifact_dir,
        stdout_path=artifact_dir / "stdout.log",
        stderr_path=artifact_dir / "stderr.log",
        outcome_path=artifact_dir / "outcome.json",
        publish=publish,
    )


def test_execution_and_task_share_one_identity_but_not_one_lifecycle(
    tmp_path: Path,
) -> None:
    store = ExecutionStore(tmp_path / "runtime.sqlite3")
    created = create_execution(store, tmp_path)

    assert created["state"] == "accepted"
    with pytest.raises(KeyError):
        store.get_task("a" * 32)

    assert store.claim("a" * 32, worker_pid=123, worker_start_ticks=456)
    assert not store.claim("a" * 32, worker_pid=789, worker_start_ticks=999)

    published = store.publish("a" * 32)
    assert published["execution_id"] == created["execution_id"]
    assert published["state"] == "running"

    completed = store.finish("a" * 32, exit_code=0)
    assert completed["state"] == "completed"
    assert store.get_task("a" * 32)["state"] == "completed"

    dismissed = store.dismiss("a" * 32)
    assert dismissed["dismissed_at"] is not None
    with pytest.raises(KeyError):
        store.get_task("a" * 32)


def test_cancel_before_claim_prevents_worker_authorization(tmp_path: Path) -> None:
    store = ExecutionStore(tmp_path / "runtime.sqlite3")
    create_execution(store, tmp_path)

    cancelled = store.request_cancel("a" * 32)

    assert cancelled["state"] == "cancelled"
    assert cancelled["reason"] == "cancelled"
    assert not store.claim("a" * 32, worker_pid=123, worker_start_ticks=456)


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
    store.request_cancel("a" * 32)

    assert run_execution(store, "a" * 32) == 0
    assert not marker.exists()
    assert not request_path.exists()
    assert store.get("a" * 32)["request_path"] == ""


def test_cancel_request_wins_a_concurrent_finish_transition(tmp_path: Path) -> None:
    store = ExecutionStore(tmp_path / "runtime.sqlite3")
    create_execution(store, tmp_path)
    assert store.claim("a" * 32, worker_pid=123, worker_start_ticks=456)

    store.request_cancel("a" * 32)
    terminal = store.finish("a" * 32, exit_code=0)

    assert terminal["state"] == "cancelled"
    assert terminal["reason"] == "cancelled"


def test_required_label_is_bounded(tmp_path: Path) -> None:
    store = ExecutionStore(tmp_path / "runtime.sqlite3")
    with pytest.raises(ValueError, match="must not be empty"):
        create_execution(store, tmp_path, label="  ")

    with pytest.raises(ValueError, match="80 characters"):
        create_execution(store, tmp_path, label="x" * 81)
