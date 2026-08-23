from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest
from mcp_types import CallToolResult, TextContent

import gpt_dive
from gpt_dive import app


def test_mcp_surface_v1_is_exactly_four_tools() -> None:
    tools = asyncio.run(gpt_dive.mcp.list_tools())
    assert {tool.name for tool in tools} == {
        "bootstrap",
        "code_mode",
        "wsl2_sync",
        "wsl2_async",
    }


def test_server_description_requires_bootstrap_first() -> None:
    description = gpt_dive.mcp.description
    assert description is not None
    assert "Call bootstrap first." in description


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
    assert "Use Pydantic run_command only when shell execution is required" in description
    assert "Every MCP call requires payload as a string" in description
    assert "CAPABILITIES provides the live inner capability signatures + descriptions" in description
    assert "Never invent capability names, arguments, optional fields, or return shapes" in description
    assert "payload" in tool.input_schema["required"]
    assert tool.input_schema["properties"]["payload"]["type"] == "string"
    label_variants = tool.input_schema["properties"]["label"]["anyOf"]
    assert {variant.get("type") for variant in label_variants} >= {"string", "null"}
    assert any(variant.get("maxLength") == 80 for variant in label_variants)
    action_variants = tool.input_schema["properties"]["action"]["anyOf"]
    assert {tuple(v.get("enum", [])) for v in action_variants} >= {("status", "result", "cancel")}
    assert "input" not in tool.input_schema["properties"]


def test_server_instructions_require_web_first_error_response_and_code_mode_default() -> None:
    instructions = gpt_dive.mcp.instructions
    assert instructions is not None
    assert "use code_mode as the default programmable root" in instructions
    assert "Use Web Search only when the missing evidence is external and current" in instructions
    assert "Never invent capability names" in instructions
    assert "Use wsl2_sync only for transport/smoke" in instructions


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


async def _call_periodic_reminder_middleware(
    tool_name: str, connection_state: dict[str, object]
) -> CallToolResult:
    connection = SimpleNamespace(state=connection_state)
    session = SimpleNamespace(_connection=connection)
    ctx = SimpleNamespace(method="tools/call", params={"name": tool_name}, session=session)

    async def call_next(_ctx):
        return _middleware_tool_result()

    result = await app._periodic_reminder_middleware(cast(Any, ctx), call_next)
    assert isinstance(result, CallToolResult)
    return result


def test_periodic_reminder_appends_user_rules_section_on_third_tool_call(monkeypatch) -> None:
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

    third = asyncio.run(_call_periodic_reminder_middleware("wsl2_sync", state))
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


def test_periodic_reminder_reads_only_user_rules_reminder(monkeypatch, tmp_path) -> None:
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
    assert text == f"---\n`$ cat {tmp_path / 'USER_RULES.md'}`\n\n## Reminder\nROUTE\nPREVIEW"
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
        result = asyncio.run(_call_periodic_reminder_middleware("wsl2_sync", state))
        assert len(result.content) == 1

    third_after_reset = asyncio.run(_call_periodic_reminder_middleware("wsl2_async", state))
    assert len(third_after_reset.content) == 2


def test_wsl2_async_capabilities_are_runtime_discoverable() -> None:
    payload = gpt_dive.wsl2_async("capabilities")
    assert set(payload["actions"]) == {"start", "status", "result", "cancel"}
    assert payload["actions"]["start"] == {
        "requires": ["command", "permission"],
        "optional": ["cwd", "timeout"],
    }


def test_wsl2_async_routes_lifecycle(monkeypatch) -> None:
    calls: list[tuple] = []

    monkeypatch.setattr(
        gpt_dive.jobs,
        "start",
        lambda command, cwd, timeout: (
            calls.append(("start", command, cwd, timeout)) or {"job_id": "j1"}
        ),
    )
    monkeypatch.setattr(
        gpt_dive.jobs,
        "status",
        lambda job_id: (
            calls.append(("status", job_id)) or {"job_id": job_id, "status": "running"}
        ),
    )
    monkeypatch.setattr(
        gpt_dive.jobs,
        "result",
        lambda job_id: (
            calls.append(("result", job_id)) or {"job_id": job_id, "ready": True}
        ),
    )
    monkeypatch.setattr(
        gpt_dive.jobs,
        "cancel",
        lambda job_id: (
            calls.append(("cancel", job_id))
            or {"job_id": job_id, "status": "cancelled"}
        ),
    )

    assert (
        gpt_dive.wsl2_async(
            "start",
            command="cmd",
            cwd="/tmp",
            timeout=11,
            permission=app._DIRECT_WSL_PERMISSION,
        )["job_id"]
        == "j1"
    )
    assert gpt_dive.wsl2_async("status", job_id="j1")["status"] == "running"
    assert gpt_dive.wsl2_async("result", job_id="j1")["ready"] is True
    assert gpt_dive.wsl2_async("cancel", job_id="j1")["status"] == "cancelled"
    assert calls == [
        ("start", "cmd", "/tmp", 11),
        ("status", "j1"),
        ("result", "j1"),
        ("cancel", "j1"),
    ]


