from __future__ import annotations

import asyncio
from types import SimpleNamespace

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
    description = tools["code_mode"].description
    assert description is not None
    assert "Primary programmable execution root for GPT Dive" in description
    assert "CAPABILITIES provides the live inner capability signatures + descriptions" in description
    assert "Prefer Harness FileSystem/Shell capabilities" in description


def test_code_mode_schema_does_not_assume_path_is_injected() -> None:
    tools = {tool.name: tool for tool in asyncio.run(gpt_dive.mcp.list_tools())}
    tool = tools["code_mode"]
    assert tool.description is not None
    assert "Prefer Harness FileSystem/Shell capabilities" in tool.description
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


async def _call_periodic_bootstrap_middleware(
    tool_name: str, connection_state: dict[str, object]
) -> CallToolResult:
    connection = SimpleNamespace(state=connection_state)
    session = SimpleNamespace(_connection=connection)
    ctx = SimpleNamespace(method="tools/call", params={"name": tool_name}, session=session)

    async def call_next(_ctx):
        return _middleware_tool_result()

    result = await app._periodic_bootstrap_middleware(ctx, call_next)
    assert isinstance(result, CallToolResult)
    return result


def test_periodic_bootstrap_is_appended_to_every_tenth_dive_tool_result(monkeypatch) -> None:
    monkeypatch.setattr(app, "_read_bootstrap_packet", lambda: {"stdout": "BOOTSTRAP-LIVE\n"})
    state: dict[str, object] = {}

    names = ["wsl2_sync", "code_mode", "wsl2_async"] * 3
    for name in names:
        result = asyncio.run(_call_periodic_bootstrap_middleware(name, state))
        assert len(result.content) == 1

    tenth = asyncio.run(_call_periodic_bootstrap_middleware("code_mode", state))
    assert len(tenth.content) == 2
    assert isinstance(tenth.content[-1], TextContent)
    assert "PERIODIC BOOTSTRAP REFRESH: 10 @dive tool calls" in tenth.content[-1].text
    assert "do not guess capability arguments from memory" in tenth.content[-1].text
    assert "BOOTSTRAP-LIVE" in tenth.content[-1].text

    eleventh = asyncio.run(_call_periodic_bootstrap_middleware("wsl2_sync", state))
    assert len(eleventh.content) == 1


def test_periodic_bootstrap_counter_is_connection_scoped(monkeypatch) -> None:
    monkeypatch.setattr(app, "_read_bootstrap_packet", lambda: {"stdout": "BOOTSTRAP-LIVE\n"})
    first: dict[str, object] = {}
    second: dict[str, object] = {}

    for _ in range(9):
        asyncio.run(_call_periodic_bootstrap_middleware("code_mode", first))

    other_session = asyncio.run(_call_periodic_bootstrap_middleware("wsl2_sync", second))
    assert len(other_session.content) == 1

    first_tenth = asyncio.run(_call_periodic_bootstrap_middleware("wsl2_async", first))
    assert len(first_tenth.content) == 2


def test_explicit_bootstrap_resets_periodic_tool_counter(monkeypatch) -> None:
    monkeypatch.setattr(app, "_read_bootstrap_packet", lambda: {"stdout": "BOOTSTRAP-LIVE\n"})
    state: dict[str, object] = {}

    for _ in range(9):
        asyncio.run(_call_periodic_bootstrap_middleware("code_mode", state))

    explicit = asyncio.run(_call_periodic_bootstrap_middleware("bootstrap", state))
    assert len(explicit.content) == 1

    for _ in range(9):
        result = asyncio.run(_call_periodic_bootstrap_middleware("wsl2_sync", state))
        assert len(result.content) == 1

    tenth_after_reset = asyncio.run(_call_periodic_bootstrap_middleware("wsl2_async", state))
    assert len(tenth_after_reset.content) == 2


def test_wsl2_async_capabilities_are_runtime_discoverable() -> None:
    payload = gpt_dive.wsl2_async("capabilities")
    assert set(payload["actions"]) == {"start", "status", "result", "cancel"}


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
        gpt_dive.wsl2_async("start", command="cmd", cwd="/tmp", timeout=11)["job_id"]
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
    with pytest.raises(ValueError, match="requires job_id"):
        gpt_dive.wsl2_async("status")
    with pytest.raises(ValueError, match="capabilities"):
        gpt_dive.wsl2_async("future-action")


def test_core_guard_policy_reroutes_native_python_on_sync_path() -> None:
    result = gpt_dive.wsl2_sync("python --version", timeout=5)
    assert result["returncode"] == 0
    assert "Python 3.14" in result["stdout"]
    assert "auto-reroute" in result["stderr"]


def test_core_guard_policy_reroutes_native_python_on_async_path(tmp_path) -> None:
    import time

    original_root = gpt_dive.jobs.root
    original_systemd = gpt_dive.jobs._systemd_available
    try:
        gpt_dive.jobs.root = tmp_path
        gpt_dive.jobs._systemd_available = False
        started = gpt_dive.wsl2_async("start", command="python --version", timeout=5)
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
