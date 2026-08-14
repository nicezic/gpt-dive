from __future__ import annotations

import asyncio

import pytest

import gpt_dive


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


def test_code_mode_description_names_local_exec_result_keys() -> None:
    tools = {tool.name: tool for tool in asyncio.run(gpt_dive.mcp.list_tools())}
    description = tools["code_mode"].description
    assert description is not None
    assert (
        "local_exec returns a dict with stdout, stderr, and returncode" in description
    )


def test_code_mode_schema_does_not_assume_path_is_injected() -> None:
    tools = {tool.name: tool for tool in asyncio.run(gpt_dive.mcp.list_tools())}
    tool = tools["code_mode"]
    assert tool.description is not None
    assert (
        "workspace-scoped Harness FileSystem and Shell capabilities" in tool.description
    )
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
