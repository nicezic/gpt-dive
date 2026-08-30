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
    output_union = tool.output_schema["properties"]["result"]
    assert output_union["discriminator"]["propertyName"] == "kind"
    assert set(output_union["discriminator"]["mapping"]) == {
        "completed",
        "task",
        "error",
    }


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
    output_union = tool.output_schema["properties"]["result"]["anyOf"]
    delivery = next(item for item in output_union if "discriminator" in item)
    assert delivery["discriminator"]["propertyName"] == "kind"
    assert set(delivery["discriminator"]["mapping"]) == {
        "completed",
        "task",
        "error",
    }
    task_shape = tool.output_schema["$defs"]["CodeModeTask"]
    assert set(task_shape["properties"]) == {"kind", "execution_id", "state"}
    assert all(
        definition["additionalProperties"] is False
        for definition in schema["$defs"].values()
    )


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
    assert "task tool for list/get/cancel/dismiss" in instructions


def test_bootstrap_description_is_only_for_structured_harness() -> None:
    tools = {tool.name: tool for tool in asyncio.run(gpt_dive.mcp.list_tools())}
    description = tools["bootstrap"].description
    assert description is not None
    assert description.startswith(
        "Call `bootstrap` before `code_mode` in a fresh ChatGPT Web session"
    )
    assert "wsl_exec" not in description


def _middleware_tool_result(text: str = "ok") -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=text)])


async def _call_tracked_tasks_middleware(
    tool_name: str,
    result: CallToolResult,
    connection_state: dict[str, object] | None = None,
) -> CallToolResult:
    connection = SimpleNamespace(
        state=connection_state if connection_state is not None else {}
    )
    session = SimpleNamespace(_connection=connection)
    ctx = SimpleNamespace(
        method="tools/call", params={"name": tool_name}, session=session
    )

    async def call_next(_ctx):
        return result

    output = await app._tracked_tasks_middleware(cast(Any, ctx), call_next)
    assert isinstance(output, CallToolResult)
    return output


def test_tracked_tasks_middleware_preserves_primary_result(monkeypatch) -> None:
    def awareness_tasks(*, limit=None):
        assert limit == 8
        return [
            {
                "execution_id": "a" * 6,
                "label": "AGY worker",
                "state": "running",
                "reason": None,
                "finished_at": None,
                "elapsed_seconds": 261,
            }
        ]

    monkeypatch.setattr(app, "_task_list", awareness_tasks)
    primary = CallToolResult(
        content=[TextContent(type="text", text="PRIMARY")],
        structured_content={"answer": 3},
    )

    result = asyncio.run(_call_tracked_tasks_middleware("code_mode", primary))

    assert result.structured_content == {"answer": 3}
    primary_content = result.content[0]
    awareness = result.content[-1]
    assert isinstance(primary_content, TextContent)
    assert isinstance(awareness, TextContent)
    assert primary_content.text == "PRIMARY"
    assert "TrackedTasks" in awareness.text
    assert "AGY worker" in awareness.text
    assert "running" in awareness.text
    assert "4:21" in awareness.text
    assert "a" * 6 in awareness.text


def test_tracked_tasks_middleware_failure_preserves_primary_result(monkeypatch) -> None:
    def fail_awareness(*, limit=None):
        assert limit == 8
        raise RuntimeError("task db unavailable")

    monkeypatch.setattr(app, "_task_list", fail_awareness)
    primary = CallToolResult(
        content=[TextContent(type="text", text="PRIMARY")],
        structured_content={"answer": 3},
    )

    result = asyncio.run(_call_tracked_tasks_middleware("code_mode", primary))

    assert result.structured_content == {"answer": 3}
    primary_content = result.content[0]
    assert isinstance(primary_content, TextContent)
    assert primary_content.text == "PRIMARY"
    assert len(result.content) == 1


def test_tracked_tasks_emits_only_when_visible_state_changes(monkeypatch) -> None:
    projected = {
        "execution_id": "b" * 6,
        "label": "build",
        "state": "running",
        "reason": None,
        "finished_at": None,
        "elapsed_seconds": 1,
    }
    monkeypatch.setattr(app, "_task_list", lambda *, limit=None: [projected])
    state: dict[str, object] = {}

    first = asyncio.run(
        _call_tracked_tasks_middleware("code_mode", _middleware_tool_result(), state)
    )
    projected["elapsed_seconds"] = 90
    unchanged = asyncio.run(
        _call_tracked_tasks_middleware("code_mode", _middleware_tool_result(), state)
    )
    projected.update(state="completed", finished_at="2026-08-27T00:00:00Z")
    changed = asyncio.run(
        _call_tracked_tasks_middleware("code_mode", _middleware_tool_result(), state)
    )

    assert len(first.content) == 2
    assert len(unchanged.content) == 1
    assert len(changed.content) == 2


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
