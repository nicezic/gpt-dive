from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

from mcp_types import CallToolResult, TextContent

import gpt_dive
from gpt_dive import app


def test_mcp_surface_is_exactly_two_tools() -> None:
    tools = asyncio.run(gpt_dive.mcp.list_tools())
    assert {tool.name for tool in tools} == {
        "bootstrap",
        "code_mode",
    }


def test_server_description_requires_bootstrap_first() -> None:
    description = gpt_dive.mcp.description
    assert description is not None
    assert "Call bootstrap first." in description
    assert "run_command" not in description
    assert "wsl2_sync" not in description
    assert "wsl2_async" not in description


def test_server_instructions_do_not_own_progress_presentation() -> None:
    instructions = gpt_dive.mcp.instructions
    assert instructions is not None
    assert "exactly two concise user-visible lines" not in instructions
    assert "Line 1" not in instructions
    assert "Line 2" not in instructions


def test_code_mode_description_exposes_compact_execution_contract() -> None:
    tools = {tool.name: tool for tool in asyncio.run(gpt_dive.mcp.list_tools())}
    tool = tools["code_mode"]
    description = tool.description
    assert description is not None
    assert "Primary programmable execution root for GPT Dive" in description
    assert "Write code as Monty/Python orchestration" in description
    assert "Prefer registered capabilities directly" in description
    assert "Decide dependencies first" in description
    assert "run_command" not in description
    assert "wsl2_sync" not in description
    assert "wsl2_async" not in description
    assert "Every MCP call requires payload as a string" in description
    assert (
        "CAPABILITIES provides the live inner capability signatures + descriptions"
        in description
    )
    assert (
        "Never invent capability names, arguments, optional fields, or return shapes"
        in description
    )
    assert "payload" in tool.input_schema["required"]
    assert tool.input_schema["properties"]["payload"]["type"] == "string"
    assert "timeout" not in tool.input_schema["properties"]
    task_schema = tool.input_schema["properties"]["task"]
    task_variants = {
        variant.get("$ref") or variant.get("type") for variant in task_schema["anyOf"]
    }
    assert "#/$defs/TaskLaunch" in task_variants and "null" in task_variants
    launch = tool.input_schema["$defs"]["TaskLaunch"]["properties"]
    assert launch["label"]["maxLength"] == 80
    assert launch["label"]["minLength"] == 1
    assert "status_cmd" not in launch
    assert "status" in launch
    assert "background" not in tool.input_schema["properties"]
    assert "execution_id" in tool.input_schema["properties"]
    assert "job_id" not in tool.input_schema["properties"]
    action_variants = tool.input_schema["properties"]["action"]["anyOf"]
    assert {tuple(v.get("enum", [])) for v in action_variants} >= {
        ("status", "result", "cancel")
    }
    assert "input" not in tool.input_schema["properties"]


def test_server_instructions_require_web_first_error_response_and_code_mode_default() -> (
    None
):
    instructions = gpt_dive.mcp.instructions
    assert instructions is not None
    assert "use code_mode as the default programmable root" in instructions
    assert (
        "Use Web Search only when the missing evidence is external and current"
        in instructions
    )
    assert "Never invent capability names" in instructions
    assert "wsl2_sync" not in instructions
    assert "wsl2_async" not in instructions
    assert "run_command" not in instructions


def test_code_mode_schema_does_not_assume_path_is_injected() -> None:
    tools = {tool.name: tool for tool in asyncio.run(gpt_dive.mcp.list_tools())}
    tool = tools["code_mode"]
    assert tool.description is not None
    assert "Prefer registered capabilities directly" in tool.description
    properties = tool.input_schema["properties"]
    assert "Path(CWD)" not in properties["code"]["description"]
    assert "Path(CWD)" not in properties["cwd"]["description"]


def test_bootstrap_description_starts_with_fresh_session_rule() -> None:
    tools = {tool.name: tool for tool in asyncio.run(gpt_dive.mcp.list_tools())}
    description = tools["bootstrap"].description
    assert description is not None
    assert description.startswith(
        "Always call `bootstrap` first in a fresh ChatGPT Web session"
    )


def _middleware_tool_result(text: str = "ok") -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=text)])


async def _call_tracked_tasks_middleware(
    tool_name: str, result: CallToolResult
) -> CallToolResult:
    connection = SimpleNamespace(state={})
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
                "label": "AGY worker",
                "state": "working",
                "elapsed_seconds": 261,
                "status_label": "TODOS 3/9",
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
    assert "working" in awareness.text
    assert "4:21" in awareness.text
    assert "TODOS 3/9" in awareness.text


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
    awareness = result.content[-1]
    assert isinstance(primary_content, TextContent)
    assert isinstance(awareness, TextContent)
    assert primary_content.text == "PRIMARY"
    assert "TrackedTasks unavailable" in awareness.text


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
