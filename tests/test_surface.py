from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from mcp_types import CallToolResult, TextContent

import gpt_dive
from gpt_dive import app


def test_mcp_surface_is_exactly_four_tools() -> None:
    tools = asyncio.run(gpt_dive.mcp.list_tools())
    assert {tool.name for tool in tools} == {
        "bootstrap",
        "code_mode",
        "task",
        "wsl_exec",
    }


def test_wsl_exec_is_minimal_raw_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tools = {tool.name: tool for tool in asyncio.run(gpt_dive.mcp.list_tools())}
    schema = tools["wsl_exec"].input_schema
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["command"]
    assert set(schema["properties"]) == {"command", "cwd"}

    output_schema = tools["wsl_exec"].output_schema
    assert output_schema is not None
    assert output_schema["additionalProperties"] is True
    assert output_schema["required"] == ["tracked_tasks"]
    tracked = output_schema["$defs"]["TrackedTaskView"]
    assert set(tracked["properties"]) == {
        "execution_id",
        "label",
        "state",
        "reason",
        "elapsed_seconds",
    }

    result = asyncio.run(app.wsl_exec("printf 'RAW_WSL\n'; pwd", cwd=str(tmp_path)))
    assert result["exit_code"] == 0
    assert result["stderr"] == ""
    assert result["stdout"].splitlines() == ["RAW_WSL", str(tmp_path)]
    assert result["truncated"] is False

    monkeypatch.setattr(app, "WSL_EXEC_TIMEOUT_SECONDS", 0.05)
    timed_out = asyncio.run(app.wsl_exec("sleep 30 & echo $!; wait", cwd=str(tmp_path)))
    child = Path("/proc") / timed_out["stdout"].strip()
    deadline = time.monotonic() + 1
    while child.exists() and time.monotonic() < deadline:
        if child.joinpath("stat").read_text().split()[2] == "Z":
            break
        time.sleep(0.01)
    assert timed_out["exit_code"] == 124
    assert not child.exists() or child.joinpath("stat").read_text().split()[2] == "Z"


def test_server_description_exposes_minimal_raw_wsl_escape_hatch() -> None:
    description = gpt_dive.mcp.description
    assert description is not None
    assert "wsl_exec is the minimal raw-shell escape hatch" in description
    assert description.count("wsl_exec") == 1


def test_code_mode_description_exposes_compact_execution_contract() -> None:
    tools = {tool.name: tool for tool in asyncio.run(gpt_dive.mcp.list_tools())}
    tool = tools["code_mode"]
    description = tool.description
    assert description is not None
    assert "always-durable" in description
    assert "bounded inline delivery" in description
    assert "Task handle for the same continuing Execution" in description
    schema = tool.input_schema
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["label", "code"]
    assert schema["properties"]["label"]["maxLength"] == 80
    assert schema["properties"]["label"]["minLength"] == 1
    assert schema["properties"]["mode"]["enum"] == ["auto", "task"]

    assert tool.output_schema is not None
    assert "result" not in tool.output_schema.get("properties", {})
    assert tool.output_schema["discriminator"]["propertyName"] == "kind"
    mapping = tool.output_schema["discriminator"]["mapping"]
    assert set(mapping) == {"completed", "task", "error"}
    expected_fields = {
        "completed": {"kind", "execution_id", "output", "tracked_tasks"},
        "task": {"kind", "execution_id", "state", "tracked_tasks"},
        "error": {"kind", "execution_id", "code", "message", "tracked_tasks"},
    }
    for kind, ref in mapping.items():
        definition = tool.output_schema["$defs"][ref.rsplit("/", 1)[-1]]
        assert definition["additionalProperties"] is False
        assert set(definition["properties"]) == expected_fields[kind]
        assert "tracked_tasks" in definition["required"]
    tracked = tool.output_schema["$defs"]["TrackedTaskView"]
    assert set(tracked["properties"]) == {
        "execution_id",
        "label",
        "state",
        "reason",
        "elapsed_seconds",
    }


def test_task_description_distinguishes_automatic_awareness_from_inspection() -> None:
    tools = {tool.name: tool for tool in asyncio.run(gpt_dive.mcp.list_tools())}
    description = tools["task"].description
    assert description is not None
    assert "list performs explicit detailed inspection" in description
    assert "get is non-destructive" in description
    assert "dismiss removes terminal awareness" in description