def test_wsl2_async_validates_action_specific_fields() -> None:
    with pytest.raises(ValueError, match="requires command"):
        gpt_dive.wsl2_async("start")
    with pytest.raises(ValueError, match="permission mismatch"):
        gpt_dive.wsl2_async("start", command="cmd")
    with pytest.raises(ValueError, match="permission mismatch"):
        gpt_dive.wsl2_async("start", command="cmd", permission="wrong")
    with pytest.raises(ValueError, match="requires job_id"):
        gpt_dive.wsl2_async("status")
    with pytest.raises(ValueError, match="capabilities"):
        gpt_dive.wsl2_async("future-action")


def test_wsl2_sync_requires_exact_permission() -> None:
    with pytest.raises(ValueError, match="permission mismatch"):
        gpt_dive.wsl2_sync("true", permission="wrong")


def test_wsl2_sync_permission_is_required_in_live_schema() -> None:
    tools = {tool.name: tool for tool in asyncio.run(gpt_dive.mcp.list_tools())}
    schema = tools["wsl2_sync"].input_schema
    assert "permission" in schema["required"]
    assert app._DIRECT_WSL_PERMISSION in schema["properties"]["permission"]["description"]


def test_wsl2_async_permission_is_exposed_in_live_schema() -> None:
    tools = {tool.name: tool for tool in asyncio.run(gpt_dive.mcp.list_tools())}
    schema = tools["wsl2_async"].input_schema
    assert "permission" in schema["properties"]
    assert "permission" not in schema.get("required", [])
    assert app._DIRECT_WSL_PERMISSION in schema["properties"]["permission"]["description"]


def test_wsl2_sync_allows_intentional_root_inspection() -> None:
    result = gpt_dive.wsl2_sync(
        "find / -maxdepth 0 -print",
        permission=app._DIRECT_WSL_PERMISSION,
        timeout=5,
    )
    assert result["returncode"] == 0
    assert result["stdout"].strip() == "/"


def test_core_guard_policy_reroutes_native_python_on_sync_path() -> None:
    result = gpt_dive.wsl2_sync(
        "python --version", permission=app._DIRECT_WSL_PERMISSION, timeout=5
    )
    assert result["returncode"] == 0
    assert "Python 3.14" in result["stdout"]
    assert "auto-reroute" in result["stderr"]


def test_core_guard_policy_blocks_direct_pytest_on_sync_path() -> None:
    result = gpt_dive.wsl2_sync(
        "pytest --version", permission=app._DIRECT_WSL_PERMISSION, timeout=5
    )
    assert result["returncode"] == 2
    assert "Direct 'pytest' execution is prohibited" in result["stderr"]


def test_core_guard_policy_reroutes_native_python_on_async_path(tmp_path) -> None:
    import time

    original_root = gpt_dive.jobs.root
    original_systemd = gpt_dive.jobs._systemd_available
    try:
        gpt_dive.jobs.root = tmp_path
        gpt_dive.jobs._systemd_available = False
        started = gpt_dive.wsl2_async(
            "start",
            command="python --version",
            timeout=5,
            permission=app._DIRECT_WSL_PERMISSION,
        )
        deadline = time.monotonic() + 3
        state = started
        while time.monotonic() < deadline:
            state = gpt_dive.wsl2_async("status", job_id=started["job_id"])
            if state["status"] != "running":
                break
            time.sleep(0.03)
        result = gpt_dive.wsl2_async("result", job_id=started["job_id"])
        assert result["ready"] is True
        assert result["exit_code"] == 0
        assert "Python 3.14" in result["stdout"]
        assert "auto-reroute" in result["stderr"]
    finally:
        gpt_dive.jobs.root = original_root
        gpt_dive.jobs._systemd_available = original_systemd


def test_core_guard_policy_blocks_direct_pytest_on_async_path(tmp_path) -> None:
    import time

    original_root = gpt_dive.jobs.root
    original_systemd = gpt_dive.jobs._systemd_available
    try:
        gpt_dive.jobs.root = tmp_path
        gpt_dive.jobs._systemd_available = False
        started = gpt_dive.wsl2_async(
            "start",
            command="pytest --version",
            timeout=5,
            permission=app._DIRECT_WSL_PERMISSION,
        )
        deadline = time.monotonic() + 3
        state = started
        while time.monotonic() < deadline:
            state = gpt_dive.wsl2_async("status", job_id=started["job_id"])
            if state["status"] != "running":
                break
            time.sleep(0.03)
        result = gpt_dive.wsl2_async("result", job_id=started["job_id"])
        assert result["ready"] is True
        assert result["exit_code"] == 2
        assert "Direct 'pytest' execution is prohibited" in result["stderr"]
    finally:
        gpt_dive.jobs.root = original_root
        gpt_dive.jobs._systemd_available = original_systemd
