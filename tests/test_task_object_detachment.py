from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

import gpt_dive
from gpt_dive import app as app_module
from gpt_dive.task_store import TaskStore


def _isolate_runtime(tmp_path: Path):
    """Root executions and the Task registry at tmp_path with popen backend."""
    original_root = gpt_dive.executions.root
    original_systemd = gpt_dive.executions._systemd_available
    original_task_store = app_module.task_store
    gpt_dive.executions.root = tmp_path / "executions"
    gpt_dive.executions.root.mkdir()
    gpt_dive.executions._systemd_available = False
    task_db = TaskStore(tmp_path / "tasks.sqlite3")
    app_module.task_store = task_db

    def restore() -> None:
        gpt_dive.executions.root = original_root
        gpt_dive.executions._systemd_available = original_systemd
        app_module.task_store = original_task_store

    return restore, task_db


def _wait_terminal(execution_id: str, timeout: float = 4.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = asyncio.run(
            gpt_dive.code_mode(action="status", execution_id=execution_id)
        )
        if state["status"] != "running":
            return str(state["status"])
        time.sleep(0.03)
    raise AssertionError("detached execution did not finish")


def test_code_mode_without_task_runs_synchronously(tmp_path: Path) -> None:
    restore, task_db = _isolate_runtime(tmp_path)
    try:
        result = asyncio.run(gpt_dive.code_mode("21 * 2", payload=""))
        assert result["result"] == 42
        assert task_db.list_tasks() == []
    finally:
        restore()


def test_code_mode_task_launch_creates_tracked_task_and_full_cycle(
    tmp_path: Path,
) -> None:
    restore, task_db = _isolate_runtime(tmp_path)
    try:
        started = asyncio.run(
            gpt_dive.code_mode(
                'await run_command("sleep 0.15")\n{"origin": "detached"}',
                payload="",
                task={"label": "Download ubuntu.iso"},  # pyright: ignore[reportArgumentType]
            )
        )
        assert set(started) == {"task_id", "execution_id", "label", "state"}
        assert started["label"] == "Download ubuntu.iso"
        assert started["state"] == "working"
        assert started["task_id"] != started["execution_id"]
        assert "result" not in started

        records = task_db.list_tasks()
        assert [str(record["task_id"]) for record in records] == [
            str(started["task_id"])
        ]

        assert _wait_terminal(str(started["execution_id"])) == "completed"

        listed = asyncio.run(gpt_dive.code_mode("await task_list()", payload=""))[
            "result"
        ]["tasks"]
        assert {str(task["task_id"]) for task in listed} == {str(started["task_id"])}

        first = app_module._task_collect(str(started["task_id"]))
        second = app_module._task_collect(str(started["task_id"]))
        assert first["task"]["state"] == "completed"
        assert second["task"]["state"] == "completed"

        app_module._task_ack(str(started["task_id"]))
        assert task_db.list_tasks() == []
    finally:
        restore()


def test_code_mode_rejects_task_on_lifecycle_action(tmp_path: Path) -> None:
    restore, _task_db = _isolate_runtime(tmp_path)
    try:
        with pytest.raises(ValueError, match="only valid when launching"):
            asyncio.run(
                gpt_dive.code_mode(
                    action="status",
                    execution_id="abc",
                    payload="",
                    task={"label": "nope"},  # pyright: ignore[reportArgumentType]
                )
            )
    finally:
        restore()


def test_wsl2_async_start_requires_task(tmp_path: Path) -> None:
    restore, _task_db = _isolate_runtime(tmp_path)
    try:
        with pytest.raises(ValueError, match="requires a labeled task"):
            gpt_dive.wsl2_async(
                action="start",
                command="printf DONE",
                permission="for-special-such-as-exceptional-wsl-win11-maintenance; no-stupid-blind-broad-recursive-search",
            )
    finally:
        restore()


def test_wsl2_async_start_creates_tracked_task(tmp_path: Path) -> None:
    restore, task_db = _isolate_runtime(tmp_path)
    try:
        started = gpt_dive.wsl2_async(
            action="start",
            command="printf DONE",
            permission="for-special-such-as-exceptional-wsl-win11-maintenance; no-stupid-blind-broad-recursive-search",
            timeout=5,
            task={
                "label": "Fetch artifact",
                "status_cmd": "printf 'BYTES 0'",
            },
        )
        assert set(started) == {"task_id", "execution_id", "label", "state"}
        assert started["label"] == "Fetch artifact"
        assert started["state"] == "working"

        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            state = gpt_dive.wsl2_async(
                "status", execution_id=str(started["execution_id"])
            )
            if state["status"] != "running":
                break
            time.sleep(0.03)
        else:
            raise AssertionError("wsl2_async execution did not finish")
        assert state["status"] == "completed"

        collected = app_module._task_collect(str(started["task_id"]))
        assert collected["task"]["state"] == "completed"
        assert collected["result"]["stdout"] == "DONE"

        app_module._task_ack(str(started["task_id"]))
        assert task_db.list_tasks() == []
    finally:
        restore()


def test_wsl2_async_non_start_actions_reject_task(tmp_path: Path) -> None:
    restore, _task_db = _isolate_runtime(tmp_path)
    try:
        with pytest.raises(ValueError, match="only valid with action='start'"):
            gpt_dive.wsl2_async(
                "status",
                execution_id="abc",
                task={"label": "nope"},  # pyright: ignore[reportArgumentType]
            )
    finally:
        restore()


def test_legacy_background_flag_is_gone_from_schema_and_signature(
    tmp_path: Path,
) -> None:
    restore, _task_db = _isolate_runtime(tmp_path)
    try:
        tools = {tool.name: tool for tool in asyncio.run(gpt_dive.mcp.list_tools())}
        code_properties = tools["code_mode"].input_schema["properties"]
        assert "background" not in code_properties
        assert "label" not in code_properties
        assert "status_cmd" not in code_properties
        assert "status" not in code_properties
        assert "task" in code_properties

        async_properties = tools["wsl2_async"].input_schema["properties"]
        assert "task" in async_properties

        with pytest.raises(TypeError):
            asyncio.run(
                gpt_dive.code_mode("1 + 1", payload="", background=True)  # type: ignore[arg-type]
            )
    finally:
        restore()