def test_task_schema_is_a_strict_lifecycle_union_with_one_id() -> None:
    tools = {tool.name: tool for tool in asyncio.run(gpt_dive.mcp.list_tools())}
    schema = tools["task"].input_schema
    request = schema["properties"]["request"]

    assert schema["additionalProperties"] is False
    assert schema["required"] == ["request"]
    assert request["discriminator"]["propertyName"] == "action"
    assert set(request["discriminator"]["mapping"]) == {
        "list",
        "get",
        "cancel",
        "dismiss",
    }

    tool = tools["task"]
    assert tool.output_schema is not None
    assert "result" not in tool.output_schema.get("properties", {})
    delivery = next(
        item for item in tool.output_schema["anyOf"] if "discriminator" in item
    )
    assert delivery["discriminator"]["propertyName"] == "kind"
    assert set(delivery["discriminator"]["mapping"]) == {
        "completed",
        "task",
        "error",
    }
    task_shape = tool.output_schema["$defs"]["CodeModeTask"]
    assert set(task_shape["properties"]) == {"kind", "execution_id", "state"}
    assert "tracked_tasks" not in task_shape["properties"]
    assert all(
        definition["additionalProperties"] is False
        for definition in schema["$defs"].values()
    )

    task_view = tool.output_schema["$defs"]["TaskView"]
    assert set(task_view["properties"]) == {
        "execution_id",
        "label",
        "state",
        "reason",
        "accepted_at",
        "finished_at",
        "published_at",
        "updated_at",
        "elapsed_seconds",
    }
    task_list = tool.output_schema["$defs"]["TaskListOutput"]
    assert task_list["properties"]["tasks"]["items"]["$ref"].endswith(
        "/TaskView"
    )


def test_task_list_model_visible_inspection_is_detailed(monkeypatch) -> None:
    def detailed_tasks(*, limit=None):
        assert limit == 50
        return [
            {
                "execution_id": "abc123",
                "label": "compile",
                "state": "running",
                "reason": None,
                "accepted_at": "2026-08-31T00:00:00Z",
                "finished_at": None,
                "published_at": "2026-08-31T00:00:01Z",
                "updated_at": "2026-08-31T00:00:02Z",
                "elapsed_seconds": 61,
            }
        ]

    async def call() -> CallToolResult:
        return await app.mcp._tool_manager.call_tool(
            "task",
            {"request": {"action": "list"}},
            cast(Any, None),
            convert_result=True,
        )

    monkeypatch.setattr(app, "_task_list", detailed_tasks)
    result = asyncio.run(call())

    assert result.structured_content == {
        "action": "list",
        "tasks": [
            {
                "execution_id": "abc123",
                "label": "compile",
                "state": "running",
                "reason": None,
                "accepted_at": "2026-08-31T00:00:00Z",
                "finished_at": None,
                "published_at": "2026-08-31T00:00:01Z",
                "updated_at": "2026-08-31T00:00:02Z",
                "elapsed_seconds": 61,
            }
        ],
    }


def test_model_visible_structured_content_has_no_outer_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_code_mode(**_: Any) -> app.CodeModeOutcome:
        return app.CodeModeCompleted(execution_id="abc123", output={"answer": 42})

    async def fake_task(_: app.TaskRequest) -> app.TaskOutcome:
        return app.CodeModeTask(execution_id="abc123", state="running")

    async def call(name: str, arguments: dict[str, Any]) -> CallToolResult:
        return await app.mcp._tool_manager.call_tool(
            name,
            arguments,
            cast(Any, None),
            convert_result=True,
        )

    monkeypatch.setattr(app, "code_mode", fake_code_mode)
    monkeypatch.setattr(app, "_task_list", lambda *, limit=None: [])
    completed = asyncio.run(call("code_mode", {"label": "shape", "code": "1"}))
    assert completed.structured_content == {
        "kind": "completed",
        "execution_id": "abc123",
        "output": {"answer": 42},
        "tracked_tasks": [],
    }

    monkeypatch.setattr(app, "task", fake_task)
    running = asyncio.run(
        call("task", {"request": {"action": "get", "execution_id": "abc123"}})
    )
    assert running.structured_content == {
        "kind": "task",
        "execution_id": "abc123",
        "state": "running",
    }


