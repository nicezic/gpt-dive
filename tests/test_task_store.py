from __future__ import annotations

from gpt_dive.task_store import TaskStore


def test_task_store_persists_across_reopen(tmp_path) -> None:
    path = tmp_path / "tasks.sqlite3"
    store = TaskStore(path)

    created = store.create(execution_id="exec-1", label="Review ADR")

    assert created["task_id"] != "exec-1"
    assert created["execution_id"] == "exec-1"
    assert created["label"] == "Review ADR"
    assert created["state"] == "working"
    assert created["status_cmd"] is None
    assert created["status"] is None
    assert created["created_at"] == created["updated_at"]

    reopened = TaskStore(path)
    assert reopened.list_tasks() == [created]


def test_task_store_get_update_and_delete(tmp_path) -> None:
    store = TaskStore(tmp_path / "tasks.sqlite3")
    created = store.create(execution_id="exec-2", label="Lifecycle")

    assert store.get(created["task_id"]) == created
    unchanged = store.update_state(created["task_id"], "working")
    assert unchanged["updated_at"] == created["updated_at"]

    completed = store.update_state(created["task_id"], "completed")
    assert completed["state"] == "completed"
    assert completed["updated_at"] >= created["updated_at"]

    store.delete(created["task_id"])
    assert store.list_tasks() == []
