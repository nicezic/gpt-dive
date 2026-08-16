from __future__ import annotations

import asyncio
import time
from pathlib import Path

from gpt_dive.conduit.runtime import ConduitRuntime
from gpt_dive.job_manager import JobManager


class RecordingPublisher:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def publish(self, event: dict[str, object]) -> str:
        self.events.append(event)
        return f"1-{len(self.events)}"


def _runtime(tmp_path: Path) -> tuple[ConduitRuntime, RecordingPublisher]:
    jobs = JobManager(tmp_path / "jobs")
    jobs._systemd_available = False
    publisher = RecordingPublisher()
    return ConduitRuntime(jobs=jobs, publisher=publisher), publisher


def test_conduit_mcp_surface_is_one_tool() -> None:
    from gpt_dive.conduit.server import mcp

    tools = asyncio.run(mcp.list_tools())
    assert [tool.name for tool in tools] == ["c"]


def test_start_returns_compact_snapshot_and_collect_is_non_destructive(tmp_path: Path) -> None:
    runtime, publisher = _runtime(tmp_path)

    started = runtime.call(
        action="start",
        label="ten-second-canary",
        command="sleep 0.12; printf DONE",
        timeout=3,
    )
    task_id = started["result"]["task_id"]
    assert started["result"]["status"] == "running"
    assert started["tasks"] == [
        {
            "id": task_id,
            "label": "ten-second-canary",
            "status": "running",
            "age_sec": started["tasks"][0]["age_sec"],
        }
    ]
    assert set(started["tasks"][0]) == {"id", "label", "status", "age_sec"}

    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        snapshot = runtime.call(action="sync", text="peek")
        if snapshot["tasks"][0]["status"] == "done":
            break
        time.sleep(0.03)
    else:
        raise AssertionError("canary job did not complete")

    first = runtime.call(action="collect", task_id=task_id)
    second = runtime.call(action="collect", task_id=task_id)
    assert first["result"]["ready"] is True
    assert first["result"]["stdout"] == "DONE"
    assert second["result"]["stdout"] == "DONE"
    assert second["tasks"][0]["status"] == "done"
    assert "stdout" not in second["tasks"][0]
    actions = [event["action"] for event in publisher.events]
    assert actions[0] == "start"
    assert "sync" in actions[1:-2]
    assert actions[-2:] == ["collect", "collect"]


def test_every_action_returns_task_snapshot(tmp_path: Path) -> None:
    runtime, _ = _runtime(tmp_path)
    assert runtime.call(action="sync", text="hello") == {
        "result": {"text": "hello"},
        "tasks": [],
    }
    assert runtime.call(action="emit", text="answer") == {
        "result": {"emitted": True},
        "tasks": [],
    }


def test_action_validation_is_explicit(tmp_path: Path) -> None:
    runtime, _ = _runtime(tmp_path)

    for action, message in [
        ("start", "requires command"),
        ("collect", "requires task_id"),
        ("sync", "requires text"),
        ("emit", "requires text"),
    ]:
        try:
            runtime.call(action=action)
        except ValueError as exc:
            assert message in str(exc)
        else:
            raise AssertionError(f"{action} should have failed")

    try:
        runtime.call(action="start", command="true", label="x" * 81)
    except ValueError as exc:
        assert "80 characters or fewer" in str(exc)
    else:
        raise AssertionError("oversized label should have failed")

    try:
        runtime.call(action="future")
    except ValueError as exc:
        assert "start, sync, collect, emit" in str(exc)
    else:
        raise AssertionError("unknown action should have failed")