def test_code_mode_public_output_summarizes_run_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_code_mode(**_: Any) -> app.CodeModeOutcome:
        return app.CodeModeCompleted(
            execution_id="abc123", output={"pytest": "2 passed"}
        )

    async def call() -> CallToolResult:
        return await app.mcp._tool_manager.call_tool(
            "code_mode",
            {"label": "summary", "code": "1"},
            cast(Any, None),
            convert_result=True,
        )

    monkeypatch.setattr(app, "code_mode", fake_code_mode)
    monkeypatch.setattr(app, "_task_list", lambda *, limit=None: [])
    monkeypatch.setattr(
        app.executions.store,
        "list_run_command_evidence",
        lambda execution_id: [
            {
                "execution_id": execution_id,
                "run_ordinal": 1,
                "stdout": b"hidden stdout",
                "stderr": b"",
                "exit_code": 0,
                "duration_ms": 2310,
            },
            {
                "execution_id": execution_id,
                "run_ordinal": 3,
                "stdout": b"more hidden stdout",
                "stderr": b"ruff failed",
                "exit_code": 2,
                "duration_ms": 410,
            },
        ],
    )

    result = asyncio.run(call())

    assert result.structured_content == {
        "kind": "completed",
        "execution_id": "abc123",
        "output": (
            "id: abc123\n\n"
            "[0] 0, 2310 ms, 13 B\n"
            "[2] 2, 410 ms, 29 B, stderr ↓\n"
            "ruff failed\n\n"
            "----\n"
            '{\n  "pytest": "2 passed"\n}'
        ),
        "tracked_tasks": [],
    }
    assert "hidden stdout" not in result.structured_content["output"]


def test_task_get_completed_uses_same_run_command_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_task(_: app.TaskRequest) -> app.TaskOutcome:
        return app.CodeModeCompleted(execution_id="abc123", output="done")

    async def call() -> CallToolResult:
        return await app.mcp._tool_manager.call_tool(
            "task",
            {"request": {"action": "get", "execution_id": "abc123"}},
            cast(Any, None),
            convert_result=True,
        )

    monkeypatch.setattr(app, "task", fake_task)
    monkeypatch.setattr(
        app.executions.store,
        "list_run_command_evidence",
        lambda _execution_id: [
            {
                "run_ordinal": 1,
                "stdout": b"",
                "stderr": b"",
                "exit_code": 0,
                "duration_ms": 95,
            }
        ],
    )

    result = asyncio.run(call())

    assert result.structured_content == {
        "kind": "completed",
        "execution_id": "abc123",
        "output": "id: abc123\n\n[0] 0, 95 ms, 0 B\n\n----\ndone",
    }


def test_code_mode_public_output_is_unchanged_without_run_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_code_mode(**_: Any) -> app.CodeModeOutcome:
        return app.CodeModeCompleted(execution_id="abc123", output=42)

    async def call() -> CallToolResult:
        return await app.mcp._tool_manager.call_tool(
            "code_mode",
            {"label": "plain", "code": "42"},
            cast(Any, None),
            convert_result=True,
        )

    monkeypatch.setattr(app, "code_mode", fake_code_mode)
    monkeypatch.setattr(app, "_task_list", lambda *, limit=None: [])
    monkeypatch.setattr(
        app.executions.store, "list_run_command_evidence", lambda _execution_id: []
    )

    result = asyncio.run(call())

    assert result.structured_content == {
        "kind": "completed",
        "execution_id": "abc123",
        "output": 42,
        "tracked_tasks": [],
    }


def test_sdk_runtime_rejects_unknown_arguments_instead_of_dropping_them() -> None:
    async def call(name: str, arguments: dict[str, Any]) -> None:
        await app.mcp._tool_manager.call_tool(
            name,
            arguments,
            cast(Any, None),
            convert_result=True,
        )

    with pytest.raises(Exception, match="Extra inputs are not permitted"):
        asyncio.run(
            call(
                "code_mode",
                {"label": "strict", "code": "1", "timeout": 999},
            )
        )
    with pytest.raises(Exception, match="Extra inputs are not permitted"):
        asyncio.run(call("task", {"request": {"action": "list", "extra": True}}))


