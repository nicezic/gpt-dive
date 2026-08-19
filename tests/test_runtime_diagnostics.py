from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest

from gpt_dive.runtime_diagnostics import request_lifecycle_middleware, run_mcp_server


def test_request_lifecycle_middleware_is_registered() -> None:
    from gpt_dive.app import mcp

    assert request_lifecycle_middleware in mcp.middleware


def test_request_lifecycle_logs_nested_exception_group(caplog: pytest.LogCaptureFixture) -> None:
    ctx = SimpleNamespace(method="tools/call", request_id="req-7", params={"name": "agy_worker"})

    async def call_next(_ctx: object) -> object:
        raise ExceptionGroup("outer failure", [ValueError("root needle")])

    with caplog.at_level(logging.INFO, logger="gpt_dive.runtime"), pytest.raises(
        ExceptionGroup
    ):
        asyncio.run(request_lifecycle_middleware(ctx, call_next))

    assert "MCP REQUEST START" in caplog.text
    assert "request=req-7" in caplog.text
    assert "tool=agy_worker" in caplog.text
    assert "MCP REQUEST ERROR" in caplog.text
    assert "root needle" in caplog.text


def test_request_lifecycle_logs_and_reraises_cancellation(caplog: pytest.LogCaptureFixture) -> None:
    ctx = SimpleNamespace(method="tools/call", request_id="req-cancel", params={"name": "agy_worker"})

    async def call_next(_ctx: object) -> object:
        raise asyncio.CancelledError

    with caplog.at_level(logging.INFO, logger="gpt_dive.runtime"), pytest.raises(
        asyncio.CancelledError
    ):
        asyncio.run(request_lifecycle_middleware(ctx, call_next))

    assert "MCP REQUEST CANCEL" in caplog.text
    assert "request=req-cancel" in caplog.text


def test_run_mcp_server_logs_start_versions_and_exception_tree(caplog: pytest.LogCaptureFixture) -> None:
    class FakeServer:
        def run(self) -> None:
            raise ExceptionGroup("server group", [RuntimeError("server root needle")])

    with caplog.at_level(logging.INFO, logger="gpt_dive.runtime"), pytest.raises(
        ExceptionGroup
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
