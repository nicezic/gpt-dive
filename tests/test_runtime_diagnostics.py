from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace

import pytest
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import CallToolRequestParams, CallToolResult

import gpt_dive.runtime_diagnostics as runtime_diagnostics
from gpt_dive.runtime_diagnostics import request_lifecycle_middleware, run_mcp_server


def test_request_lifecycle_middleware_is_registered() -> None:
    from gpt_dive.app import mcp

    assert request_lifecycle_middleware in mcp.middleware
    assert runtime_diagnostics.normalize_tool_error_middleware in mcp.middleware


def test_tool_error_normalizer_rewrites_sdk_generic_unexpected_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    server = MCPServer(name="normalizer-test")

    @server.tool(name="boom")
    async def boom() -> str:
        raise RuntimeError("server-only secret")

    ctx = SimpleNamespace(
        method="tools/call", request_id="req-9", params={"name": "boom"}
    )
    params = CallToolRequestParams(name="boom", arguments={})

    async def call_next(_ctx: object) -> CallToolResult:
        return await server._handle_call_tool(_ctx, params)  # type: ignore[arg-type]

    with caplog.at_level(logging.INFO, logger="gpt_dive.runtime"):
        result = asyncio.run(
            runtime_diagnostics.normalize_tool_error_middleware(ctx, call_next)
        )

    assert result.is_error is True
    payload = json.loads(result.content[0].text)
    assert payload == {
        "status": "failed",
        "error": {
            "boundary": "mcp_server",
            "code": "MCP.SERVER.UNHANDLED",
            "message": "The MCP server observed an unexpected tool failure.",
        },
        "request_id": "req-9",
        "tool": "boom",
        "recovery": "inspect_boundary",
        "guidance": (
            "Match request_id and tool in GPT Dive server diagnostics; the cause is "
            "not known from this payload. Check whether the original execution "
            "ran before retrying any side-effectful request."
        ),
    }
    assert "server-only secret" not in result.content[0].text
    assert "code=MCP.SERVER.UNHANDLED" in caplog.text
    assert "request=req-9" in caplog.text
    assert "tool=boom" in caplog.text


def test_tool_error_normalizer_preserves_sdk_anticipated_error_detail() -> None:
    server = MCPServer(name="normalizer-test")

    @server.tool(name="expected")
    async def expected() -> str:
        raise ToolError("label is required")

    ctx = SimpleNamespace(
        method="tools/call", request_id="req-10", params={"name": "expected"}
    )
    params = CallToolRequestParams(name="expected", arguments={})

    async def call_next(_ctx: object) -> CallToolResult:
        return await server._handle_call_tool(_ctx, params)  # type: ignore[arg-type]

    result = asyncio.run(
        runtime_diagnostics.normalize_tool_error_middleware(ctx, call_next)
    )

    assert result.is_error is True
    assert result.content[0].text == "Error executing tool expected: label is required"


def test_request_lifecycle_logs_nested_exception_group(
    caplog: pytest.LogCaptureFixture,
) -> None:
    ctx = SimpleNamespace(
        method="tools/call", request_id="req-7", params={"name": "agy_worker"}
    )

    async def call_next(_ctx: object) -> object:
        raise ExceptionGroup("outer failure", [ValueError("root needle")])

    with (
        caplog.at_level(logging.INFO, logger="gpt_dive.runtime"),
        pytest.raises(ExceptionGroup),
    ):
        asyncio.run(request_lifecycle_middleware(ctx, call_next))

    assert "MCP REQUEST START" in caplog.text
    assert "request=req-7" in caplog.text
    assert "tool=agy_worker" in caplog.text
    assert "MCP REQUEST ERROR" in caplog.text
    assert "root needle" in caplog.text


def test_request_lifecycle_logs_and_reraises_cancellation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    ctx = SimpleNamespace(
        method="tools/call", request_id="req-cancel", params={"name": "agy_worker"}
    )

    async def call_next(_ctx: object) -> object:
        raise asyncio.CancelledError

    with (
        caplog.at_level(logging.INFO, logger="gpt_dive.runtime"),
        pytest.raises(asyncio.CancelledError),
    ):
        asyncio.run(request_lifecycle_middleware(ctx, call_next))

    assert "MCP REQUEST CANCEL" in caplog.text
    assert "request=req-cancel" in caplog.text


def test_run_mcp_server_logs_start_versions_and_exception_tree(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FakeServer:
        def run(self) -> None:
            raise ExceptionGroup("server group", [RuntimeError("server root needle")])

    with (
        caplog.at_level(logging.INFO, logger="gpt_dive.runtime"),
        pytest.raises(ExceptionGroup),
    ):
        run_mcp_server(FakeServer())

    assert "GPT-DIVE PROCESS START" in caplog.text
    assert "mcp=" in caplog.text
    assert "anyio=" in caplog.text
    assert "GPT-DIVE SERVER EXIT reason=exception" in caplog.text
    assert "server root needle" in caplog.text
    assert "GPT-DIVE PROCESS STOP" in caplog.text


def test_process_diagnostics_use_stderr_not_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime_logger = logging.getLogger("gpt_dive.runtime")
    handler = logging.StreamHandler()
    previous_level = runtime_logger.level
    previous_propagate = runtime_logger.propagate
    runtime_logger.addHandler(handler)
    runtime_logger.setLevel(logging.INFO)
    runtime_logger.propagate = False

    class FakeServer:
        def run(self) -> None:
            return None

    try:
        run_mcp_server(FakeServer())
    finally:
        runtime_logger.removeHandler(handler)
        runtime_logger.setLevel(previous_level)
        runtime_logger.propagate = previous_propagate

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "GPT-DIVE PROCESS START" in captured.err
    assert "GPT-DIVE PROCESS STOP" in captured.err
