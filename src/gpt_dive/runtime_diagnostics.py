from __future__ import annotations

import asyncio
import json
import logging
import time
import traceback
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from mcp_types import CallToolResult, TextContent

logger = logging.getLogger("gpt_dive.runtime")

_RUNTIME_PACKAGES = (
    ("gpt-dive", "gpt-dive"),
    ("mcp", "mcp"),
    ("anyio", "anyio"),
    ("pydantic-ai-slim", "pydantic-ai-slim"),
    ("pydantic-ai-harness", "pydantic-ai-harness"),
)


def runtime_versions() -> str:
    """Return a compact startup snapshot for incident correlation."""
    values: list[str] = []
    for label, distribution in _RUNTIME_PACKAGES:
        try:
            installed = version(distribution)
        except PackageNotFoundError:
            installed = "unknown"
        values.append(f"{label}={installed}")
    return " ".join(values)


def _request_id(ctx: Any) -> str:
    value = getattr(ctx, "request_id", None)
    if value is None:
        request_context = getattr(ctx, "request_context", None)
        value = getattr(request_context, "request_id", None)
    return str(value) if value is not None else "-"


def _tool_name(ctx: Any) -> str:
    if getattr(ctx, "method", None) != "tools/call":
        return "-"
    params = getattr(ctx, "params", None)
    if isinstance(params, dict):
        value = params.get("name")
    else:
        value = getattr(params, "name", None)
    return value if isinstance(value, str) and value else "-"


def _exception_text(exc: BaseException) -> str:
    """Preserve Python's recursive ExceptionGroup traceback formatting."""
    return "".join(traceback.format_exception(exc)).rstrip()


def _log_exception(prefix: str, exc: BaseException) -> None:
    logger.error("%s\n%s", prefix, _exception_text(exc))


async def normalize_tool_error_middleware(ctx: Any, call_next: Any) -> Any:
    """Give generic unexpected tool failures stable model-visible provenance."""
    result = await call_next(ctx)
    if getattr(ctx, "method", None) != "tools/call" or not isinstance(
        result, CallToolResult
    ):
        return result
    if not result.is_error or not result.content:
        return result

    tool = _tool_name(ctx)
    first = result.content[0]
    if (
        not isinstance(first, TextContent)
        or first.text != f"Error executing tool {tool}"
    ):
        return result

    request_id = _request_id(ctx)
    payload = {
        "status": "failed",
        "error": {
            "boundary": "mcp_server",
            "code": "MCP.SERVER.UNHANDLED",
            "message": "The MCP server observed an unexpected tool failure.",
        },
        "request_id": request_id,
        "tool": tool,
        "recovery": "inspect_boundary",
        "guidance": (
            "Match request_id and tool in GPT Dive server diagnostics; the cause is "
            "not known from this payload. Check whether the original execution "
            "ran before retrying any side-effectful request."
        ),
    }
    logger.warning(
        "MCP TOOL ERROR boundary=mcp_server code=MCP.SERVER.UNHANDLED request=%s tool=%s",
        request_id,
        tool,
    )
    content = [
        TextContent(
            type="text",
            text=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        ),
        *result.content[1:],
    ]
    return result.model_copy(update={"content": content})


async def request_lifecycle_middleware(ctx: Any, call_next: Any) -> Any:
    """Observe every inbound MCP request without changing request semantics."""
    method = str(getattr(ctx, "method", "-"))
    request_id = _request_id(ctx)
    tool = _tool_name(ctx)
    started = time.perf_counter()
    logger.info(
        "MCP REQUEST START method=%s request=%s tool=%s",
        method,
        request_id,
        tool,
    )
    try:
        result = await call_next(ctx)
    except asyncio.CancelledError:
        logger.warning(
            "MCP REQUEST CANCEL method=%s request=%s tool=%s elapsed_ms=%.1f",
            method,
            request_id,
            tool,
            (time.perf_counter() - started) * 1000,
        )
        raise
    except BaseException as exc:
        _log_exception(
            "MCP REQUEST ERROR "
            f"method={method} request={request_id} tool={tool} "
            f"elapsed_ms={(time.perf_counter() - started) * 1000:.1f}",
            exc,
        )
        raise
    logger.info(
        "MCP REQUEST DONE method=%s request=%s tool=%s elapsed_ms=%.1f",
        method,
        request_id,
        tool,
        (time.perf_counter() - started) * 1000,
    )
    return result


def run_mcp_server(server: Any) -> None:
    """Run the MCP server while preserving process-level failure evidence."""
    logger.info("GPT-DIVE PROCESS START %s", runtime_versions())
    try:
        server.run()
    except BaseException as exc:
        _log_exception("GPT-DIVE SERVER EXIT reason=exception", exc)
        raise
    else:
        logger.info("GPT-DIVE SERVER EXIT reason=normal")
    finally:
        logger.info("GPT-DIVE PROCESS STOP")