def test_server_instructions_keep_raw_wsl_out_of_structured_guidance() -> None:
    instructions = gpt_dive.mcp.instructions
    assert instructions is not None
    assert "wsl_exec" not in instructions
    assert (
        "Use Web Search only when the missing evidence is external and current"
        in instructions
    )
    assert "Never invent capability names" in instructions
    assert "ordinary work result includes tracked_tasks" in instructions
    assert "compact passive awareness with elapsed_seconds" in instructions
    assert "task(list) is explicit detailed inspection, not polling" in instructions
    assert "task(get) is non-destructive" in instructions
    assert "task(dismiss) removes terminal awareness" in instructions
    assert "Program output semantics stay separate from Task awareness" in instructions


def test_bootstrap_description_is_only_for_structured_harness() -> None:
    tools = {tool.name: tool for tool in asyncio.run(gpt_dive.mcp.list_tools())}
    description = tools["bootstrap"].description
    assert description is not None
    assert description.startswith(
        "Call `bootstrap` before `code_mode` in a fresh ChatGPT Web session"
    )
    assert "wsl_exec" not in description


async def _call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
    return await app.mcp._tool_manager.call_tool(
        name,
        arguments,
        cast(Any, None),
        convert_result=True,
    )


def _projected_task(*, elapsed_seconds: int = 1, state: str = "running") -> dict[str, Any]:
    return {
        "execution_id": "b" * 6,
        "label": "build",
        "state": state,
        "reason": None,
        "accepted_at": "2026-08-31T00:00:00Z",
        "finished_at": "2026-08-31T00:01:30Z" if state == "completed" else None,
        "published_at": "2026-08-31T00:00:01Z",
        "updated_at": "2026-08-31T00:01:30Z",
        "elapsed_seconds": elapsed_seconds,
    }


def test_wsl_exec_model_visible_result_projects_current_tracked_tasks(monkeypatch) -> None:
    async def fake_wsl_exec(command: str, cwd: str | None = None) -> dict[str, Any]:
        assert command == "true"
        assert cwd is None
        return {
            "exit_code": 0,
            "stdout": "OK",
            "stderr": "",
            "duration_ms": 1,
            "truncated": False,
        }

    monkeypatch.setattr(app, "wsl_exec", fake_wsl_exec)
    monkeypatch.setattr(app, "_task_list", lambda *, limit=None: [_projected_task(elapsed_seconds=261)])

    result = asyncio.run(_call_tool("wsl_exec", {"command": "true"}))

    assert result.structured_content == {
        "exit_code": 0,
        "stdout": "OK",
        "stderr": "",
        "duration_ms": 1,
        "truncated": False,
        "tracked_tasks": [
            {
                "execution_id": "b" * 6,
                "label": "build",
                "state": "running",
                "reason": None,
                "elapsed_seconds": 261,
            }
        ],
    }


def test_ordinary_result_always_projects_latest_snapshot(monkeypatch) -> None:
    async def fake_code_mode(**_: Any) -> app.CodeModeOutcome:
        return app.CodeModeCompleted(execution_id="abc123", output=42)

    projected = [_projected_task()]
    monkeypatch.setattr(app, "code_mode", fake_code_mode)
    monkeypatch.setattr(app, "_task_list", lambda *, limit=None: projected)

    def call() -> CallToolResult:
        return asyncio.run(_call_tool("code_mode", {"label": "shape", "code": "1"}))

    first = call()
    unchanged = call()
    projected[0] = _projected_task(elapsed_seconds=90)
    elapsed = call()
    projected[0] = _projected_task(elapsed_seconds=90, state="completed")
    terminal = call()
    projected.clear()
    dismissed = call()

    assert first.structured_content["tracked_tasks"][0]["elapsed_seconds"] == 1
    assert unchanged.structured_content["tracked_tasks"] == first.structured_content["tracked_tasks"]
    assert elapsed.structured_content["tracked_tasks"][0]["elapsed_seconds"] == 90
    assert terminal.structured_content["tracked_tasks"][0]["state"] == "completed"
    assert dismissed.structured_content["tracked_tasks"] == []


def test_projection_failure_does_not_masquerade_as_empty_snapshot(monkeypatch) -> None:
    async def fake_code_mode(**_: Any) -> app.CodeModeOutcome:
        return app.CodeModeCompleted(execution_id="abc123", output=42)

    def fail_tasks(*, limit=None):
        raise RuntimeError("task db unavailable")

    monkeypatch.setattr(app, "code_mode", fake_code_mode)
    monkeypatch.setattr(app, "_task_list", fail_tasks)

    with pytest.raises(Exception, match="task db unavailable"):
        asyncio.run(_call_tool("code_mode", {"label": "shape", "code": "1"}))


