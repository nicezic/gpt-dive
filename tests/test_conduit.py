from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import pytest

from gpt_dive.conduit.runtime import ConduitRuntime
from gpt_dive.conduit.server import mcp as conduit_mcp
from gpt_dive.execution_manager import ExecutionManager


class FakePublisher:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def publish(self, event: dict[str, object]) -> str:
        self.events.append(event)
        return f"event-{len(self.events)}"


def runtime_for_test(tmp_path: Path) -> tuple[ConduitRuntime, FakePublisher]:
    executions = ExecutionManager(
        tmp_path / "executions",
        work_timeout_seconds=5,
        cleanup_timeout_seconds=2,
    )
    executions._systemd_available = False
    publisher = FakePublisher()
    return ConduitRuntime(executions=executions, publisher=publisher), publisher


def wait_ready(
    runtime: ConduitRuntime, execution_id: str, *, timeout: float = 5.0
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = runtime.call(action="get", execution_id=execution_id)
        if result["result"]["ready"]:
            return result
        time.sleep(0.03)
    raise AssertionError("Conduit Execution did not finish")


def test_start_get_and_dismiss_share_one_execution_id(tmp_path: Path) -> None:
    runtime, publisher = runtime_for_test(tmp_path)

    started = runtime.call(
        action="start",
        label="conduit canary",
        command="printf CONDUIT_OK",
        cwd=str(tmp_path),
    )
    execution_id = str(started["result"]["execution_id"])

    assert started["tasks"][0]["id"] == execution_id
    first = wait_ready(runtime, execution_id)
    second = runtime.call(action="get", execution_id=execution_id)
    assert first["result"]["output"]["stdout"] == "CONDUIT_OK"
    assert second["result"]["output"]["stdout"] == "CONDUIT_OK"

    dismissed = runtime.call(action="dismiss", execution_id=execution_id)
    assert dismissed["result"]["dismissed"] is True
    assert dismissed["tasks"] == []
    assert runtime.executions.result(execution_id)["stdout"] == "CONDUIT_OK"
    assert publisher.events[-1]["v"] == 2


def test_cancel_is_explicit_and_runtime_owned(tmp_path: Path) -> None:
    runtime, _ = runtime_for_test(tmp_path)
    started = runtime.call(
        action="start",
        label="cancel canary",
        command="sleep 30",
    )
    execution_id = str(started["result"]["execution_id"])

    cancelled = runtime.call(action="cancel", execution_id=execution_id)

    assert cancelled["result"]["cancel_requested"] is True
    assert cancelled["result"]["status"] == "cancelled"


def test_snapshot_includes_tasks_started_outside_conduit(tmp_path: Path) -> None:
    runtime, _ = runtime_for_test(tmp_path)
    external = runtime.executions.start(
        "sleep 30",
        label="shared runtime",
        kind="code_mode",
        publish=True,
    )

    snapshot = runtime.snapshot()

    assert snapshot[0]["id"] == external["execution_id"]
    runtime.executions.cancel(str(external["execution_id"]))


def test_conduit_schema_is_a_strict_action_union() -> None:
    tool = asyncio.run(conduit_mcp.list_tools())[0]
    schema = tool.input_schema

    assert schema["additionalProperties"] is False
    assert schema["required"] == ["request"]
    assert schema["properties"]["request"]["discriminator"]["propertyName"] == (
        "action"
    )
    assert "timeout" not in str(schema)
    assert "task_id" not in str(schema)


@pytest.mark.parametrize("action", ["get", "cancel", "dismiss"])
def test_lifecycle_actions_require_execution_id(tmp_path: Path, action: str) -> None:
    runtime, _ = runtime_for_test(tmp_path)

    with pytest.raises(ValueError, match="requires execution_id"):
        runtime.call(action=action)