def _middleware_tool_result(text: str = "ok") -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=text)])


async def _call_periodic_reminder_middleware(
    tool_name: str, connection_state: dict[str, object]
) -> CallToolResult:
    connection = SimpleNamespace(state=connection_state)
    session = SimpleNamespace(_connection=connection)
    ctx = SimpleNamespace(
        method="tools/call", params={"name": tool_name}, session=session
    )

    async def call_next(_ctx):
        return _middleware_tool_result()

    result = await app._periodic_reminder_middleware(cast(Any, ctx), call_next)
    assert isinstance(result, CallToolResult)
    return result


def test_periodic_reminder_appends_user_rules_section_on_third_tool_call(
    monkeypatch,
) -> None:
    monkeypatch.setattr(app, "_read_periodic_reminder", lambda: "## Reminder\nREMINDER")
    monkeypatch.setattr(
        app,
        "_read_periodic_reminder_config",
        lambda: (3, [("USER_RULES.md", "Reminder")]),
    )
    state: dict[str, object] = {}

    for _ in range(2):
        result = asyncio.run(_call_periodic_reminder_middleware("code_mode", state))
        assert len(result.content) == 1

    third = asyncio.run(_call_periodic_reminder_middleware("code_mode", state))
    assert len(third.content) == 2
    assert isinstance(third.content[-1], TextContent)
    text = third.content[-1].text
    assert "PERIODIC DIVE REMINDER: 3 tool calls" in text
    assert "## Reminder" in text
    assert "BOOTSTRAP PACKET" not in text
    assert "ERROR_CASE" not in text


def test_periodic_reminder_interval_comes_from_config(monkeypatch) -> None:
    monkeypatch.setattr(app, "_read_periodic_reminder", lambda: "## Reminder\nREMINDER")
    monkeypatch.setattr(
        app,
        "_read_periodic_reminder_config",
        lambda: (2, [("USER_RULES.md", "Reminder")]),
    )
    state: dict[str, object] = {}

    first = asyncio.run(_call_periodic_reminder_middleware("code_mode", state))
    assert len(first.content) == 1

    second = asyncio.run(_call_periodic_reminder_middleware("code_mode", state))
    assert len(second.content) == 2
    assert isinstance(second.content[-1], TextContent)
    assert "PERIODIC DIVE REMINDER: 2 tool calls" in second.content[-1].text


def test_periodic_reminder_reads_only_user_rules_reminder(
    monkeypatch, tmp_path
) -> None:
    (tmp_path / "bootstrap").mkdir()
    (tmp_path / "bootstrap" / "reminder.json").write_text(
        '{"interval": 3, "reminder_files": [{"path": "USER_RULES.md", "section": "Reminder"}]}'
    )
    (tmp_path / "USER_RULES.md").write_text(
        "# USER_RULES\n\n## Work\nFULL RULES\n\n## Reminder\nROUTE\nPREVIEW\n"
    )
    (tmp_path / "ERROR_CASE.md").write_text("# ERROR_CASE\nSHOULD NOT APPEAR\n")
    monkeypatch.setattr(app, "_wiki_path", lambda: tmp_path)

    text = app._read_periodic_reminder()
    assert (
        text
        == f"---\n`$ cat {tmp_path / 'USER_RULES.md'}`\n\n## Reminder\nROUTE\nPREVIEW"
    )
    assert "FULL RULES" not in text
    assert "ERROR_CASE" not in text


def test_explicit_bootstrap_resets_periodic_reminder_counter(monkeypatch) -> None:
    monkeypatch.setattr(app, "_read_periodic_reminder", lambda: "REMINDER")
    monkeypatch.setattr(
        app,
        "_read_periodic_reminder_config",
        lambda: (3, [("USER_RULES.md", "Reminder")]),
    )
    state: dict[str, object] = {}

    for _ in range(2):
        asyncio.run(_call_periodic_reminder_middleware("code_mode", state))

    explicit = asyncio.run(_call_periodic_reminder_middleware("bootstrap", state))
    assert len(explicit.content) == 1

    for _ in range(2):
        result = asyncio.run(_call_periodic_reminder_middleware("code_mode", state))
        assert len(result.content) == 1

    third_after_reset = asyncio.run(
        _call_periodic_reminder_middleware("code_mode", state)
    )
    assert len(third_after_reset.content) == 2
